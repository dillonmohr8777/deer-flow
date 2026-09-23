"""M3 lane D: user-owned custom agents, subagent batches, GitHub dispatch.

Covers plans/momentum-m3-isolation-plan.md lane D and the contract in
plans/momentum-enterprise-runtime-contract.md sections 3, 4, 7 (isolation
gate). Four properties:

1. Custom agent CRUD and subagent batch reads return 404, or are excluded
   from lists, across organizations.
2. ``AgentStore.list_all()`` -- the cross-owner scan the GitHub registry
   needs -- is never reachable from an org-scoped route.
3. The deployment-global managed-subagent catalog stays global (no
   ``organization_id``) and admin-only for mutation regardless of which
   organization is active.
4. GitHub dispatch denies fail-closed when the matched agent's owner has no
   active organization delegation, and fires once one is granted.

Every user_id passed to a store is already the workspace storage principal
(``get_effective_user_id()`` / ``get_current_user(request)``), which alone
determines the organization 1:1 (persistence/AGENTS.md's "Key finding"). So a
plain two-different-real-orgs scenario would already have passed before this
lane's change -- it only proves the route/repository *shape* is right. The
new ``organization_id`` filter's own defense-in-depth is proven by pairing
the *correct* explicit ``user_id`` with the *wrong* active organization
context: pre-lane-D this leaked; post-lane-D it is denied independently of
the user filter.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, USER_B, acting_as, org_world  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.channels.message_bus import MessageBus
from app.gateway.github.dispatcher import (
    GITHUB_DELEGATION_SCOPE,
    GITHUB_DELEGATION_SUBJECT_TYPE,
    _github_delegation_subject_id,
    fanout_event,
)
from deerflow.config.agent_storage_config import AgentStorageConfig
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.model import OrganizationRow

GATEWAY_ROOT = Path(__file__).parent.parent / "app" / "gateway"


def _seed_organizations(url: str) -> None:
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[OrganizationRow.__table__, AgentRow.__table__])
    with Session(engine) as session:
        session.add_all(
            [
                OrganizationRow(id=ORG_A, slug="org-a-d-agents", name="Org A", status="active"),
                OrganizationRow(id=ORG_B, slug="org-b-d-agents", name="Org B", status="active"),
            ]
        )
        session.commit()
    engine.dispose()


# ---------------------------------------------------------------------------
# 1a. Custom agents -- SqlAgentStore repository-level isolation
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_store(tmp_path) -> SqlAgentStore:
    url = f"sqlite:///{tmp_path}/agents.db"
    _seed_organizations(url)
    return SqlAgentStore(url)


def test_agent_store_reads_excluded_across_orgs(agent_store: SqlAgentStore) -> None:
    with acting_as(USER_A):
        agent_store.create("reviewer", {"name": "reviewer", "description": "A's agent"}, "A's soul", user_id=USER_A)

    # Owner, in its own organization: visible everywhere.
    with acting_as(USER_A):
        assert agent_store.get("reviewer", user_id=USER_A).description == "A's agent"
        assert agent_store.exists("reviewer", user_id=USER_A) is True
        assert agent_store.get_soul("reviewer", user_id=USER_A) == "A's soul"
        assert [a.name for a in agent_store.list(user_id=USER_A)] == ["reviewer"]

    # A different organization, using its own (non-matching) user_id: already
    # denied by the pre-existing user filter -- the ordinary route shape.
    with acting_as(USER_B):
        with pytest.raises(FileNotFoundError):
            agent_store.get("reviewer", user_id=USER_B)
        assert agent_store.exists("reviewer", user_id=USER_B) is False
        assert agent_store.list(user_id=USER_B) == []
        assert agent_store.delete("reviewer", user_id=USER_B) == "missing"

    # Defense-in-depth: the correct owning user_id, but the active
    # organization context is B's. The new organization filter denies this
    # independently of the (matching) user_id.
    with acting_as(USER_B):
        with pytest.raises(FileNotFoundError):
            agent_store.get("reviewer", user_id=USER_A)
        assert agent_store.exists("reviewer", user_id=USER_A) is False
        assert agent_store.get_soul("reviewer", user_id=USER_A) is None
        assert agent_store.list(user_id=USER_A) == []
        assert agent_store.delete("reviewer", user_id=USER_A) == "missing"

    # Untouched by every denied attempt above.
    with acting_as(USER_A):
        assert agent_store.get("reviewer", user_id=USER_A).description == "A's agent"


def test_agent_store_list_all_ignores_organization_by_design(agent_store: SqlAgentStore) -> None:
    """list_all() is the documented cross-owner scan the GitHub registry needs.

    It must keep returning every owner's agents regardless of the active
    organization context -- narrowing it would break registry discovery.
    Reachability from an org-scoped route is pinned separately below.
    """
    with acting_as(USER_A):
        agent_store.create("alpha", {"name": "alpha"}, "s", user_id=USER_A)
    with acting_as(USER_B):
        agent_store.create("bravo", {"name": "bravo"}, "s", user_id=USER_B)

    with acting_as(USER_A):
        names = sorted(name for _user_id, cfg in agent_store.list_all() for name in [cfg.name])
    assert names == ["alpha", "bravo"]


def test_list_all_not_reachable_from_any_gateway_route() -> None:
    """``AgentStore.list_all`` must only ever be called by the GitHub registry.

    Every file under ``app/gateway`` is scanned for the call; the only
    permitted occurrence is the registry's own cross-owner scan
    (``github/registry.py``), which is reachable solely from the
    HMAC-verified webhook route, never from a session/PAT org-scoped route.
    """
    offenders: list[str] = []
    allowed = {(GATEWAY_ROOT / "github" / "registry.py").resolve()}
    for py_file in sorted(GATEWAY_ROOT.rglob("*.py")):
        if py_file.resolve() in allowed:
            continue
        if ".list_all(" in py_file.read_text(encoding="utf-8"):
            offenders.append(str(py_file.relative_to(GATEWAY_ROOT.parent.parent)))
    assert not offenders, f"list_all() must stay internal-only, called only from github/registry.py: {offenders}"


# ---------------------------------------------------------------------------
# 1b. Custom agents -- the /api/agents router, db backend
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_agents_router_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    _seed_organizations(database.app_sync_sqlalchemy_url)
    set_app_config(
        AppConfig(
            agent_storage=AgentStorageConfig(backend="db"),
            database=database,
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        )
    )
    try:
        yield
    finally:
        load_agents_api_config_from_dict({})
        reset_app_config()


@pytest.mark.asyncio
async def test_agent_router_crud_returns_404_or_excludes_across_orgs(db_agents_router_env) -> None:
    from fastapi import HTTPException

    from app.gateway.routers.agents import (
        AgentCreateRequest,
        AgentUpdateRequest,
        create_agent_endpoint,
        delete_agent,
        get_agent,
        list_agents,
        update_agent,
    )

    with acting_as(USER_A):
        await create_agent_endpoint(AgentCreateRequest(name="reviewer", description="A's agent", soul="A soul"))
        assert (await get_agent("reviewer")).description == "A's agent"
        assert [a.name for a in (await list_agents()).agents] == ["reviewer"]

    with acting_as(USER_B):
        assert (await list_agents()).agents == []

        with pytest.raises(HTTPException) as excinfo:
            await get_agent("reviewer")
        assert excinfo.value.status_code == 404

        with pytest.raises(HTTPException) as excinfo:
            await update_agent("reviewer", AgentUpdateRequest(description="hijacked"))
        assert excinfo.value.status_code == 404

        with pytest.raises(HTTPException) as excinfo:
            await delete_agent("reviewer")
        assert excinfo.value.status_code == 404

    # Untouched by every cross-org attempt above.
    with acting_as(USER_A):
        assert (await get_agent("reviewer")).description == "A's agent"


# ---------------------------------------------------------------------------
# 2. Subagent batches -- repository-level isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_batch_reads_excluded_across_orgs(org_world) -> None:  # noqa: F811
    from deerflow.persistence.subagent_batches.sql import SubagentBatchRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    session_factory = org_world
    repo = SubagentBatchRepository(session_factory)

    async with session_factory() as session, session.begin():
        session.add(ThreadMetaRow(thread_id="thread-a", user_id=USER_A, organization_id=ORG_A))

    created = await repo.create_batch(
        batch_id="batch-a",
        user_id=USER_A,
        thread_id="thread-a",
        run_id=None,
        tool_call_id=None,
        submission_key="submit-a",
        title="Batch A",
        subagent_type="general-purpose",
        items=[{"key": "item-1", "prompt": "do the thing"}],
        max_live_items=1,
        max_running_items=1,
        max_attempts=1,
        execution_spec={},
    )
    batch_id = created["id"]

    # Owner, in its own organization: visible.
    with acting_as(USER_A):
        assert await repo.get_batch(batch_id, user_id=USER_A) is not None
        assert [b["id"] for b in await repo.list_by_thread("thread-a", user_id=USER_A)] == [batch_id]
        assert await repo.list_items(batch_id, user_id=USER_A) is not None

    # A different organization, its own user_id: already denied pre-existing.
    with acting_as(USER_B):
        assert await repo.get_batch(batch_id, user_id=USER_B) is None
        assert await repo.list_by_thread("thread-a", user_id=USER_B) == []
        assert await repo.list_items(batch_id, user_id=USER_B) is None

    # Defense-in-depth: correct owning user_id, wrong active organization.
    with acting_as(USER_B):
        assert await repo.get_batch(batch_id, user_id=USER_A) is None
        assert [b["id"] for b in await repo.list_by_thread("thread-a", user_id=USER_A)] == []
        assert await repo.list_items(batch_id, user_id=USER_A) is None

    # Untouched: still visible to the real owner in its own organization.
    with acting_as(USER_A):
        assert await repo.get_batch(batch_id, user_id=USER_A) is not None


# ---------------------------------------------------------------------------
# 3. Managed subagents (deployment-global catalog) stay global, admin-only
# ---------------------------------------------------------------------------


def test_managed_subagent_row_has_no_organization_column() -> None:
    from deerflow.persistence.managed_subagents.model import ManagedSubagentRow

    assert "organization_id" not in ManagedSubagentRow.__table__.columns.keys()


@pytest.mark.asyncio
async def test_managed_subagents_stay_global_and_admin_only_across_orgs(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.gateway.routers import subagents as subagents_router
    from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    set_app_config(AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")))
    store = FileManagedSubagentStore()
    monkeypatch.setattr(subagents_router, "get_managed_subagent_store", lambda *_: store)

    def _request(role: str):
        return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role=role)))

    try:
        # Created while org A is active, by an admin.
        with acting_as(USER_A):
            await subagents_router.create_managed_subagent(
                _request("admin"),
                subagents_router.ManagedSubagentCreateRequest(
                    name="planner",
                    description="Plans work",
                    system_prompt="You plan.",
                ),
            )

        # Global: still visible while org B is active -- not org-scoped.
        with acting_as(USER_B):
            catalog = await subagents_router.list_subagents(_request("user"))
        assert "planner" in {item.name for item in catalog.subagents if item.source == "managed"}

        # Admin-only mutation holds regardless of which organization is active.
        from fastapi import HTTPException

        with acting_as(USER_B):
            with pytest.raises(HTTPException) as excinfo:
                await subagents_router.update_managed_subagent(
                    "planner",
                    _request("user"),
                    subagents_router.ManagedSubagentUpdateRequest(enabled=False),
                )
            assert excinfo.value.status_code == 403

        # An admin in a *different* organization can still administer the
        # global catalog -- it is deployment-global, not per-organization.
        with acting_as(USER_B):
            updated = await subagents_router.update_managed_subagent(
                "planner",
                _request("admin"),
                subagents_router.ManagedSubagentUpdateRequest(enabled=False),
            )
        assert updated.enabled is False
    finally:
        reset_app_config()


# ---------------------------------------------------------------------------
# 4. GitHub dispatch -- fail-closed without an organization delegation
# ---------------------------------------------------------------------------


def _write_github_bound_agent(base: Path, user_id: str, name: str, repo: str) -> None:
    agent_dir = base / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "name": name,
                "github": {"bindings": [{"repo": repo, "triggers": {"pull_request": {"actions": ["opened"]}}}]},
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def github_agent_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    from app.gateway.github.registry import _invalidate_cache

    _invalidate_cache()
    return tmp_path


def _pull_request_opened_payload(repo: str) -> dict:
    return {
        "action": "opened",
        "pull_request": {"number": 7, "title": "Add feature", "user": {"login": "someone"}, "body": "change"},
        "repository": {"full_name": repo},
        "sender": {"login": "someone"},
    }


@pytest.mark.asyncio
async def test_github_dispatch_skips_fail_closed_without_delegation(org_world, github_agent_env: Path) -> None:  # noqa: F811
    _write_github_bound_agent(github_agent_env, USER_A, "reviewer", "acme/widgets")
    bus = MessageBus()

    result = await fanout_event(bus, "pull_request", "delivery-1", _pull_request_opened_payload("acme/widgets"))

    assert result["matched_agents"] == ["reviewer"]
    assert result["fired_agents"] == []
    assert {"agent": "reviewer", "reason": "no_active_delegation"} in result["skipped"]
    assert bus.inbound_queue.empty()


@pytest.mark.asyncio
async def test_github_dispatch_fires_once_delegation_is_granted(org_world, github_agent_env: Path) -> None:  # noqa: F811
    _write_github_bound_agent(github_agent_env, USER_A, "reviewer", "acme/widgets")

    await OrganizationDelegationRepository(org_world).grant(
        organization_id=ORG_A,
        subject_type=GITHUB_DELEGATION_SUBJECT_TYPE,
        subject_id=_github_delegation_subject_id(USER_A, "reviewer"),
        owner_user_id=USER_A,
        scopes=[GITHUB_DELEGATION_SCOPE],
    )

    bus = MessageBus()
    result = await fanout_event(bus, "pull_request", "delivery-2", _pull_request_opened_payload("acme/widgets"))

    assert result["fired_agents"] == ["reviewer"]
    assert result["skipped"] == []
    msg = await bus.get_inbound()
    assert msg.owner_user_id == USER_A


@pytest.mark.asyncio
async def test_github_dispatch_revoked_delegation_skips_again(org_world, github_agent_env: Path) -> None:  # noqa: F811
    _write_github_bound_agent(github_agent_env, USER_A, "reviewer", "acme/widgets")
    repository = OrganizationDelegationRepository(org_world)
    await repository.grant(
        organization_id=ORG_A,
        subject_type=GITHUB_DELEGATION_SUBJECT_TYPE,
        subject_id=_github_delegation_subject_id(USER_A, "reviewer"),
        owner_user_id=USER_A,
        scopes=[GITHUB_DELEGATION_SCOPE],
    )
    await repository.revoke(subject_type=GITHUB_DELEGATION_SUBJECT_TYPE, subject_id=_github_delegation_subject_id(USER_A, "reviewer"))

    bus = MessageBus()
    result = await fanout_event(bus, "pull_request", "delivery-3", _pull_request_opened_payload("acme/widgets"))

    assert result["fired_agents"] == []
    assert {"agent": "reviewer", "reason": "no_active_delegation"} in result["skipped"]
