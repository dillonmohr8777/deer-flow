"""Tests for the verify_quote project-document evidence-check tool (pilot).

``verify_quote`` sits beside ``list_project_documents`` / ``read_project_document``
(Phase-2 spec §7.3 pattern): same pinned-project resolution via
``_resolve_pin_and_repo``, same owner/org fail-closed identity, same
registration gate. It checks whether an exact quote appears in one shelf
document's text after normalizing whitespace runs and curly/smart quote
characters, and reports the matched offsets and a slice of surrounding
context in that normalized text.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deerflow.projects.documents import add_staged_document, stage_document_bytes
from deerflow.projects.tools import _QUOTE_MAX_CHARS, _QUOTE_MIN_CHARS, _verify_quote_impl, get_project_document_tools
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY

pytestmark = pytest.mark.anyio

_USER = "u1"
_SAMPLE = b'The quick brown fox jumps over the lazy dog. It was a "very" strange day, all told, and no one could explain the noise.'


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """Real SQLite repos + a real per-user projects layout on disk."""
    import deerflow.config.paths as paths_mod
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    projects = ProjectRepository(sf)
    docs = ProjectDocumentRepository(sf)
    project = await projects.create(name="P", user_id=_USER)
    yield SimpleNamespace(paths=paths_mod.get_paths(), projects=projects, docs=docs, project=project)
    await close_engine()


def _runtime(*, project_id: str | None = "p-1", user_id: str = _USER) -> SimpleNamespace:
    context: dict = {"user_id": user_id}
    if project_id is not None:
        context[PROJECT_CONTEXT_KEY] = {"project_id": project_id, "name": "P", "instructions": ""}
    return SimpleNamespace(context=context)


async def _shelve(env, *, name: str, data: bytes, project_id: str | None = None) -> dict:
    staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=project_id or env.project["id"], chunks=[data], max_bytes=1 << 20)
    result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=project_id or env.project["id"], name=name, staged=staged)
    assert result is not None
    row, created = result
    assert created
    return row


class TestVerifyQuote:
    async def test_exact_match_reports_offsets_and_context(self, env):
        row = await _shelve(env, name="notes.txt", data=_SAMPLE)
        runtime = _runtime(project_id=env.project["id"])
        quote = "The quick brown fox jumps over the lazy dog."
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote=quote))
        assert result["found"] is True
        assert result["start_offset"] == 0
        assert result["end_offset"] == len(quote)
        assert quote in result["context"]

    async def test_whitespace_and_curly_quote_normalization_still_matches(self, env):
        row = await _shelve(env, name="notes.txt", data=_SAMPLE)
        runtime = _runtime(project_id=env.project["id"])
        # Curly quotes plus extra/newline whitespace, against a straight-quoted,
        # single-spaced source.
        quote = "It  was\na “very” strange   day"
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote=quote))
        assert result["found"] is True
        assert result["context"]

    async def test_quote_not_in_document_reports_not_found(self, env):
        row = await _shelve(env, name="notes.txt", data=_SAMPLE)
        runtime = _runtime(project_id=env.project["id"])
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote="this text never appears in the document at all"))
        assert result == {"found": False}

    async def test_quote_too_short_is_rejected(self, env):
        row = await _shelve(env, name="notes.txt", data=_SAMPLE)
        runtime = _runtime(project_id=env.project["id"])
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote="short"))
        assert "error" in result
        assert str(_QUOTE_MIN_CHARS) in result["error"]

    async def test_quote_too_long_is_rejected(self, env):
        row = await _shelve(env, name="notes.txt", data=_SAMPLE)
        runtime = _runtime(project_id=env.project["id"])
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote="x" * (_QUOTE_MAX_CHARS + 1)))
        assert "error" in result
        assert str(_QUOTE_MAX_CHARS) in result["error"]

    async def test_quote_length_is_validated_before_touching_the_document(self, env):
        # A nonexistent document id would otherwise fail closed as "not on the
        # shelf"; a length violation is reported first regardless.
        runtime = _runtime(project_id=env.project["id"])
        result = json.loads(await _verify_quote_impl(runtime, document_id="does-not-exist", quote="x"))
        assert "error" in result
        assert str(_QUOTE_MIN_CHARS) in result["error"]

    async def test_document_owned_by_another_user_is_indistinguishable_from_not_found(self, env):
        row = await _shelve(env, name="secret.txt", data=_SAMPLE)
        runtime = _runtime(project_id=env.project["id"], user_id="u2")
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote="The quick brown fox jumps over the lazy dog."))
        assert "error" in result
        assert "no longer on the shelf" in result["error"]

    async def test_document_in_another_organization_is_indistinguishable_from_not_found(self, env):
        from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context

        row = await _shelve(env, name="secret.txt", data=_SAMPLE)
        runtime = _runtime(project_id=env.project["id"])
        token = set_storage_context(WorkspaceStorageContext(actor_user_id=_USER, organization_id="org-elsewhere", storage_user_id=_USER))
        try:
            result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote="The quick brown fox jumps over the lazy dog."))
        finally:
            reset_storage_context(token)
        assert "error" in result
        assert "no longer on the shelf" in result["error"]

    async def test_document_from_another_project_is_fail_closed(self, env):
        other = await env.projects.create(name="Other", user_id=_USER)
        row = await _shelve(env, name="theirs.txt", data=_SAMPLE, project_id=other["id"])
        runtime = _runtime(project_id=env.project["id"])
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote="The quick brown fox jumps over the lazy dog."))
        assert "error" in result
        assert "no longer on the shelf" in result["error"]

    async def test_fail_closed_without_pinned_context(self, env):
        result = json.loads(await _verify_quote_impl(_runtime(project_id=None), document_id="anything", quote="x" * 25))
        assert "error" in result

    async def test_binary_document_is_declined_naming_attach_to_thread(self, env):
        row = await _shelve(env, name="photo.bin", data=b"\x00\x01\x02binary")
        runtime = _runtime(project_id=env.project["id"])
        result = json.loads(await _verify_quote_impl(runtime, document_id=row["id"], quote="z" * 20))
        assert "error" in result
        assert "attach" in result["error"]


class TestVerifyQuoteRegistration:
    def test_included_in_project_document_tools(self):
        names = {tool.name for tool in get_project_document_tools()}
        assert "verify_quote" in names

    def test_absent_without_pinned_project_context(self):
        from deerflow.agents.lead_agent.agent import _append_project_document_tools_if_pinned

        tools: list = []
        _append_project_document_tools_if_pinned(tools, {})
        assert tools == []

    def test_present_with_pinned_project_context(self):
        from deerflow.agents.lead_agent.agent import _append_project_document_tools_if_pinned

        tools: list = []
        _append_project_document_tools_if_pinned(tools, {PROJECT_CONTEXT_KEY: {"project_id": "p-1"}})
        assert {"list_project_documents", "read_project_document", "verify_quote"} <= {tool.name for tool in tools}
