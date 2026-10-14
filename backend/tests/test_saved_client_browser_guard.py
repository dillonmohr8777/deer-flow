from types import SimpleNamespace

import pytest
from langchain_core.tools import ToolException

from deerflow.community.browser_automation.momo_guard import build_private_client_guard
from deerflow.community.browser_automation.momo_protocol import ORGANIZATION, OWNER, signature


class Request:
    def __init__(self, context, server="client_browser"):
        self.server_name = server
        self.runtime = SimpleNamespace(context=context, config={}, server_info=None)
        self.name = "saved_client_sites"
        self.args = {}
        self.headers = {}
    def override(self, *, headers):
        self.headers = headers
        return self


def context():
    return {"actor_user_id": OWNER, "storage_user_id": OWNER,
            "organization_id": ORGANIZATION, "thread_id": "guard-test"}


@pytest.mark.asyncio
async def test_private_scope_is_signed(monkeypatch):
    secret = "Bearer synthetic-test-key"
    monkeypatch.setenv("BRAIN_MCP_AUTHORIZATION", secret)
    req = Request(context())
    seen = []
    async def handler(request):
        seen.append(request)
        return "ok"
    assert await build_private_client_guard()(req, handler) == "ok"
    import json
    h = seen[0].headers
    assert h["X-Momo-Signature"] == signature(secret, json.loads(h["X-Momo-Scope"]),
        h["X-Momo-Nonce"], h["X-Momo-Issued"], req.name, req.args)


@pytest.mark.parametrize("field,value", [
    ("actor_user_id", "other-user"), ("storage_user_id", "shared-workspace"),
    ("organization_id", "shared-org"), ("thread_id", None),
])
@pytest.mark.asyncio
async def test_scope_denied_before_handler(monkeypatch, field, value):
    monkeypatch.setenv("BRAIN_MCP_AUTHORIZATION", "Bearer synthetic-test-key")
    ctx = context()
    ctx[field] = value
    async def handler(request):
        pytest.fail("unauthorized downstream call")
    with pytest.raises(ToolException):
        await build_private_client_guard()(Request(ctx), handler)


@pytest.mark.asyncio
async def test_existing_other_servers_unchanged():
    async def handler(request):
        return "preserved"
    assert await build_private_client_guard()(Request({}, server="browserbase"), handler) == "preserved"


@pytest.mark.asyncio
async def test_missing_credential_denied(monkeypatch):
    monkeypatch.delenv("BRAIN_MCP_AUTHORIZATION", raising=False)
    async def handler(request):
        pytest.fail("missing credential reached transport")
    with pytest.raises(ToolException):
        await build_private_client_guard()(Request(context()), handler)
