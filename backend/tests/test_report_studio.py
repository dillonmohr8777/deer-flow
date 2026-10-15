"""Report Studio extension: render, one-client isolation, approval gating. No network; Netlify is a fake."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import USER_A, acting_as, auth_headers, org_world  # noqa: F401

from app.gateway import approval_adapters
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import approvals
from deerflow.approvals import InvalidPayloadError, register_action_type, validate_payload, workflow
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.tools.builtins.propose_action_tool import propose_action

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "extensions" / "report-studio"))

from deerflow_report_studio import render, validate_deploy  # noqa: E402
from deerflow_report_studio.deploy import DeployError, DeployReportAdapter, deploy_one_client, sha1  # noqa: E402

LOGO = b"\x89PNG fake logo bytes"
SECTIONS = [{"heading": "Results", "body": "Clicks rose, then fell \u2014 a bit.", "metrics": [{"label": "Clicks", "value": "120"}], "items": ["<b>raw</b> item"]}]
WEEK = "2026-10-05"


# --- fakes -------------------------------------------------------------------


class FakeNetlify:
    """An in-memory Netlify site. ``live`` maps path -> content bytes."""

    def __init__(self, live: dict[str, bytes], *, status: int = 200, tamper: str | None = None, state: str = "ready"):
        self.live, self.status, self.tamper, self.state = dict(live), status, tamper, state
        self.deploys: list[dict[str, str]] = []
        self.uploads: list[str] = []
        self._pending: dict[str, dict[str, bytes]] = {}
        self._blobs = {sha1(v): v for v in live.values()}

    def list_files(self, site_id):
        return {p: sha1(b) for p, b in self.live.items()}

    def create_deploy(self, site_id, files):
        self.deploys.append(files)
        known = {sha1(b) for b in self.live.values()}
        return {"id": f"d{len(self.deploys)}", "required": sorted({s for s in files.values() if s not in known})}

    def upload(self, deploy_id, path, data):
        self.uploads.append(path)
        self._blobs[sha1(data)] = data

    def deploy_state(self, deploy_id):
        if self.state == "ready":
            manifest = self.deploys[-1]
            self.live = {p: self._blobs[s] for p, s in manifest.items()}
            if self.tamper:
                self.live[self.tamper] = b"changed by something else"
        return self.state

    def url_status(self, url):
        return self.status


SITE = {
    "/index.html": b"ops",
    "/reports/report.css": b"css",
    "/reports/client-b/index.html": b"B page",
    "/reports/client-c/index.html": b"C page",
    "/assets/client-b.png": b"B logo",
}


@pytest.fixture()
def settings(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "client-a.png").write_bytes(LOGO)
    s = render.Settings(staging_dir=tmp_path / "staging", assets_dir=assets, site_id="site-1", site_url="https://reports.example.test")
    render.configure(s)
    yield s
    render.configure(None)


def _build(settings, client="client-a", week=WEEK):
    return render.build(settings, client, week, SECTIONS, "Client A")


# --- render -------------------------------------------------------------------


def test_render_uses_only_passed_data_and_the_existing_logo(settings):
    out = _build(settings)
    html = (Path(out["staging_path"]) / "reports/client-a/index.html").read_text()
    assert "Client A weekly report" in html and ">120<" in html and 'src="../../assets/client-a.png"' in html
    assert "<b>raw</b>" not in html and "&lt;b&gt;raw&lt;/b&gt;" in html  # escaped, not injected
    assert "\u2014" not in html and "brand-float" in html and "prefers-reduced-motion" in html
    assert (Path(out["staging_path"]) / "assets/client-a.png").read_bytes() == LOGO  # copied, not generated
    assert out["files"] == ["/assets/client-a.png", "/reports/client-a/index.html"]
    assert out["bundle_sha256"] == render.bundle_sha256(render.load_staged(settings, "client-a", WEEK))


def test_render_refuses_missing_logo_empty_sections_and_bad_ids(settings):
    with pytest.raises(FileNotFoundError, match="never generated"):
        render.build(settings, "client-z", WEEK, SECTIONS)
    for args in [("client-a", WEEK, []), ("../evil", WEEK, SECTIONS), ("client-a", "../../x", SECTIONS)]:
        with pytest.raises(ValueError):
            render.build(settings, *args)


def test_build_report_page_tool_returns_bundle_and_reports_errors(settings):
    out = json.loads(render.build_report_page.invoke({"client_id": "client-a", "week": WEEK, "sections": SECTIONS}))
    assert len(out["bundle_sha256"]) == 64
    assert render.build_report_page.invoke({"client_id": "client-z", "week": WEEK, "sections": SECTIONS}).startswith("Not built")


# --- one-client isolation -----------------------------------------------------


def test_deploy_changes_only_the_one_client_by_sha(settings):
    _build(settings)
    fake = FakeNetlify(SITE)
    before = fake.list_files("s")
    detail = deploy_one_client(fake, site_id="s", site_url=settings.site_url, client_id="client-a", staged=render.load_staged(settings, "client-a", WEEK))
    after = fake.list_files("s")
    assert fake.uploads == ["/assets/client-a.png", "/reports/client-a/index.html"]  # nothing else is sent
    assert {p for p in after if before.get(p) != after[p]} == {"/assets/client-a.png", "/reports/client-a/index.html"}
    assert all(after[p] == before[p] for p in before)  # every pre-existing page is byte-identical
    assert detail["url"] == "https://reports.example.test/reports/client-a/"
    assert set(fake.deploys[0]) == set(SITE) | {"/assets/client-a.png", "/reports/client-a/index.html"}


def test_deploy_refuses_anything_that_could_touch_another_client(settings):
    _build(settings)
    staged = render.load_staged(settings, "client-a", WEEK)
    kw = {"site_id": "s", "site_url": settings.site_url, "client_id": "client-a"}
    with pytest.raises(DeployError, match="plus /assets/"):
        deploy_one_client(FakeNetlify(SITE), staged={**staged, "/reports/client-b/index.html": b"x"}, **kw)
    with pytest.raises(DeployError, match="different content"):
        deploy_one_client(FakeNetlify({**SITE, "/assets/client-a.png": b"someone else's"}), staged=staged, **kw)
    with pytest.raises(DeployError, match="empty"):
        deploy_one_client(FakeNetlify({}), staged=staged, **kw)


def test_deploy_verification_fails_loudly_on_other_change_or_bad_url(settings):
    _build(settings)
    staged = render.load_staged(settings, "client-a", WEEK)
    kw = {"site_id": "s", "site_url": settings.site_url, "client_id": "client-a", "staged": staged, "sleep": lambda _: None}
    with pytest.raises(DeployError, match="other files changed"):
        deploy_one_client(FakeNetlify(SITE, tamper="/reports/client-b/index.html"), **kw)
    with pytest.raises(DeployError, match="returned 404"):
        deploy_one_client(FakeNetlify(SITE, status=404), **kw)
    with pytest.raises(DeployError, match="did not become ready"):
        deploy_one_client(FakeNetlify(SITE, state="building"), attempts=2, **kw)


# --- approval gating ----------------------------------------------------------


@pytest.fixture()
def registered(settings, monkeypatch):
    """Install the extension's approval pieces the way ``install()`` does, with a fake Netlify."""
    fake = FakeNetlify(SITE)
    monkeypatch.setenv("NETLIFY_AUTH_TOKEN", "test-token-not-real")
    monkeypatch.setitem(workflow._EXTENSION_TYPES, "deploy_report", validate_deploy)
    monkeypatch.setitem(approval_adapters._EXTENSION_ADAPTERS, "deploy_report", DeployReportAdapter(settings, lambda token: fake))
    return fake


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.pending_action_repo = PendingActionRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.include_router(approvals.router)
    return app


