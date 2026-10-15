"""Client memory: reviewer edits are recorded per client and shown to that client's drafting agent."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from org_isolation_fixtures import USER_A, USER_B, auth_headers, org_world  # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import approvals
from deerflow.agents.middlewares.client_corrections_middleware import ClientCorrectionsMiddleware
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.approvals.corrections import ClientCorrectionRepository, render_corrections, summarize_edit
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.persistence.fleet.model import FleetAgentBindingRow

SLACK = {"action_type": "slack_message", "title": "Update", "target": "C123", "payload": {"text": "Hey team, spend is up a lot."}}


@pytest.fixture(autouse=True)
def _slack(monkeypatch):
    sent = []

    class Chan:
        _web_client = object()

        async def send(self, msg):
            sent.append(msg)

    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: SimpleNamespace(get_channel=lambda name: Chan()))
    return sent


def _app(sf) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.pending_action_repo = PendingActionRepository(sf)
    app.state.audit_repo = AuditEventRepository(sf)
    app.include_router(approvals.router)
    return app


async def _approve(sf, *, agent="agent-one", edit: dict | None = None, user=USER_A, **kw):
    row = await PendingActionRepository(sf).create(**{**SLACK, "agent_name": agent, **kw}, user_id=user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(sf)), base_url="http://test") as client:
        h = auth_headers(user)
        if edit is not None:
            assert (await client.patch(f"/api/approvals/{row['id']}", json={"payload": edit}, headers=h)).status_code == 200
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).status_code == 200
    return row


async def _bind(sf, client_id, agent, owner=USER_A):
    now = datetime.now(UTC)
    async with sf() as s, s.begin():
        s.add(FleetAgentBindingRow(id=f"b-{agent}", organization_id=None, client_id=client_id, template_id=f"t-{agent}", template_version="1", agent_name=agent, agent_owner_user_id=owner, created_at=now, updated_at=now))


def test_summary_counts_words_per_changed_field():
    assert summarize_edit({"text": "a b c"}, {"text": "a b c d e"}) == "text: +2/-0 words"
    assert summarize_edit({"text": "same"}, {"text": "same"}) == "no field changes"


@pytest.mark.asyncio
async def test_edited_approval_is_recorded_with_all_fields(org_world):  # noqa: F811
    row = await _approve(org_world, edit={"text": "Hey team, spend is up 12%."})
    (c,) = await ClientCorrectionRepository(org_world).recent(USER_A, "agent:agent-one")
    assert c["approval_id"] == row["id"] and c["action_type"] == "slack_message" and c["approver"] == USER_A
    assert c["original"] == {"text": "Hey team, spend is up a lot."} and c["edited"] == {"text": "Hey team, spend is up 12%."}
    assert "text:" in c["summary"] and c["created_at"] is not None


@pytest.mark.asyncio
async def test_unedited_approval_and_agentless_approval_record_nothing(org_world):  # noqa: F811
    await _approve(org_world)
    await _approve(org_world, agent=None, edit={"text": "changed"})
    repo = ClientCorrectionRepository(org_world)
    assert await repo.recent(USER_A, "agent:agent-one") == []


@pytest.mark.asyncio
async def test_agents_bound_to_one_client_share_a_ledger_and_clients_stay_apart(org_world):  # noqa: F811
    await _bind(org_world, "acme", "acme-social")
    await _bind(org_world, "acme", "acme-email")
    await _bind(org_world, "globex", "globex-social")
    await _approve(org_world, agent="acme-social", edit={"text": "one"})
    await _approve(org_world, agent="acme-email", edit={"text": "two"})
    await _approve(org_world, agent="globex-social", edit={"text": "three"})
    repo = ClientCorrectionRepository(org_world)
    assert [c["edited"]["text"] for c in await repo.recent(USER_A, "client:acme")] == ["two", "one"]
    assert [c["edited"]["text"] for c in await repo.recent(USER_A, "client:globex")] == ["three"]
    assert await repo.recent(USER_B, "client:acme") == []


@pytest.mark.asyncio
async def test_recent_is_capped_newest_first_and_rendered_oldest_first(org_world):  # noqa: F811
    for i in range(12):
        await _approve(org_world, edit={"text": f"v{i}"})
    rows = await ClientCorrectionRepository(org_world).recent(USER_A, "agent:agent-one", 10)
    assert [r["edited"]["text"] for r in rows][0] == "v11" and len(rows) == 10
    block = render_corrections(rows)
    assert block.index("v2") < block.index("v11") and "v1'" not in block and block.startswith("<client_corrections>")
    assert render_corrections([]) == ""


@pytest.mark.asyncio
async def test_a_recording_failure_never_blocks_the_approval(org_world, monkeypatch):  # noqa: F811
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(ClientCorrectionRepository, "record_for_approval", boom)
    await _approve(org_world, edit={"text": "changed"})  # asserts 200


class _Req:
    def __init__(self, messages, runtime):
        self.messages, self.runtime = messages, runtime

    def override(self, **kw):
        return _Req(kw.get("messages", self.messages), self.runtime)


async def _model_sees(mw, messages):
    seen = {}

    async def handler(req):
        seen["messages"] = req.messages
        return "ok"

    await mw.awrap_model_call(_Req(messages, SimpleNamespace(context={"user_id": USER_A})), handler)
    return seen["messages"]


@pytest.mark.asyncio
async def test_drafting_agent_sees_its_clients_corrections_once_before_the_user_message(org_world):  # noqa: F811
    await _bind(org_world, "acme", "acme-social")
    await _approve(org_world, agent="acme-social", edit={"text": "Spend is up 12%."})
    mw = ClientCorrectionsMiddleware("acme-social")
    history = [HumanMessage(content="earlier"), AIMessage(content="reply"), HumanMessage(content="draft the update")]
    seen = await _model_sees(mw, history)
    assert [type(m).__name__ for m in seen] == ["HumanMessage", "AIMessage", "HumanMessage", "HumanMessage"]
    assert "<client_corrections>" in seen[2].content and "Spend is up 12%." in seen[2].content and seen[3].content == "draft the update"
    again = await _model_sees(mw, seen)  # re-assembling a decorated request must not stack blocks
    assert sum("<client_corrections>" in str(m.content) for m in again) == 1
    assert history[2].content == "draft the update" and len(history) == 3  # state is never mutated


@pytest.mark.asyncio
async def test_other_agents_and_empty_ledgers_get_no_block(org_world):  # noqa: F811
    await _approve(org_world, edit={"text": "changed"})
    history = [HumanMessage(content="hi")]
    assert await _model_sees(ClientCorrectionsMiddleware("someone-else"), history) == history
    assert await _model_sees(ClientCorrectionsMiddleware(None), history) == history


@pytest.mark.asyncio
async def test_migration_0051_chains_after_0050_with_one_head(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    cfg = _get_alembic_config(engine)
    try:
        assert ScriptDirectory.from_config(cfg).get_heads() == ["0051_client_corrections"]
        await asyncio.to_thread(command.upgrade, cfg, "head")
        await asyncio.to_thread(command.downgrade, cfg, "0050_pending_action_fact_check")
        await asyncio.to_thread(command.upgrade, cfg, "head")
    finally:
        await engine.dispose()
