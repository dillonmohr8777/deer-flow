"""Read-only, client-namespaced evidence retrieval from the Jevbox research library.

Jevbox is Momo's supporting research library, not a dependency: every failure
returns a plain "library unavailable" tool result so the agent's task continues.

Permission model (all startup-owned, nothing the model can widen):
- ``namespaces`` in config.yaml maps a client ID to the exact Jevbox document IDs
  that client may see. Only those IDs are ever requested; anything else Jevbox
  holds is never fetched or returned.
- An agent stamped with a ``client_id`` (fleet agents) may only query its own
  namespace.
- Only $0 owner-session REST reads are used (``/api/resources/:id``). Jevbox
  search/answer endpoints queue paid model runs and are deliberately not called.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, ValidationError

from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

TOOL_NAME = "jevbox_evidence"
UNAVAILABLE = "Jevbox library unavailable"
_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_WORD = re.compile(r"[a-z0-9]{3,}")


class JevboxSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: AnyHttpUrl = Field(default="http://localhost:4310")
    # Jevbox rejects sign-in unless Origin equals its APP_ORIGIN. Set this when
    # base_url differs from it (e.g. host.docker.internal from a container).
    origin: AnyHttpUrl | None = None
    email: SecretStr | None = None
    password: SecretStr | None = None
    timeout: float = Field(default=10, gt=0, le=60)
    top_k: int = Field(default=4, ge=1, le=12)
    max_chars_per_passage: int = Field(default=1200, ge=100, le=6000)
    namespaces: dict[str, list[str]] = Field(default_factory=dict)


@dataclass(frozen=True)
class Passage:
    document_id: str
    document_name: str
    passage_id: str
    text: str
    score: int

    @property
    def locator(self) -> str:
        return f"jevbox:{self.document_id}:{self.passage_id}"


@dataclass(frozen=True)
class EvidenceResult:
    status: str  # "ok" | "denied" | "unavailable"
    reason: str
    passages: tuple[Passage, ...] = ()
    review: tuple[tuple[str, str, str], ...] = ()  # (document_id, accepted|rejected, reason)


class _Unavailable(Exception):
    pass


def _secret(value: SecretStr | None) -> str:
    return value.get_secret_value().strip() if value is not None else ""


def _walk_passages(nodes: list[Any]):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        for passage in node.get("passages") or []:
            if isinstance(passage, dict) and isinstance(passage.get("content"), str):
                yield str(passage.get("id") or ""), passage["content"]
        yield from _walk_passages(node.get("children") or [])


def _score(query_terms: set[str], text: str) -> int:
    words = _WORD.findall(text.lower())
    return sum(1 for word in words if word in query_terms)


def _get(client: httpx.Client, path: str) -> httpx.Response:
    try:
        return client.get(path)
    except httpx.HTTPError:
        raise _Unavailable("connection failed") from None


def retrieve_evidence(
    settings: JevboxSettings,
    client_id: str,
    query: str,
    *,
    bound_client_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> EvidenceResult:
    """Return cited passages for ``client_id`` only. Never raises."""
    if not _ID.fullmatch(client_id or ""):
        return EvidenceResult("denied", "invalid client_id")
    if bound_client_id is not None and bound_client_id != client_id:
        return EvidenceResult("denied", "this agent is bound to a different client namespace")
    allowed = [doc for doc in settings.namespaces.get(client_id, []) if _ID.fullmatch(doc)]
    if not allowed:
        return EvidenceResult("denied", "no Jevbox documents are bound to this client namespace")
    terms = set(_WORD.findall((query or "").lower()))
    if not terms:
        return EvidenceResult("denied", "query has no searchable terms")
    email, password = _secret(settings.email), _secret(settings.password)
    if not email or not password:
        return EvidenceResult("unavailable", "credentials not configured")

    base = str(settings.base_url).rstrip("/")
    origin = str(settings.origin or settings.base_url).rstrip("/")
    headers = {"Origin": origin, "Referer": origin + "/", "X-Jevbox-Request": "1", "Accept": "application/json"}
    passages: list[Passage] = []
    review: list[tuple[str, str, str]] = []
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=settings.timeout, transport=transport, trust_env=False, follow_redirects=False) as client:
            try:
                login = client.post("/api/auth/sign-in/email", json={"email": email, "password": password})
            except httpx.HTTPError:
                raise _Unavailable("connection failed") from None
            if login.status_code != 200:
                raise _Unavailable(f"sign-in returned HTTP {login.status_code}")
            for document_id in allowed:
                response = _get(client, f"/api/resources/{document_id}")
                if response.status_code >= 500:
                    raise _Unavailable(f"server returned HTTP {response.status_code}")
                if response.status_code != 200:
                    review.append((document_id, "rejected", f"not readable (HTTP {response.status_code})"))
                    continue
                resource = response.json()
                # Defence in depth: the server must echo the exact ID we asked for.
                if resource.get("id") != document_id or resource.get("kind") != "document":
                    review.append((document_id, "rejected", "response did not match the requested document"))
                    continue
                if resource.get("status") != "ready" or not isinstance(resource.get("parsed"), dict):
                    review.append((document_id, "rejected", "document is not indexed"))
                    continue
                name = str(resource.get("name") or document_id)[:256]
                matched = 0
                for passage_id, text in _walk_passages(resource["parsed"].get("nodes") or []):
                    score = _score(terms, text)
                    if score and _ID.fullmatch(passage_id):
                        matched += 1
                        passages.append(Passage(document_id, name, passage_id, text[: settings.max_chars_per_passage], score))
                review.append((document_id, "accepted", f"{matched} matching passages") if matched else (document_id, "rejected", "no passage matched the query"))
    except _Unavailable as exc:
        return EvidenceResult("unavailable", str(exc))
    except (httpx.HTTPError, ValueError):
        return EvidenceResult("unavailable", "unexpected response")

    # Final namespace gate: nothing outside the allowlist can leave this function.
    allowed_set = set(allowed)
    passages = [p for p in passages if p.document_id in allowed_set]
    passages.sort(key=lambda p: (-p.score, p.document_id, p.passage_id))
    return EvidenceResult("ok", "retrieved", tuple(passages[: settings.top_k]), tuple(review))


def format_result(result: EvidenceResult, client_id: str) -> str:
    if result.status == "unavailable":
        return f"{UNAVAILABLE} ({result.reason}). Continue the task without library evidence and say so."
    if result.status == "denied":
        return f"Jevbox evidence denied for client '{client_id}': {result.reason}."
    lines = [f"Jevbox evidence for client '{client_id}' ({len(result.passages)} cited passages). Cite sources by their [J#] locator."]
    for index, passage in enumerate(result.passages, 1):
        digest = hashlib.sha256(passage.text.encode()).hexdigest()
        lines.append(f"\n[J{index}] {passage.document_name} — {passage.locator} (sha256 {digest[:12]})\n{passage.text}")
    if not result.passages:
        lines.append("No passage matched the query.")
    lines.append("\nEvidence review:")
    lines.extend(f"- {doc}: {verdict} — {why}" for doc, verdict, why in result.review)
    return "\n".join(lines)


def _settings() -> JevboxSettings | None:
    from deerflow.config import get_app_config

    tool_config = get_app_config().get_tool_config(TOOL_NAME)
    if tool_config is None:
        return None
    try:
        return JevboxSettings.model_validate(dict(getattr(tool_config, "model_extra", None) or {}))
    except ValidationError:
        logger.warning("jevbox_evidence tool configuration is invalid")
        return None


def _bound_client_id(runtime: Runtime | None) -> tuple[bool, str | None]:
    """Return (ok, client_id) for the running agent; fail closed on load errors."""
    context = getattr(runtime, "context", None) or {}
    agent_name = context.get("agent_name") if isinstance(context, dict) else None
    if not agent_name:
        return True, None
    from deerflow.config.agents_config import load_agent_config

    try:
        agent = load_agent_config(agent_name)
    except FileNotFoundError:
        return True, None  # Built-in agent: no client stamp exists.
    except Exception:
        return False, None
    return True, getattr(agent, "client_id", None)


def _run(client_id: str, query: str, runtime: Runtime | None) -> str:
    settings = _settings()
    if settings is None:
        return format_result(EvidenceResult("unavailable", "not configured"), client_id)
    ok, bound = _bound_client_id(runtime)
    if not ok:
        return format_result(EvidenceResult("denied", "agent client binding could not be verified"), client_id)
    return format_result(retrieve_evidence(settings, client_id, query, bound_client_id=bound), client_id)


async def _jevbox_evidence(client_id: str, query: str, runtime: Runtime) -> str:
    """Retrieve cited evidence passages from the Jevbox research library for one client.

    Args:
        client_id: Client namespace to search, for example "bar-crawl-usa". Only documents bound to this client are searched.
        query: Specific question or keywords to find in that client's library documents.
    """
    # Blocking HTTP and agent-store reads stay off the event loop.
    return await asyncio.to_thread(_run, client_id, query, runtime)


jevbox_evidence_tool = StructuredTool.from_function(
    coroutine=_jevbox_evidence,
    name=TOOL_NAME,
    description=(
        "Search the Jevbox research library for cited evidence scoped to one client namespace. "
        "Returns [J#] passages with jevbox:<document>:<passage> locators plus an accept/reject review per document. "
        "If it reports the library is unavailable, continue the task without it."
    ),
    parse_docstring=True,
)
