"""Offline tests for the client-namespaced Jevbox evidence tool (fake Jevbox via httpx.MockTransport)."""

from __future__ import annotations

import httpx

import deerflow.community.jevbox.tools as jevbox

AUTHORIZED_A = "aaaaaaaa-0000-0000-0000-000000000001"
AUTHORIZED_B = "aaaaaaaa-0000-0000-0000-000000000002"
OTHER_CLIENT_DOC = "bbbbbbbb-0000-0000-0000-000000000009"
PASSWORD = "fake-password-never-echoed"


def _doc(doc_id: str, name: str, text: str) -> dict:
    return {
        "id": doc_id,
        "kind": "document",
        "name": name,
        "status": "ready",
        "parsed": {"nodes": [{"id": "n1", "passages": [], "children": [{"id": "n2", "children": [], "passages": [{"id": f"p-{doc_id[-1]}", "content": text}]}]}]},
    }


DOCS = {
    AUTHORIZED_A: _doc(AUTHORIZED_A, "01-client-route.md", "Bar crawl route covers parking and wristband pickup."),
    AUTHORIZED_B: _doc(AUTHORIZED_B, "02-draft.md", "Event date conflicts noted for October parking."),
    # Strongest match for the query, but it belongs to another client.
    OTHER_CLIENT_DOC: _doc(OTHER_CLIENT_DOC, "secret-other-client.md", "parking parking parking wristband route event October"),
}


class FakeJevbox:
    def __init__(self, *, login_status: int = 200, docs: dict | None = None, aliases: dict | None = None, fail: int | None = None):
        self.requests: list[str] = []
        self.origins: list[str | None] = []
        self.login_status = login_status
        self.docs = DOCS if docs is None else docs
        self.aliases = aliases or {}
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        self.origins.append(request.headers.get("Origin"))
        if request.url.path == "/api/auth/sign-in/email":
            return httpx.Response(self.login_status, json={})
        if self.fail:
            return httpx.Response(self.fail, json={})
        doc_id = request.url.path.rsplit("/", 1)[-1]
        doc_id = self.aliases.get(doc_id, doc_id)
        if doc_id in self.docs:
            return httpx.Response(200, json=self.docs[doc_id])
        return httpx.Response(404, json={"error": "Not found"})


def _settings(**namespaces) -> jevbox.JevboxSettings:
    return jevbox.JevboxSettings(
        base_url="http://jevbox.test",
        email="owner@example.test",
        password=PASSWORD,
        namespaces=namespaces or {"bar-crawl-usa": [AUTHORIZED_A, AUTHORIZED_B], "other-client": [OTHER_CLIENT_DOC]},
    )


def _retrieve(fake: FakeJevbox, client_id: str = "bar-crawl-usa", query: str = "parking route wristband October", **kwargs):
    return jevbox.retrieve_evidence(kwargs.pop("settings", _settings()), client_id, query, transport=httpx.MockTransport(fake), **kwargs)


def test_returns_cited_passages_for_the_client_namespace():
    fake = FakeJevbox()
    result = _retrieve(fake)
    assert result.status == "ok"
    assert {p.document_id for p in result.passages} == {AUTHORIZED_A, AUTHORIZED_B}
    assert all(p.locator.startswith(f"jevbox:{p.document_id}:") for p in result.passages)
    assert {doc for doc, verdict, _ in result.review if verdict == "accepted"} == {AUTHORIZED_A, AUTHORIZED_B}
    text = jevbox.format_result(result, "bar-crawl-usa")
    assert "[J1]" in text and "Evidence review:" in text


def test_negative_unauthorized_document_is_never_returned_or_fetched():
    fake = FakeJevbox()
    result = _retrieve(fake)
    text = jevbox.format_result(result, "bar-crawl-usa")
    assert OTHER_CLIENT_DOC not in {p.document_id for p in result.passages}
    assert OTHER_CLIENT_DOC not in text and "secret-other-client" not in text
    assert not any(OTHER_CLIENT_DOC in path for path in fake.requests)


def test_negative_server_substituting_another_document_is_rejected():
    fake = FakeJevbox(aliases={AUTHORIZED_A: OTHER_CLIENT_DOC})
    result = _retrieve(fake)
    assert OTHER_CLIENT_DOC not in {p.document_id for p in result.passages}
    assert (AUTHORIZED_A, "rejected", "response did not match the requested document") in result.review


def test_agent_bound_to_another_client_is_denied_before_any_request():
    fake = FakeJevbox()
    result = _retrieve(fake, client_id="other-client", bound_client_id="bar-crawl-usa")
    assert result.status == "denied" and not result.passages
    assert fake.requests == []


