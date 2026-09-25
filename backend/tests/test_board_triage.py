"""Momo Board thread triage (Workspace Phase 4 item b3).

Mirrors ``test_security_scanner.py``'s fake-model pattern: monkeypatch
``create_chat_model`` where it's imported into ``deerflow.board.triage`` and
feed a canned response, no real API calls.
"""

from types import SimpleNamespace

import pytest

from deerflow.board.triage import BoardThreadTriage, _extract_json_object, triage_board_thread


def _make_env(monkeypatch, response_content):
    config = SimpleNamespace()
    fake_response = SimpleNamespace(content=response_content)

    class FakeModel:
        async def ainvoke(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return fake_response

    model = FakeModel()

    def _fake_create_chat_model(**kwargs):
        model.create_kwargs = kwargs
        return model

    monkeypatch.setattr("deerflow.board.triage.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.triage.create_chat_model", _fake_create_chat_model)
    return model


# --- _extract_json_object unit tests ---


def test_extract_json_plain():
    assert _extract_json_object('{"kind":"ticket","urgency":"high","summary":"s"}') == {"kind": "ticket", "urgency": "high", "summary": "s"}


def test_extract_json_markdown_fence():
    raw = '```json\n{"kind": "ticket", "urgency": "high", "summary": "s"}\n```'
    assert _extract_json_object(raw) == {"kind": "ticket", "urgency": "high", "summary": "s"}


def test_extract_json_returns_none_for_garbage():
    assert _extract_json_object("no json here") is None


# --- triage_board_thread integration tests ---


@pytest.mark.anyio
async def test_triage_classifies_from_model_response(monkeypatch):
    model = _make_env(monkeypatch, '{"kind":"ticket","urgency":"urgent","summary":"Site is down for everyone."}')

    result = await triage_board_thread("Our site has been down for an hour, customers can't check out!", subject="Site down")

    assert result == BoardThreadTriage(kind="ticket", urgency="urgent", summary="Site is down for everyone.")
    assert model.kwargs["config"] == {"run_name": "board_triage"}


@pytest.mark.anyio
async def test_triage_parses_markdown_fenced_response(monkeypatch):
    _make_env(monkeypatch, '```json\n{"kind": "concern", "urgency": "low", "summary": "Asking about next month\'s content calendar."}\n```')

    result = await triage_board_thread("What's on the content calendar for next month?")

    assert result.kind == "concern"
    assert result.urgency == "low"


@pytest.mark.anyio
async def test_triage_parses_responses_api_text_blocks(monkeypatch):
    _make_env(monkeypatch, [{"type": "text", "text": '{"kind":"dm","urgency":"normal","summary":"Says hello."}'}])

    result = await triage_board_thread("Hey, just checking in!")

    assert result.kind == "dm"
    assert result.summary == "Says hello."


@pytest.mark.anyio
async def test_triage_normalizes_case(monkeypatch):
    _make_env(monkeypatch, '{"kind":"TICKET","urgency":"HIGH","summary":"Needs a fix."}')

    result = await triage_board_thread("Something is broken.")

    assert result.kind == "ticket"
    assert result.urgency == "high"


@pytest.mark.anyio
async def test_triage_falls_back_on_invalid_kind(monkeypatch):
    _make_env(monkeypatch, '{"kind":"spam","urgency":"high","summary":"Bad kind."}')

    result = await triage_board_thread("Buy my product now!!!")

    assert result.kind == "ticket"
    assert result.urgency == "normal"


@pytest.mark.anyio
async def test_triage_falls_back_on_invalid_urgency(monkeypatch):
    _make_env(monkeypatch, '{"kind":"post","urgency":"whenever","summary":"Bad urgency."}')

    result = await triage_board_thread("Some post content.")

    assert result.kind == "ticket"
    assert result.urgency == "normal"


@pytest.mark.anyio
async def test_triage_falls_back_on_unparseable_response(monkeypatch):
    _make_env(monkeypatch, "not json at all")

    result = await triage_board_thread("A message the model can't classify.")

    assert result.kind == "ticket"
    assert result.urgency == "normal"
    assert "message the model" in result.summary


@pytest.mark.anyio
async def test_triage_falls_back_when_model_call_fails(monkeypatch):
    config = SimpleNamespace()
    monkeypatch.setattr("deerflow.board.triage.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.triage.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = await triage_board_thread("A message sent while the model is unavailable.")

    assert result.kind == "ticket"
    assert result.urgency == "normal"
    assert result.summary


@pytest.mark.anyio
async def test_triage_fallback_summary_truncates_long_content(monkeypatch):
    _make_env(monkeypatch, "not json at all")

    long_content = "word " * 60
    result = await triage_board_thread(long_content)

    assert len(result.summary) <= 140
    assert result.summary.endswith("…")


@pytest.mark.anyio
async def test_triage_requires_summary_to_accept_model_response(monkeypatch):
    _make_env(monkeypatch, '{"kind":"ticket","urgency":"high","summary":""}')

    result = await triage_board_thread("A ticket with no summary from the model.")

    assert result.kind == "ticket"
    assert result.urgency == "normal"
    assert result.summary


# --- action field ---


@pytest.mark.anyio
async def test_triage_parses_action_from_model_response(monkeypatch):
    _make_env(monkeypatch, '{"kind":"concern","urgency":"high","summary":"Wants a refund.","action":"escalate"}')

    result = await triage_board_thread("I want a refund for last month.")

    assert result.action == "escalate"


@pytest.mark.anyio
async def test_triage_defaults_action_to_draft_when_model_omits_it(monkeypatch):
    _make_env(monkeypatch, '{"kind":"post","urgency":"low","summary":"Says hi."}')

    result = await triage_board_thread("Just saying hi!")

    assert result.action == "draft"


@pytest.mark.anyio
async def test_triage_defaults_action_to_draft_on_invalid_action(monkeypatch):
    _make_env(monkeypatch, '{"kind":"post","urgency":"low","summary":"Says hi.","action":"auto-reply"}')

    result = await triage_board_thread("Just saying hi!")

    assert result.action == "draft"


@pytest.mark.anyio
async def test_triage_falls_back_to_escalate_action_on_unparseable_response(monkeypatch):
    _make_env(monkeypatch, "not json at all")

    result = await triage_board_thread("A message the model can't classify.")

    assert result.action == "escalate"


@pytest.mark.anyio
async def test_triage_falls_back_to_escalate_action_when_model_call_fails(monkeypatch):
    config = SimpleNamespace()
    monkeypatch.setattr("deerflow.board.triage.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.triage.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = await triage_board_thread("A message sent while the model is unavailable.")

    assert result.action == "escalate"
