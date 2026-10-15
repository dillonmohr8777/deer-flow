"""One-client Netlify deploy: reuse the live file digests for every other path, replace only this client's page.

Netlify deploys are whole-site snapshots, so the new manifest is the live manifest with
this client's files swapped in. Every other path keeps its live sha, nothing else is uploaded,
and the result is verified by sha afterwards.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx
from deerflow.approvals import AdapterOutcome

from deerflow_report_studio.render import Settings, bundle_sha256, load_staged

API = "https://api.netlify.com/api/v1"


class DeployError(RuntimeError):
    """A deploy was refused or failed verification. The message never contains credentials."""


class NetlifyClient(Protocol):
    def list_files(self, site_id: str) -> dict[str, str]: ...  # path -> sha1 of the published deploy
    def create_deploy(self, site_id: str, files: dict[str, str]) -> dict[str, Any]: ...  # {"id", "required": [sha1, ...]}
    def upload(self, deploy_id: str, path: str, data: bytes) -> None: ...
    def deploy_state(self, deploy_id: str) -> str: ...
    def url_status(self, url: str) -> int: ...


class HttpNetlifyClient:
    """The real client. Only used by the adapter at execution time; tests use a fake."""

    def __init__(self, token: str) -> None:
        self._http = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=60, follow_redirects=True)

    def list_files(self, site_id: str) -> dict[str, str]:
        r = self._http.get(f"/sites/{site_id}/files")
        r.raise_for_status()
        return {"/" + f["id"].lstrip("/"): f["sha"] for f in r.json()}

    def create_deploy(self, site_id: str, files: dict[str, str]) -> dict[str, Any]:
        r = self._http.post(f"/sites/{site_id}/deploys", json={"files": files})
        r.raise_for_status()
        return r.json()

    def upload(self, deploy_id: str, path: str, data: bytes) -> None:
        r = self._http.put(f"/deploys/{deploy_id}/files{path}", content=data, headers={"Content-Type": "application/octet-stream"})
        r.raise_for_status()

    def deploy_state(self, deploy_id: str) -> str:
        r = self._http.get(f"/deploys/{deploy_id}")
        r.raise_for_status()
        return r.json()["state"]

    def url_status(self, url: str) -> int:
        return httpx.get(url, timeout=30, follow_redirects=True).status_code


def sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()  # Netlify's file digest


def deploy_one_client(
    client: NetlifyClient,
    *,
    site_id: str,
    site_url: str,
    client_id: str,
    staged: dict[str, bytes],
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 30,
) -> dict[str, Any]:
    page = f"/reports/{client_id}/index.html"
    if page not in staged or any(p != page and not p.startswith("/assets/") for p in staged):
        raise DeployError(f"Staged files must be {page} plus /assets/ files only")
    live = client.list_files(site_id)
    if not live:
        raise DeployError("Live site listing is empty; refusing to deploy a one-page snapshot")
    new = {p: sha1(b) for p, b in staged.items()}
    for path in staged:
        if path.startswith("/assets/") and path in live and live[path] != new[path]:
            raise DeployError(f"{path} already exists live with different content; it could change another page")
    manifest = {**live, **new}
    deploy = client.create_deploy(site_id, manifest)
    needed = set(deploy.get("required", []))
    for path, digest in new.items():
        if digest in needed:
            client.upload(deploy["id"], path, staged[path])
            needed.discard(digest)
    for _ in range(attempts):
        state = client.deploy_state(deploy["id"])
        if state == "ready":
            break
        if state == "error":
            raise DeployError("Netlify reported the deploy failed")
        sleep(2)
    else:
        raise DeployError("Netlify deploy did not become ready in time; check Netlify before retrying")
    after = client.list_files(site_id)
    changed = sorted(p for p in set(live) | set(after) if live.get(p) != after.get(p))
    stray = [p for p in changed if p not in new]
    if stray:
        raise DeployError(f"Deploy is live but other files changed: {stray[:5]}. Check Netlify.")
    url = f"{site_url}/reports/{client_id}/"
    status = client.url_status(url)
    if status != 200:
        raise DeployError(f"Deploy is live but {url} returned {status}")
    return {"deploy_id": deploy["id"], "url": url, "changed": changed, "others_unchanged": len(live) - len([p for p in new if p in live])}


class DeployReportAdapter:
    """Runs only for the caller that won pending->approved (see ``execute_approved``)."""

    def __init__(self, settings: Settings, client_factory: Callable[[str], NetlifyClient] = HttpNetlifyClient) -> None:
        self._settings = settings
        self._client_factory = client_factory

    async def execute(self, action: dict[str, Any]) -> AdapterOutcome:
        s, client_id, week = self._settings, action["target"], str(action["payload"].get("week", ""))
        token = os.environ.get(s.token_env, "")
        if not token:
            return AdapterOutcome("failed", error=f"{s.token_env} is not set on this Gateway")
        try:
            staged = load_staged(s, client_id, week)
        except OSError:
            staged = {}
        if not staged or bundle_sha256(staged) != action["payload"].get("bundle_sha256"):
            return AdapterOutcome("failed", error="Staged page is missing or changed since it was proposed; rebuild and propose again")
        try:
            detail = await asyncio.to_thread(deploy_one_client, self._client_factory(token), site_id=s.site_id, site_url=s.site_url, client_id=client_id, staged=staged)
        except (DeployError, httpx.HTTPError) as exc:
            return AdapterOutcome("failed", error=f"Deploy failed: {type(exc).__name__}: {exc}" if isinstance(exc, DeployError) else f"Netlify request failed: {type(exc).__name__}")
        return AdapterOutcome("executed", detail)