def test_unbound_or_invalid_client_is_denied():
    fake = FakeJevbox()
    assert _retrieve(fake, client_id="unknown-client").status == "denied"
    assert _retrieve(fake, client_id="../etc").status == "denied"
    assert fake.requests == []


def test_missing_document_is_rejected_not_fatal():
    fake = FakeJevbox(docs={AUTHORIZED_B: DOCS[AUTHORIZED_B]})
    result = _retrieve(fake)
    assert result.status == "ok"
    assert (AUTHORIZED_A, "rejected", "not readable (HTTP 404)") in result.review
    assert {p.document_id for p in result.passages} == {AUTHORIZED_B}


def test_auth_failure_and_server_errors_degrade_to_unavailable():
    for fake in (FakeJevbox(login_status=401), FakeJevbox(fail=503)):
        result = _retrieve(fake)
        assert result.status == "unavailable"
        text = jevbox.format_result(result, "bar-crawl-usa")
        assert text.startswith(jevbox.UNAVAILABLE) and PASSWORD not in text


def test_connection_error_degrades_to_unavailable():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = jevbox.retrieve_evidence(_settings(), "bar-crawl-usa", "parking", transport=httpx.MockTransport(down))
    assert result.status == "unavailable" and result.reason == "connection failed"


def test_tool_entrypoint_returns_library_unavailable_when_jevbox_is_down(monkeypatch):
    # Real socket to a closed loopback port: no mocks between the tool and the network.
    settings = _settings()
    settings.base_url = "http://127.0.0.1:9"
    monkeypatch.setattr(jevbox, "_settings", lambda: settings)
    text = jevbox._run("bar-crawl-usa", "parking", None)
    assert text.startswith("Jevbox library unavailable")


def test_tool_entrypoint_reports_unconfigured_as_unavailable(monkeypatch):
    monkeypatch.setattr(jevbox, "_settings", lambda: None)
    assert jevbox._run("bar-crawl-usa", "parking", None).startswith("Jevbox library unavailable")


def test_agent_binding_load_failure_fails_closed(monkeypatch):
    import deerflow.config.agents_config as agents_config

    def broken(name, **kwargs):
        raise ValueError("corrupt")

    monkeypatch.setattr(jevbox, "_settings", _settings)
    monkeypatch.setattr(agents_config, "load_agent_config", broken)
    runtime = type("R", (), {"context": {"agent_name": "client-agent"}})()
    assert "agent client binding could not be verified" in jevbox._run("bar-crawl-usa", "parking", runtime)


def test_agent_stamped_client_id_is_enforced(monkeypatch):
    import deerflow.config.agents_config as agents_config

    monkeypatch.setattr(jevbox, "_settings", _settings)
    monkeypatch.setattr(agents_config, "load_agent_config", lambda name, **kwargs: type("A", (), {"client_id": "bar-crawl-usa"})())
    runtime = type("R", (), {"context": {"agent_name": "bar-crawl-agent"}})()
    assert "bound to a different client namespace" in jevbox._run("other-client", "parking", runtime)


def test_tool_assembles_from_config_with_only_model_safe_arguments():
    from types import SimpleNamespace

    from deerflow.config.tool_config import ToolConfig
    from deerflow.tools.tools import get_available_tools

    tool_config = ToolConfig(name="jevbox_evidence", group="research", use="deerflow.community.jevbox.tools:jevbox_evidence_tool", email="owner@example.test", password=PASSWORD, namespaces={"bar-crawl-usa": [AUTHORIZED_A]})
    config = SimpleNamespace(
        tools=[tool_config],
        knowledge_base=SimpleNamespace(enabled=False),
        sandbox=SimpleNamespace(use="example.remote:Sandbox"),
        skill_evolution=SimpleNamespace(enabled=False),
        models=[],
        acp_agents={},
        get_model_config=lambda name: None,
    )
    tool = next(t for t in get_available_tools(include_mcp=False, app_config=config) if t.name == "jevbox_evidence")
    assert set(tool.tool_call_schema.model_fields) == {"client_id", "query"}
    assert PASSWORD not in tool.description and AUTHORIZED_A not in tool.description


def test_origin_override_is_sent_for_container_base_urls():
    fake = FakeJevbox()
    settings = _settings()
    settings.base_url = "http://host.docker.internal:4310"
    settings.origin = "http://localhost:4310"
    assert _retrieve(fake, settings=settings).status == "ok"
    assert set(fake.origins) == {"http://localhost:4310"}
