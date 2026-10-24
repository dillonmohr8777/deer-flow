"""First-login onboarding: forced steps, own-profile pre-fill, completion once."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.people_profiles import load_own_profile, parse_profile
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, McpUserScopedAuthConfig
from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.user.preferences import UserPreferencesRepository

PATH = "/api/v1/auth/onboarding"
ALICE_PROFILE = "---\nrole: Account manager\nteam: Paid media\nclients: Example Co, Sample LLC\ntools: slack, gmail, google_ads, fax\n---\nLikes short morning updates.\n"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def people_dir(tmp_path, monkeypatch):
    folder = tmp_path / "people"
    folder.mkdir()
    (folder / "alice@example.com.md").write_text(ALICE_PROFILE, encoding="utf-8")
    (folder / "bob@example.com.md").write_text("---\nrole: Designer\nteam: Creative\n---\n", encoding="utf-8")
    monkeypatch.setenv("MOMO_PEOPLE_DIR", str(folder))
    return folder


@pytest.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/prefs.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all([UserRow(id="alice", email="alice@example.com"), UserRow(id="bob", email="bob@example.com"), UserRow(id="carol", email="carol@example.com", system_role="client")])
        await session.commit()
    yield UserPreferencesRepository(sessions)
    await engine.dispose()


@pytest.fixture
async def api(repo, people_dir, monkeypatch):
    from app.gateway.routers import onboarding

    users = {
        "alice": SimpleNamespace(id="alice", email="alice@example.com", system_role="user"),
        "bob": SimpleNamespace(id="bob", email="bob@example.com", system_role="exec"),
        "carol": SimpleNamespace(id="carol", email="carol@example.com", system_role="client"),
        "admin": SimpleNamespace(id="admin", email="admin@example.com", system_role="admin"),
    }
    identity = SimpleNamespace(id="alice")
    app = FastAPI()
    app.include_router(onboarding.router)

    @app.middleware("http")
    async def session(request, call_next):
        request.state.user = users[identity.id]
        request.state.auth_source = "session"
        return await call_next(request)

    facts: list[tuple[str, str]] = []

    class Memory:
        def create_fact(self, content, category, confidence, user_id):
            facts.append((user_id, content))
            return {}, "fact-id"

    monkeypatch.setattr(onboarding, "_repository", lambda: repo)
    monkeypatch.setattr(onboarding, "_momo_memory_enabled", lambda: False)
    monkeypatch.setattr(onboarding, "get_effective_user_id", lambda: identity.id)
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: Memory())
    monkeypatch.setattr("app.gateway.deps.is_admin_user", lambda request: _async(users[identity.id].system_role == "admin"))
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: ExtensionsConfig(mcp_servers={}, skills={}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.headers["X-Expected-User-Id"] = "alice"
        yield client, identity, facts


async def _async(value):
    return value


def _as(client, identity, user_id):
    identity.id = user_id
    client.headers["X-Expected-User-Id"] = user_id


@pytest.mark.anyio
async def test_profile_prefills_only_the_signed_in_persons_own_step(api):
    client, identity, _ = api
    state = (await client.get(PATH)).json()
    assert state["required"] is True
    assert (state["role"], state["team"], state["profile_found"]) == ("Account manager", "Paid media", True)
    assert state["clients"] == ["Example Co", "Sample LLC"]
    # Unknown tool names in a profile are dropped, known ones pre-select step 2.
    assert state["tools"] == ["slack", "gmail", "google_ads"]
    _as(client, identity, "bob")
    bob = (await client.get(PATH)).json()
    assert (bob["role"], bob["clients"]) == ("Designer", [])
    # There is no way to ask for another person's profile.
    assert (await client.get(PATH, params={"email": "alice@example.com"})).json()["role"] == "Designer"


@pytest.mark.anyio
async def test_steps_are_ordered_and_completion_needs_steps_one_and_two(api):
    client, _, facts = api
    assert (await client.post(f"{PATH}/complete")).status_code == 409
    assert (await client.put(f"{PATH}/tools", json={"tools": ["slack"]})).status_code == 409
    assert (await client.put(f"{PATH}/profile", json={"role": " ", "team": "x"})).status_code == 422
    assert (await client.put(f"{PATH}/profile", json={"role": "AM", "team": "Paid"})).status_code == 200
    assert (await client.put(f"{PATH}/tools", json={"tools": [], "other": ""})).status_code == 422
    assert (await client.put(f"{PATH}/tools", json={"tools": ["fax"]})).status_code == 422
    assert (await client.post(f"{PATH}/connections/gmail", json={"status": "requested"})).status_code == 409
    state = (await client.put(f"{PATH}/tools", json={"tools": ["slack", "gmail", "google_ads"], "other": "Canva"})).json()
    assert [(c["id"], c["status"], c["available"]) for c in state["connections"]] == [("slack", "pending", False), ("gmail", "pending", False), ("google_ads", "pending", True)]
    assert (await client.post(f"{PATH}/connections/slack", json={"status": "skipped"})).status_code == 200
    state = (await client.post(f"{PATH}/connections/gmail", json={"status": "requested"})).json()
    assert state["profile_saved"] and state["tools_saved"]
    assert {c["id"]: c["status"] for c in state["connections"]}["gmail"] == "requested"
    assert facts == []
    done = (await client.post(f"{PATH}/complete")).json()
    assert done["required"] is False and done["completed_at"]
    assert {c["id"]: c["status"] for c in done["connections"]} == {"slack": "skipped", "gmail": "requested", "google_ads": "requested"}
    assert [user for user, _ in facts] == ["alice"] * 4
    assert any("Example Co" in fact for _, fact in facts) and any("Canva" in fact for _, fact in facts)
    # Completing again is a no-op: memory is seeded once.
    assert (await client.post(f"{PATH}/complete")).status_code == 200
    assert len(facts) == 4


@pytest.mark.anyio
async def test_completion_sets_easy_mode_server_side(api, repo):
    client, _, _ = api
    await client.put(f"{PATH}/profile", json={"role": "AM", "team": "Paid"})
    await client.put(f"{PATH}/tools", json={"tools": ["hubspot"]})
    await client.post(f"{PATH}/complete")
    stored = await repo.get("alice")
    assert stored["experience_mode"] == "easy" and stored["mode"] == "flash"
    assert stored["onboarding_profile"] == {"role": "AM", "team": "Paid"}
    assert await repo.get("bob") == {}


@pytest.mark.anyio
async def test_clients_are_never_onboarded(api):
    client, identity, _ = api
    _as(client, identity, "carol")
    assert (await client.get(PATH)).json()["required"] is False
    assert (await client.put(f"{PATH}/profile", json={"role": "x", "team": "y"})).status_code == 403


@pytest.mark.anyio
async def test_connected_only_with_the_users_own_mapped_credential(api, monkeypatch, tmp_path):
    client, identity, _ = api
    slack = McpServerConfig(enabled=True, type="http", url="https://slack-mcp.example.com/mcp", user_auth=McpUserScopedAuthConfig(users={"bob": "Bearer user-token-bob"}))
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: ExtensionsConfig(mcp_servers={"slack-user": slack}, skills={}))
    await client.put(f"{PATH}/profile", json={"role": "AM", "team": "Paid"})
    state = (await client.put(f"{PATH}/tools", json={"tools": ["slack", "meta_ads"]})).json()
    assert [(c["id"], c["status"], c["available"]) for c in state["connections"]] == [("slack", "pending", True), ("meta_ads", "pending", True)]
    _as(client, identity, "bob")
    await client.put(f"{PATH}/profile", json={"role": "Designer", "team": "Creative"})
    from deerflow.config import paths

    monkeypatch.setattr(paths, "get_paths", lambda: SimpleNamespace(user_dir=lambda uid: tmp_path / "users" / uid))
    monkeypatch.setattr("deerflow.community.ads.common.get_paths", lambda: SimpleNamespace(user_dir=lambda uid: tmp_path / "users" / uid))
    creds = tmp_path / "users" / "bob" / "integrations" / "ads" / "credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text(json.dumps({"meta_ads": {"access_token": "x", "allowed_account_ids": ["1"]}}))
    monkeypatch.setattr("deerflow.community.ads.common.get_effective_user_id", lambda: "bob")
    state = (await client.put(f"{PATH}/tools", json={"tools": ["slack", "meta_ads"]})).json()
    assert {c["id"]: c["status"] for c in state["connections"]} == {"slack": "connected", "meta_ads": "connected"}


@pytest.mark.anyio
async def test_admin_request_list_shows_requested_tools_only_to_admins(api):
    client, identity, _ = api
    await client.put(f"{PATH}/profile", json={"role": "AM", "team": "Paid"})
    await client.put(f"{PATH}/tools", json={"tools": ["gmail", "hubspot"], "other": "Canva"})
    await client.post(f"{PATH}/connections/gmail", json={"status": "requested"})
    await client.post(f"{PATH}/connections/hubspot", json={"status": "skipped"})
    await client.post(f"{PATH}/complete")
    assert (await client.get(f"{PATH}/requests")).status_code == 403
    _as(client, identity, "admin")
    [entry] = (await client.get(f"{PATH}/requests")).json()
    assert (entry["email"], entry["tools"], entry["other"]) == ("alice@example.com", {"gmail": "requested", "other": "requested"}, "Canva")
    assert entry["completed_at"]


@pytest.mark.anyio
async def test_step_two_offers_the_whole_plugin_catalog_with_common_tools_pinned(api, monkeypatch):
    client, _, _ = api
    servers = {
        "github": McpServerConfig(enabled=True, type="http", url="https://gh.example.com/mcp"),
        "notion-user": McpServerConfig(enabled=True, type="http", url="https://notion.example.com/mcp", user_auth=McpUserScopedAuthConfig(users={"alice": "Bearer own"})),
        "house-crm": McpServerConfig(enabled=True, type="http", url="https://crm.example.com/mcp"),
    }
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: ExtensionsConfig(mcp_servers=servers, skills={}))
    catalog = (await client.get(PATH)).json()["catalog"]
    ids = [entry["id"] for entry in catalog]
    assert ids[:9] == ["slack", "gmail", "google_calendar", "google_drive", "hubspot", "google_ads", "meta_ads", "ga4", "search_console"]
    assert all(entry["pinned"] for entry in catalog[:9]) and not any(entry["pinned"] for entry in catalog[9:])
    # The plugin catalog and configured MCP servers are offered too; per-user servers fold into their tool.
    assert {"notion", "github", "atlassian", "house-crm"} <= set(ids) and "notion-user" not in ids
    assert ids.count("hubspot") == 1
    await client.put(f"{PATH}/profile", json={"role": "AM", "team": "Paid"})
    assert (await client.put(f"{PATH}/tools", json={"tools": ["not-a-plugin"]})).status_code == 422
    state = (await client.put(f"{PATH}/tools", json={"tools": ["notion", "github", "house-crm", "atlassian"]})).json()
    assert {c["id"]: (c["status"], c["available"]) for c in state["connections"]} == {
        "notion": ("connected", True),
        "github": ("shared", True),
        "house-crm": ("shared", True),
        "atlassian": ("pending", False),
    }


def test_profile_loader_rejects_unsafe_or_missing_keys(people_dir, monkeypatch):
    assert load_own_profile("ALICE@example.com").role == "Account manager"
    for email in (None, "", "../alice@example.com", "alice@example.com/../bob", "nobody@example.com"):
        assert load_own_profile(email) is None
    (people_dir / "big@example.com.md").write_text("x" * (70 * 1024))
    assert load_own_profile("big@example.com") is None
    monkeypatch.delenv("MOMO_PEOPLE_DIR")
    assert load_own_profile("alice@example.com") is None


def test_parse_profile_without_front_matter_keeps_notes_only():
    profile = parse_profile("Just notes here.")
    assert (profile.role, profile.notes) == ("", "Just notes here.")


@pytest.mark.anyio
async def test_deselected_answers_are_dropped_and_concurrent_finish_seeds_once(api, repo):
    import asyncio

    client, _, facts = api
    await client.put(f"{PATH}/profile", json={"role": "AM", "team": "Paid"})
    await client.put(f"{PATH}/tools", json={"tools": ["gmail", "hubspot"]})
    await client.post(f"{PATH}/connections/gmail", json={"status": "requested"})
    await client.put(f"{PATH}/tools", json={"tools": ["hubspot"]})
    assert "gmail" not in (await repo.get("alice")).get("onboarding_connections", {})
    results = await asyncio.gather(client.post(f"{PATH}/complete"), client.post(f"{PATH}/complete"))
    assert all(r.status_code == 200 for r in results)
    assert len(facts) == 4  # one seed: role, clients, tools, working style
    assert (await repo.get("alice"))["onboarding_connections"] == {"hubspot": "requested"}


@pytest.mark.anyio
async def test_shared_workspace_principal_gets_no_personal_memory_or_borrowed_connection(api, monkeypatch):
    from app.gateway.routers import onboarding

    client, _, facts = api
    slack = McpServerConfig(enabled=True, type="http", url="https://slack-mcp.example.com/mcp", user_auth=McpUserScopedAuthConfig(users={"team-principal": "Bearer shared"}))
    bad = McpServerConfig(enabled=True, type="http", url="https://x.example.com/mcp")
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: ExtensionsConfig(mcp_servers={"slack-user": slack, "My Server": bad}, skills={}))
    monkeypatch.setattr(onboarding, "get_effective_user_id", lambda: "team-principal")
    assert "My Server" not in [entry["id"] for entry in (await client.get(PATH)).json()["catalog"]]
    await client.put(f"{PATH}/profile", json={"role": "AM", "team": "Paid"})
    state = (await client.put(f"{PATH}/tools", json={"tools": ["slack"]})).json()
    assert state["connections"][0]["status"] == "pending"
    await client.post(f"{PATH}/complete")
    assert facts == []