def _http(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _propose_deploy(org_world, settings, **payload):  # noqa: F811
    out = _build(settings)
    runtime = SimpleNamespace(context={"user_id": USER_A, "thread_id": "t", "run_id": "r", "agent_name": "momo"}, config={})
    body = {"action_type": "deploy_report", "title": "Deploy client A report", "target": "client-a", "payload": {"week": WEEK, "bundle_sha256": out["bundle_sha256"], **payload}}
    return json.loads(await propose_action.coroutine(runtime=runtime, **body))


def test_deploy_report_type_is_unknown_until_registered_and_validated_after():
    with pytest.raises(InvalidPayloadError, match="Unknown action type"):
        validate_payload("deploy_report", "client-a", {})
    register_action_type("deploy_report", validate_deploy)
    try:
        good = {"week": WEEK, "bundle_sha256": "a" * 64}
        validate_payload("deploy_report", "client-a", good)
        for target, payload in [("Client A", good), ("client-a", {**good, "week": "soon"}), ("client-a", {**good, "bundle_sha256": "zz"})]:
            with pytest.raises(InvalidPayloadError):
                validate_payload("deploy_report", target, payload)
        with pytest.raises(ValueError):
            register_action_type("email", validate_deploy)
    finally:
        workflow._EXTENSION_TYPES.pop("deploy_report", None)


@pytest.mark.asyncio
async def test_nothing_deploys_before_approval_and_reject_never_deploys(org_world, settings, registered):  # noqa: F811
    out = await _propose_deploy(org_world, settings)
    assert out["status"] == "pending_approval"
    assert registered.deploys == [] and registered.uploads == []
    async with _http(_app(org_world)) as client:
        assert (await client.post(f"/api/approvals/{out['id']}/reject", headers=auth_headers(USER_A))).status_code == 200
    assert registered.deploys == []
    with acting_as(USER_A):
        assert (await PendingActionRepository(org_world).get(out["id"]))["status"] == "rejected"


@pytest.mark.asyncio
async def test_approve_deploys_once_even_when_approved_concurrently(org_world, settings, registered):  # noqa: F811
    out = await _propose_deploy(org_world, settings)
    async with _http(_app(org_world)) as client:
        h = auth_headers(USER_A)
        codes = sorted(r.status_code for r in await asyncio.gather(*[client.post(f"/api/approvals/{out['id']}/approve", headers=h) for _ in range(4)]))
    assert codes.count(200) == 1 and len(registered.deploys) == 1
    with acting_as(USER_A):
        row = await PendingActionRepository(org_world).get(out["id"])
    assert row["status"] == "executed" and row["execution_result"]["url"].endswith("/reports/client-a/")
    assert "test-token-not-real" not in json.dumps(row, default=str)


@pytest.mark.asyncio
async def test_page_changed_after_proposal_or_missing_token_fails_without_deploying(org_world, settings, registered, monkeypatch):  # noqa: F811
    out = await _propose_deploy(org_world, settings)
    (render.stage_dir(settings, "client-a", WEEK) / "reports/client-a/index.html").write_text("swapped after proposal")
    async with _http(_app(org_world)) as client:
        row = (await client.post(f"/api/approvals/{out['id']}/approve", headers=auth_headers(USER_A))).json()
    assert row["status"] == "failed" and "changed since" in row["error"] and registered.deploys == []

    out2 = await _propose_deploy(org_world, settings)
    monkeypatch.delenv("NETLIFY_AUTH_TOKEN")
    async with _http(_app(org_world)) as client:
        row = (await client.post(f"/api/approvals/{out2['id']}/approve", headers=auth_headers(USER_A))).json()
    assert row["status"] == "failed" and "NETLIFY_AUTH_TOKEN" in row["error"] and registered.deploys == []


def test_sha1_matches_netlify_digest():
    assert sha1(b"abc") == hashlib.sha1(b"abc", usedforsecurity=False).hexdigest()
