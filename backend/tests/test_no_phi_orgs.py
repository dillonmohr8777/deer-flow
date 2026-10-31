"""Health-sector (no-PHI) workspaces: the guard, the upload block, the admin switch.

The flag is admin-owned. A flagged workspace gets the marketing-only guard in
every agent run, refuses file uploads, and tells the portal to show a banner.
"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from _router_auth_helpers import call_unwrapped
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from test_momobot_max_assembly import _app_config, _assemble

from app.gateway import no_phi
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import admin as admin_router
from app.gateway.routers import uploads, workspaces
from deerflow.agents.lead_agent.prompt import NO_PHI_GUARD, _build_no_phi_section
from deerflow.config.app_config import NoPhiConfig
from deerflow.persistence.audit_events import AuditEventRepository, AuditEventRow
from deerflow.persistence.base import Base
from deerflow.persistence.clients.model import ClientRow
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    for module in (no_phi, admin_router, workspaces):
        monkeypatch.setattr(module, "get_session_factory", lambda factory=factory: factory)
    async with factory() as session:
        session.add_all(
            [
                OrganizationRow(id="org-health", slug="health-co", name="Health Co", status="active", customer_client_id=None),
                OrganizationRow(id="org-plain", slug="plain-co", name="Plain Co", status="active", customer_client_id=None),
                OrganizationRow(id="org-bound", slug="bound-co", name="Bound Co", status="active", customer_client_id="client-health"),
                OrganizationRow(id="org-seed", slug="Seeded-Co", name="Seeded Co", status="active", customer_client_id=None),
                ClientRow(id="client-health", organization_id="agency", display_name="Acme Dental", no_phi=True),
                ClientRow(id="client-plain", organization_id="agency", display_name="Plain Client"),
                ProjectRow(id="proj-health", user_id="staff-1", name="Health project", client_id="client-health"),
                ProjectRow(id="proj-plain", user_id="staff-1", name="Plain project", client_id="client-plain"),
                ProjectRow(id="proj-none", user_id="staff-1", name="Unlinked project"),
                ProjectRow(id="proj-ghost", user_id="staff-1", name="Dangling client link", client_id="client-ghost"),
                ThreadMetaRow(thread_id="thread-health", user_id="staff-1", project_id="proj-health"),
                ThreadMetaRow(thread_id="thread-plain", user_id="staff-1", project_id="proj-plain"),
                ThreadMetaRow(thread_id="thread-none", user_id="staff-1"),
            ]
        )
        health = await session.get(OrganizationRow, "org-health")
        health.no_phi = True
        await session.commit()
    yield factory
    await engine.dispose()


# -- the guard in the prompt -------------------------------------------------


async def test_the_guard_is_in_the_prompt_only_when_the_flag_is_true():
    assert NO_PHI_GUARD in _build_no_phi_section(True)
    for flag in (None, False, "true", 1):
        assert _build_no_phi_section(flag) == ""
    for rule in ("marketing work only", "Never request, collect, store", "Do not handle leads", "replies to individual patient reviews", "stop", "outrank"):
        assert rule in NO_PHI_GUARD


async def test_a_flagged_run_assembles_with_the_guard(monkeypatch, tmp_path):
    _, captured = await _assemble(monkeypatch, tmp_path, role="client", app=_app_config(), keys=("c-max",), context={"no_phi": True})

    assert "<no_phi_guard>" in captured["system_prompt"] and "patient" in captured["system_prompt"]


async def test_an_unflagged_run_assembles_without_the_guard(monkeypatch, tmp_path):
    _, captured = await _assemble(monkeypatch, tmp_path, role="client", app=_app_config(), keys=("c-max",))

    assert "<no_phi_guard>" not in captured["system_prompt"]


@pytest.mark.parametrize("mode", ["tool", "inject"])
async def test_a_flagged_run_has_no_memory_middleware_or_tools(monkeypatch, tmp_path, mode):
    from deerflow.agents.lead_agent import agent
    from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

    bound = []
    monkeypatch.setattr(agent, "_append_memory_tools_without_name_conflicts", lambda tools: bound.append(True))

    async def memory_surface(context):
        bound.clear()
        _, captured = await _assemble(monkeypatch, tmp_path, role="client", app=app, keys=("c-max",), context=context)
        return any(isinstance(m, MemoryMiddleware) for m in captured["middleware"]), bool(bound)

    app = _app_config()
    app.memory.enabled, app.memory.mode = True, mode
    assert await memory_surface(None) != (False, False)  # control: an unflagged run does expose memory
    assert await memory_surface({"no_phi": True}) == (False, False)


# -- which workspaces are flagged --------------------------------------------


async def test_a_workspace_is_flagged_by_its_row_its_bound_client_or_the_operator_config(session_factory):
    seeded = SimpleNamespace(no_phi=NoPhiConfig(organization_slugs=[" seeded-CO "]))

    assert await no_phi.organization_is_no_phi("org-health") is True
    assert await no_phi.organization_is_no_phi("org-bound") is True  # via the client it is bound to
    assert await no_phi.organization_is_no_phi("org-seed", seeded) is True  # via config, case and spaces ignored
    assert await no_phi.organization_is_no_phi("org-seed") is False
    assert await no_phi.organization_is_no_phi("org-plain", seeded) is False
    assert await no_phi.organization_is_no_phi(None) is False  # no workspace named: dev, tests, internal callers


async def test_an_unreadable_workspace_fails_closed(session_factory, monkeypatch):
    seeded = SimpleNamespace(no_phi=NoPhiConfig(organization_slugs=["seeded-co"]))

    assert await no_phi.organization_is_no_phi("missing") is True  # named, but no row
    assert await no_phi.organization_is_no_phi("missing", seeded) is True
    monkeypatch.setattr(no_phi, "get_session_factory", lambda: None)
    assert await no_phi.organization_is_no_phi("org-plain", seeded) is True  # slug list configured, slug unreadable
    assert await no_phi.organization_is_no_phi("org-plain") is False  # no database, empty list: nothing to read
    assert await no_phi.organization_is_no_phi(None, seeded) is False  # plain no-org dev/test path still works
    assert await no_phi.organization_is_no_phi(None, seeded, thread_id="thread-health") is False  # no database: nothing to look up


async def test_a_project_or_thread_of_a_flagged_client_is_flagged_in_any_workspace(session_factory):
    # org-plain stands in for the agency workspace staff work in: it is not flagged itself.
    assert await no_phi.organization_is_no_phi("org-plain") is False
    assert await no_phi.organization_is_no_phi("org-plain", project_id="proj-health") is True
    assert await no_phi.organization_is_no_phi("org-plain", thread_id="thread-health") is True
    assert await no_phi.organization_is_no_phi(None, thread_id="thread-health") is True  # even with no workspace named
    for clean in ({"project_id": "proj-plain"}, {"project_id": "proj-none"}, {"thread_id": "thread-plain"}, {"thread_id": "thread-none"}, {"thread_id": "thread-new"}, {"project_id": "proj-unknown"}):
        assert await no_phi.organization_is_no_phi("org-plain", **clean) is False, clean
    assert await no_phi.organization_is_no_phi("org-plain", project_id="proj-ghost") is True  # linked client cannot be read: fail closed


async def test_the_run_policy_stamps_flagged_workspaces_only_and_drops_a_forged_flag(session_factory):
    flagged = {"context": {}, "configurable": {}}
    await no_phi.apply_no_phi_policy(flagged, request=SimpleNamespace(state=SimpleNamespace(organization_id="org-health")))
    assert flagged["context"]["no_phi"] is True and flagged["configurable"]["no_phi"] is True

    forged = {"context": {"no_phi": True}, "configurable": {"no_phi": True}}
    await no_phi.apply_no_phi_policy(forged, request=SimpleNamespace(state=SimpleNamespace(organization_id="org-plain")))
    assert "no_phi" not in forged["context"] and "no_phi" not in forged["configurable"]

    staff = {"context": {}, "configurable": {"thread_id": "thread-health"}}
    await no_phi.apply_no_phi_policy(staff, request=SimpleNamespace(state=SimpleNamespace(organization_id="org-plain")))
    assert staff["context"]["no_phi"] is True and staff["configurable"]["no_phi"] is True  # agency staff on a flagged client's thread

    internal = {"context": {"no_phi": True}}
    await no_phi.apply_no_phi_policy(internal, request=SimpleNamespace(state=SimpleNamespace()))
    assert "no_phi" not in internal["context"]


async def test_a_client_cannot_send_the_flag_in_a_run_request():
    from app.gateway.services import strip_internal_context_keys

    config = {"context": {"no_phi": False, "model_name": "x"}, "configurable": {"no_phi": False}}
    strip_internal_context_keys(config)

    assert config == {"context": {"model_name": "x"}, "configurable": {}}


# -- uploads ----------------------------------------------------------------


async def _upload(org_id: str | None, tmp_path, thread_id: str = "thread-1"):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    file = UploadFile(filename="notes.txt", file=BytesIO(b"hello"))
    with (
        patch.object(no_phi, "resolve_organization_id", return_value=org_id),
        patch.object(uploads, "_reserve_upload_thread", AsyncMock()),
        patch.object(uploads, "get_uploads_dir", return_value=uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "reserve_upload_write", _noop_upload_write),
    ):
        return await call_unwrapped(uploads.upload_files, thread_id, request=MagicMock(), files=[file], config=SimpleNamespace(no_phi=NoPhiConfig())), uploads_dir


class _noop_upload_write:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return None

    async def __aexit__(self, *_exc):
        return False


async def test_uploads_are_refused_in_a_flagged_workspace_with_a_clear_message(session_factory, tmp_path):
    with pytest.raises(HTTPException) as refused:
        await _upload("org-health", tmp_path)

    assert refused.value.status_code == 403
    assert "patient or health information" in refused.value.detail
    assert list((tmp_path / "uploads").iterdir()) == []


async def test_uploads_are_refused_to_a_flagged_clients_thread_from_an_unflagged_workspace(session_factory, tmp_path):
    with pytest.raises(HTTPException) as refused:
        await _upload("org-plain", tmp_path, thread_id="thread-health")

    assert refused.value.status_code == 403
    assert list((tmp_path / "uploads").iterdir()) == []


async def test_uploads_still_work_in_an_unflagged_workspace(session_factory, tmp_path):
    result, uploads_dir = await _upload("org-plain", tmp_path)

    assert result.success is True
    assert (uploads_dir / "notes.txt").read_bytes() == b"hello"


async def test_the_project_shelf_routes_refuse_uploads_in_a_flagged_workspace(session_factory):
    from app.gateway.routers import project_documents

    guards = {route.path: [d.dependency for d in route.dependencies] for route in project_documents.router.routes if "POST" in route.methods}
    base = "/api/projects/{project_id}/documents"
    for path in (base, f"{base}/from-thread", f"{base}/{{document_id}}/attach-to-thread/{{thread_id}}"):
        assert no_phi.uploads_allowed in guards[path], path
    config = SimpleNamespace(no_phi=NoPhiConfig())
    with patch.object(no_phi, "resolve_organization_id", return_value="org-health"), pytest.raises(HTTPException) as refused:
        await no_phi.uploads_allowed(SimpleNamespace(path_params={}), config)
    assert refused.value.status_code == 403
    with patch.object(no_phi, "resolve_organization_id", return_value="org-plain"):
        await no_phi.uploads_allowed(SimpleNamespace(path_params={"project_id": "proj-plain"}), config)
        with pytest.raises(HTTPException) as refused:  # an agency workspace, a flagged client's project
            await no_phi.uploads_allowed(SimpleNamespace(path_params={"project_id": "proj-health"}), config)
    assert refused.value.status_code == 403


# -- admin switch -----------------------------------------------------------


@pytest_asyncio.fixture()
async def audit_repo(session_factory):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[AuditEventRow.__table__]))
    yield AuditEventRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def _request(role: str, audit_repo=None):
    return SimpleNamespace(
        state=SimpleNamespace(user=SimpleNamespace(id="admin-1", system_role=role), auth_source=AUTH_SOURCE_SESSION),
        app=SimpleNamespace(state=SimpleNamespace(audit_repo=audit_repo)),
        client=None,
        headers={},
    )


@pytest.mark.parametrize("role", ["client", "user", "exec"])
async def test_only_a_system_admin_can_change_the_flag(session_factory, role):
    body = admin_router.SetNoPhiRequest(no_phi=False)
    for call in (
        admin_router.set_organization_no_phi("org-health", body, _request(role)),
        admin_router.get_organization_no_phi("org-health", _request(role)),
        admin_router.set_client_no_phi("client-health", body, _request(role)),
    ):
        with pytest.raises(HTTPException) as refused:
            await call
        assert refused.value.status_code == 403
    async with session_factory() as session:
        assert (await session.get(OrganizationRow, "org-health")).no_phi is True


async def test_an_admin_sets_and_clears_the_flag_and_it_is_audited(session_factory, audit_repo):
    request = _request("admin", audit_repo)
    on = await admin_router.set_organization_no_phi("org-plain", admin_router.SetNoPhiRequest(no_phi=True), request)
    assert (on.no_phi, on.effective) == (True, True)
    assert await no_phi.organization_is_no_phi("org-plain") is True

    off = await admin_router.set_organization_no_phi("org-plain", admin_router.SetNoPhiRequest(no_phi=False), request)
    assert (off.no_phi, off.effective) == (False, False)
    events, _ = await audit_repo.list(organization_id=None, action_prefix="admin.organization.no_phi")
    assert sorted((e["details"]["from"], e["details"]["to"]) for e in events) == [(False, True), (True, False)]


async def test_an_admin_cannot_clear_a_workspace_the_operator_config_lists(session_factory, monkeypatch):
    monkeypatch.setattr(admin_router, "operator_config", lambda: SimpleNamespace(no_phi=NoPhiConfig(organization_slugs=["seeded-co"])))

    cleared = await admin_router.set_organization_no_phi("org-seed", admin_router.SetNoPhiRequest(no_phi=False), _request("admin"))

    assert (cleared.no_phi, cleared.configured, cleared.effective) == (False, True, True)


async def test_flagging_a_client_flags_the_workspaces_bound_to_it(session_factory):
    await admin_router.set_client_no_phi("client-health", admin_router.SetNoPhiRequest(no_phi=False), _request("admin"))
    assert await no_phi.organization_is_no_phi("org-bound") is False
    done = await admin_router.set_client_no_phi("client-health", admin_router.SetNoPhiRequest(no_phi=True), _request("admin"))
    assert done.no_phi is True and await no_phi.organization_is_no_phi("org-bound") is True


async def test_unknown_targets_are_404(session_factory):
    with pytest.raises(HTTPException) as missing:
        await admin_router.set_organization_no_phi("nope", admin_router.SetNoPhiRequest(no_phi=True), _request("admin"))
    assert missing.value.status_code == 404


# -- the portal banner flag -------------------------------------------------


async def test_the_workspace_list_tells_the_portal_when_to_show_the_banner(session_factory):
    actor = SimpleNamespace(id="user-1")
    async with session_factory() as session:
        private = private_organization_id("user-1")
        session.add(OrganizationRow(id=private, slug="private-user-1", name="Private organization", status="active", storage_user_id=None))
        session.add(OrganizationMemberRow(organization_id=private, user_id="user-1", role="owner", status="active"))
        await session.commit()

    def request(org_id):
        return SimpleNamespace(state=SimpleNamespace(user=actor, auth_source=AUTH_SOURCE_SESSION, organization_id=org_id), cookies={})

    assert (await workspaces.list_workspaces(request("org-health"))).active_no_phi is True
    assert (await workspaces.list_workspaces(request("org-plain"))).active_no_phi is False
    assert (await workspaces.list_workspaces(request(private))).active_no_phi is False


# -- channel attachments ----------------------------------------------------


@pytest.fixture()
def channel_delegation(monkeypatch):
    """Resolve the channel connection's delegation to a chosen workspace."""

    def pick(organization_id: str | None):
        async def resolve(_self, delegation_id, **_kwargs):
            return None if organization_id is None else SimpleNamespace(id=delegation_id, organization=SimpleNamespace(id=organization_id))

        monkeypatch.setattr("deerflow.persistence.organizations.delegation.OrganizationDelegationRepository.resolve_delegation_by_id", resolve)

    return pick


def _slack_message(**overrides):
    from app.channels.message_bus import InboundMessage

    fields = {"channel_name": "slack", "chat_id": "chat-1", "user_id": "u-1", "text": "", "delegation_id": "delegation-1", "files": [{"type": "file", "filename": "labs.pdf", "_content": b"pdf bytes"}]}
    return InboundMessage(**{**fields, **overrides})


@pytest.mark.parametrize(
    ("organization_id", "thread_id"),
    [("org-health", "thread-none"), ("org-plain", "thread-health"), (None, "thread-none")],
    ids=["flagged workspace", "flagged client's thread in an unflagged workspace", "delegation no longer resolves"],
)
async def test_channel_attachments_are_dropped_not_stored_in_a_flagged_workspace(session_factory, channel_delegation, tmp_path, organization_id, thread_id):
    from app.channels import manager

    channel_delegation(organization_id)
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    msg = _slack_message()

    with patch("deerflow.uploads.manager.ensure_uploads_dir", return_value=uploads_dir):
        assert await manager._ingest_inbound_files(thread_id, msg) == []

    assert msg.files == []
    assert list(uploads_dir.iterdir()) == []


async def test_channel_attachments_are_still_stored_in_an_unflagged_workspace(session_factory, channel_delegation, tmp_path):
    from app.channels import manager

    channel_delegation("org-plain")
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    msg = _slack_message()

    with patch("deerflow.uploads.manager.ensure_uploads_dir", return_value=uploads_dir):
        stored = await manager._ingest_inbound_files("thread-plain", msg)

    assert [entry["filename"] for entry in stored] == ["labs.pdf"]
    assert (uploads_dir / "labs.pdf").read_bytes() == b"pdf bytes"


@pytest.mark.parametrize("text", ["", "see attached"])
async def test_a_flagged_channel_message_is_refused_before_the_channel_downloads_anything(session_factory, channel_delegation, tmp_path, text):
    from app.channels.manager import NO_PHI_FILES_REFUSAL, ChannelManager
    from app.channels.message_bus import MessageBus
    from app.channels.store import ChannelStore

    channel_delegation("org-health")
    bus = MessageBus()
    published = []

    async def capture(outbound):
        published.append(outbound)

    bus.subscribe_outbound(capture)
    manager = ChannelManager(bus=bus, store=ChannelStore(path=tmp_path / "store.json"))
    channel = MagicMock(supports_streaming=False, receive_file=AsyncMock())
    client = MagicMock()
    client.runs.wait = AsyncMock(return_value={"messages": [{"type": "ai", "content": "ok"}]})
    msg = _slack_message(text=text)

    with (
        patch("app.channels.service.get_channel_service", return_value=MagicMock(get_channel=MagicMock(return_value=channel))),
        patch("app.channels.manager._ingest_inbound_files", AsyncMock(return_value=[])) as ingest,
    ):
        await manager._handle_chat_on_thread(client, msg, "thread-none")

    channel.receive_file.assert_not_awaited()  # Feishu and DingTalk write attachments inside receive_file
    assert msg.files == []
    assert published and published[0].text == NO_PHI_FILES_REFUSAL
    assert (client.runs.wait.await_count, ingest.await_count) == ((0, 0) if not text else (1, 1))
    assert published[0].is_final is (not text)
