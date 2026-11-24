"""Unit and integration tests for Buffer GraphQL client and BufferPublishAdapter.

All HTTP traffic is mocked via ``httpx.MockTransport`` (zero live network calls).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from app.channels import slack_approvals as sa
from app.gateway import approval_adapters
from app.gateway.buffer_publish_adapter import BufferPublishAdapter
from deerflow.approvals import InvalidPayloadError, validate_payload
from deerflow.integrations.buffer import (
    ACTION_TYPE,
    CREATE_POST_MUTATION,
    GET_CHANNELS_QUERY,
    GET_ORGANIZATIONS_QUERY,
    BufferAPIError,
    BufferAuthError,
    BufferGraphQLClient,
    BufferGraphQLError,
    BufferMutationError,
    BufferNetworkError,
    BufferNotConfiguredError,
    BufferOutcomeUnknownError,
    BufferRateLimitError,
    build_post_request,
    scrub_secret,
)

KEY = "buf_test_secret_token_987654321"
async_test = pytest.mark.asyncio
parametrize = pytest.mark.parametrize


def _action(target: str = "ch_gbp_001", payload: dict[str, Any] | None = None, action_id: str = "act_001") -> dict[str, Any]:
    return {
        "id": action_id,
        "action_type": ACTION_TYPE,
        "target": target,
        "title": "Weekly local post",
        "status": "approved",
        "payload": payload if payload is not None else {"service": "googlebusiness", "text": "Spring tune-ups open now.", "mode": "draft"},
    }


def _mock_transport(handler):
    captured: list[dict[str, Any]] = []

    async def _handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(
            {
                "method": request.method,
                "url": str(request.url),
                "authorization": request.headers.get("authorization"),
                "content_type": request.headers.get("content-type"),
                "body": body,
            }
        )
        return handler(request, body)

    return httpx.MockTransport(_handle), captured


# --- Fail-closed & dry-run switches ------------------------------------------


@async_test
async def test_fail_closed_when_api_key_unset_makes_zero_http_calls():
    transport, captured = _mock_transport(lambda _req, _body: httpx.Response(200, json={"data": {}}))
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key="", transport=transport),
        env_getter=lambda: {},
    )
    outcome = await adapter.execute(_action(payload={"service": "linkedin", "text": "Live post", "mode": "shareNow"}))

    assert outcome.status == "failed"
    assert outcome.detail["state"] == "unconfigured"
    assert outcome.detail["api_key_configured"] is False
    assert "BUFFER_API_KEY" in (outcome.error or "")
    assert captured == []


@async_test
async def test_client_fail_closed_when_api_key_whitespace():
    transport, captured = _mock_transport(lambda _req, _body: httpx.Response(200, json={"data": {}}))
    client = BufferGraphQLClient(api_key="   \n\t ", transport=transport)
    assert client.is_configured is False
    with pytest.raises(BufferNotConfiguredError):
        await client.list_organizations()
    assert captured == []


@async_test
async def test_dry_run_via_env_makes_zero_http_calls_and_cannot_be_disabled_by_payload(caplog):
    transport, captured = _mock_transport(lambda _req, _body: httpx.Response(200, json={"data": {}}))
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=transport),
        env_getter=lambda: {"BUFFER_API_KEY": KEY, "BUFFER_DRY_RUN": "true"},
    )
    with caplog.at_level(logging.INFO):
        outcome = await adapter.execute(
            _action(
                target="ch_li_100",
                payload={
                    "service": "linkedin",
                    "text": "Dry run cannot be bypassed.",
                    "mode": "shareNow",
                    "dry_run": False,
                },
            )
        )

    assert outcome.status == "approved"
    assert outcome.error is None
    assert outcome.detail["state"] == "dry_run"
    assert outcome.detail["dry_run"] is True
    assert outcome.detail["api_key_configured"] is True
    assert outcome.detail["graphql_input"] == {
        "channelId": "ch_li_100",
        "schedulingType": "automatic",
        "mode": "shareNow",
        "text": "Dry run cannot be bypassed.",
    }
    assert captured == []
    assert KEY not in caplog.text
    assert "Buffer dry-run receipt" in caplog.text


@async_test
async def test_dry_run_via_payload_flag_without_api_key():
    transport, captured = _mock_transport(lambda _req, _body: httpx.Response(200, json={"data": {}}))
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key="", transport=transport),
        env_getter=lambda: {},
    )
    outcome = await adapter.execute(
        _action(
            target="ch_gbp_002",
            payload={"service": "gbp", "text": "Preview update", "mode": "draft", "dry_run": True},
        )
    )

    assert outcome.status == "approved"
    assert outcome.detail["state"] == "dry_run"
    assert outcome.detail["api_key_configured"] is False
    assert outcome.detail["graphql_input"]["saveToDraft"] is True
    assert outcome.detail["graphql_input"]["mode"] == "addToQueue"
    assert captured == []


@async_test
async def test_channel_allowlist_blocks_unlisted_channel_in_both_live_and_dry_run():
    transport, captured = _mock_transport(lambda _req, _body: httpx.Response(200, json={"data": {}}))
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=transport),
        env_getter=lambda: {
            "BUFFER_API_KEY": KEY,
            "BUFFER_DRY_RUN": "true",
            "BUFFER_ALLOWED_CHANNEL_IDS": "ch_sandbox_1, ch_sandbox_2",
        },
    )
    blocked = await adapter.execute(_action(target="ch_prod_999", payload={"service": "linkedin", "text": "Wrong org"}))
    assert blocked.status == "failed"
    assert blocked.detail["state"] == "channel_not_allowed"
    assert "BUFFER_ALLOWED_CHANNEL_IDS" in (blocked.error or "")

    allowed = await adapter.execute(_action(target="ch_sandbox_2", payload={"service": "linkedin", "text": "Sandbox ok"}))
    assert allowed.status == "approved"
    assert allowed.detail["state"] == "dry_run"
    assert captured == []


# --- Channel listing (organizations + channels GraphQL queries) --------------


@async_test
async def test_list_channels_discovers_organizations_and_filters_services():
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            assert query == GET_ORGANIZATIONS_QUERY
            return httpx.Response(
                200,
                json={
                    "data": {
                        "account": {
                            "id": "acct_1",
                            "email": "ops" + "@example.com",
                            "organizations": [
                                {"id": "org_1", "name": "Sandbox Org"},
                                {"id": "org_2", "name": "Second Org"},
                            ],
                        }
                    }
                },
            )
        if "GetChannels" in query:
            assert query == GET_CHANNELS_QUERY
            org_id = body["variables"]["organizationId"]
            if org_id == "org_1":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "channels": [
                                {
                                    "id": "ch_gbp",
                                    "name": "Acme Philly",
                                    "displayName": "Acme Philly GBP",
                                    "service": "googlebusiness",
                                    "avatar": "https://cdn.example.com/a.png",
                                    "isQueuePaused": False,
                                },
                                {
                                    "id": "ch_li",
                                    "name": "Acme LinkedIn",
                                    "displayName": "Acme Co",
                                    "service": "linkedin",
                                    "avatar": None,
                                    "isQueuePaused": True,
                                },
                            ]
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "channels": [
                            {
                                "id": "ch_ig",
                                "name": "@acme",
                                "displayName": "Acme IG",
                                "service": "instagram",
                                "avatar": None,
                                "isQueuePaused": False,
                            },
                            {
                                "id": "ch_x",
                                "name": "@acmex",
                                "displayName": "Acme X",
                                "service": "twitter",
                                "avatar": None,
                                "isQueuePaused": False,
                            },
                        ]
                    }
                },
            )
        return httpx.Response(500, json={"error": "unexpected query"})

    transport, captured = _mock_transport(_handler)
    client = BufferGraphQLClient(api_key=KEY, transport=transport)

    all_channels = await client.list_channels()
    assert [c.id for c in all_channels] == ["ch_gbp", "ch_li", "ch_ig", "ch_x"]
    assert all_channels[0].organization_id == "org_1"
    assert all_channels[0].organization_name == "Sandbox Org"
    assert all_channels[1].is_queue_paused is True
    assert all(req["authorization"] == f"Bearer {KEY}" for req in captured)
    assert all(req["url"] == "https://api.buffer.com" for req in captured)

    gbp_and_x = await client.list_channels(services=["gbp", "x"])
    assert [(c.id, c.service) for c in gbp_and_x] == [("ch_gbp", "googlebusiness"), ("ch_x", "twitter")]


@async_test
async def test_list_channels_with_explicit_organization_id_skips_org_query():
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        assert "GetChannels" in body["query"]
        assert body["variables"] == {"organizationId": "org_pinned"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "channels": [
                        {
                            "id": "ch_fb",
                            "name": "Acme FB",
                            "displayName": "Acme Page",
                            "service": "facebook",
                            "avatar": None,
                            "isQueuePaused": False,
                        }
                    ]
                }
            },
        )

    transport, captured = _mock_transport(_handler)
    client = BufferGraphQLClient(api_key=KEY, transport=transport)
    channels = await client.list_channels(organization_id="org_pinned")
    assert len(captured) == 1
    assert len(channels) == 1
    assert channels[0].to_dict()["service"] == "facebook"


# --- createPost across all 5 networks (GBP, LinkedIn, Facebook, IG, X) -------


@async_test
@parametrize(
    ("service_in", "expected_service", "payload_extra", "expected_input_subset"),
    [
        (
            "gbp",
            "googlebusiness",
            {
                "text": "Free HVAC inspection this week.",
                "mode": "customScheduled",
                "due_at": "2026-12-01T14:30:00-05:00",
                "metadata": {
                    "post_type": "post",
                    "cta_button": "BOOK",
                    "cta_link": "https://example.com/book",
                },
            },
            {
                "mode": "customScheduled",
                "dueAt": "2026-12-01T19:30:00Z",
                "metadata": {
                    "google": {
                        "type": "post",
                        "detailsWhatsNew": {"button": "BOOK", "link": "https://example.com/book"},
                    }
                },
            },
        ),
        (
            "linkedin",
            "linkedin",
            {
                "text": "How local contractors cut lead response time to 90 seconds.",
                "mode": "addToQueue",
                "metadata": {
                    "first_comment": "Full breakdown: https://example.com/guide",
                    "link_attachment": {"url": "https://example.com/guide", "title": "Response Guide"},
                },
            },
            {
                "mode": "addToQueue",
                "metadata": {
                    "linkedin": {
                        "firstComment": "Full breakdown: https://example.com/guide",
                        "linkAttachment": {"url": "https://example.com/guide", "title": "Response Guide"},
                    }
                },
            },
        ),
        (
            "facebook",
            "facebook",
            {
                "text": "Before and after patio install in Main Line.",
                "mode": "shareNow",
                "assets": [{"type": "image", "url": "https://cdn.example.com/patio.jpg"}],
                "metadata": {"type": "post", "first_comment": "Book an estimate at example.com"},
            },
            {
                "mode": "shareNow",
                "assets": [{"image": {"url": "https://cdn.example.com/patio.jpg"}}],
                "metadata": {
                    "facebook": {
                        "type": "post",
                        "firstComment": "Book an estimate at example.com",
                    }
                },
            },
        ),
        (
            "instagram",
            "instagram",
            {
                "text": "New roof finished before the storm.",
                "mode": "draft",
                "assets": [{"image": {"url": "https://cdn.example.com/roof.jpg"}}],
                "metadata": {
                    "instagram": {
                        "shouldShareToFeed": True,
                        "firstComment": "#phillycontractors",
                        "isAiGenerated": False,
                    }
                },
            },
            {
                "mode": "addToQueue",
                "saveToDraft": True,
                "assets": [{"image": {"url": "https://cdn.example.com/roof.jpg"}}],
                "metadata": {
                    "instagram": {
                        "shouldShareToFeed": True,
                        "firstComment": "#phillycontractors",
                        "isAiGenerated": False,
                    }
                },
            },
        ),
        (
            "x",
            "twitter",
            {
                "text": "Shipping Buffer publishing behind MomoBot approvals.",
                "mode": "shareNext",
                "assets": [{"type": "video", "url": "https://cdn.example.com/demo.mp4", "metadata": {"thumbnailOffset": 1000}}],
            },
            {
                "mode": "shareNext",
                "assets": [{"video": {"url": "https://cdn.example.com/demo.mp4", "metadata": {"thumbnailOffset": 1000}}}],
            },
        ),
    ],
)
async def test_adapter_publishes_all_five_platforms_with_exact_receipt(
    service_in: str,
    expected_service: str,
    payload_extra: dict[str, Any],
    expected_input_subset: dict[str, Any],
    caplog,
):
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        assert body["query"] == CREATE_POST_MUTATION
        post_input = body["variables"]["input"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "createPost": {
                        "__typename": "PostActionSuccess",
                        "post": {
                            "id": f"post_{expected_service}_01",
                            "text": post_input.get("text", ""),
                            "status": "draft" if post_input.get("saveToDraft") else "scheduled",
                            "dueAt": post_input.get("dueAt"),
                            "externalLink": f"https://social.example.com/{expected_service}/post_01",
                        },
                    }
                }
            },
        )

    transport, captured = _mock_transport(_handler)
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=transport),
        env_getter=lambda: {"BUFFER_API_KEY": KEY},
    )

    payload = {"service": service_in, **payload_extra}
    with caplog.at_level(logging.INFO):
        outcome = await adapter.execute(_action(target=f"ch_{expected_service}", payload=payload, action_id=f"act_{expected_service}"))

    assert outcome.status == "executed"
    assert outcome.error is None
    assert len(captured) == 1
    assert captured[0]["authorization"] == f"Bearer {KEY}"
    sent_input = captured[0]["body"]["variables"]["input"]
    assert sent_input["channelId"] == f"ch_{expected_service}"
    assert sent_input["schedulingType"] == "automatic"
    for key, expected_val in expected_input_subset.items():
        assert sent_input[key] == expected_val

    receipt = outcome.detail
    assert receipt["provider"] == "buffer"
    assert receipt["state"] == "published"
    assert receipt["action_id"] == f"act_{expected_service}"
    assert receipt["channel_id"] == f"ch_{expected_service}"
    assert receipt["service"] == expected_service
    assert receipt["post_id"] == f"post_{expected_service}_01"
    assert receipt["external_link"] == f"https://social.example.com/{expected_service}/post_01"
    assert receipt["http_status"] == 200
    assert isinstance(receipt["elapsed_ms"], int)
    assert receipt["dry_run"] is False
    assert "Buffer publish receipt" in caplog.text
    assert KEY not in caplog.text
    assert KEY not in json.dumps(receipt)


# --- Validation edge cases ---------------------------------------------------


@parametrize(
    ("target", "payload", "expected_msg"),
    [
        ("", {"service": "linkedin", "text": "No channel"}, "channel_id"),
        ("ch_1", {"service": "linkedin", "channel_id": "ch_2", "text": "Mismatch"}, "must match"),
        ("ch_1", {"service": "myspace", "text": "Unknown"}, "Unsupported Buffer service"),
        ("ch_1", {"service": "linkedin", "text": "   "}, "non-empty payload.text or at least one asset"),
        ("ch_1", {"service": "instagram", "text": "No media"}, "at least one image or video asset"),
        ("ch_1", {"service": "linkedin", "text": "Sched", "mode": "customScheduled"}, "requires payload.due_at"),
        ("ch_1", {"service": "linkedin", "text": "Naive ts", "mode": "customScheduled", "due_at": "2026-12-01T12:00:00"}, "timezone"),
        ("ch_1", {"service": "linkedin", "text": "Extra ts", "mode": "shareNow", "due_at": "2026-12-01T12:00:00Z"}, "only valid with mode='customScheduled'"),
        ("ch_1", {"service": "linkedin", "text": "Conflict", "mode": "shareNow", "save_to_draft": True}, "conflicts"),
        ("ch_1", {"service": "linkedin", "text": "Conflict2", "mode": "draft", "save_to_draft": False}, "conflicts"),
        ("ch_1", {"service": "facebook", "text": "Bad URL", "assets": [{"type": "image", "url": "file:///etc/passwd"}]}, "http:// or https://"),
        (
            "ch_1",
            {"service": "facebook", "text": "Cred URL", "assets": [{"type": "image", "url": "https://user:pass" + "@cdn.example.com/a.jpg"}]},
            "embedded credentials",
        ),
        (
            "ch_1",
            {
                "service": "linkedin",
                "text": "Both",
                "assets": [{"type": "image", "url": "https://cdn.example.com/a.jpg"}],
                "metadata": {"link_attachment": {"url": "https://example.com"}},
            },
            "cannot be combined",
        ),
        ("ch_1", {"service": "twitter", "text": "Leak", "api_key": "should-fail"}, "Credential-bearing"),
        ("ch_1", {"service": "gbp", "text": "Bad GBP", "metadata": {"post_type": "invalid"}}, "Google Business Profile post type"),
    ],
)
def test_validation_rejects_invalid_payloads(target: str, payload: dict[str, Any], expected_msg: str):
    with pytest.raises(InvalidPayloadError, match=expected_msg):
        validate_payload(ACTION_TYPE, target, payload)


def test_gbp_offer_and_event_metadata_validation():
    req = build_post_request(
        "ch_gbp_9",
        {
            "service": "google_business_profile",
            "text": "20% off roof tune-up.",
            "mode": "draft",
            "metadata": {
                "type": "offer",
                "title": "Winter Roof Special",
                "detailsOffer": {"couponCode": "ROOF20", "redeemOnlineUrl": "https://example.com/offer"},
            },
        },
    )
    assert req.to_graphql_input()["metadata"] == {
        "google": {
            "type": "offer",
            "title": "Winter Roof Special",
            "detailsOffer": {"couponCode": "ROOF20", "redeemOnlineUrl": "https://example.com/offer"},
        }
    }


# --- Error taxonomy, outcome_unknown & zero-secret-leak ----------------------


@async_test
async def test_mutation_error_and_secret_scrubbing(caplog):
    def _handler(_request: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "createPost": {
                        "__typename": "LimitReachedError",
                        "message": f"Queue limit reached for token Bearer {KEY}",
                    }
                }
            },
        )

    transport, _ = _mock_transport(_handler)
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=transport),
        env_getter=lambda: {"BUFFER_API_KEY": KEY},
    )
    with caplog.at_level(logging.WARNING):
        outcome = await adapter.execute(_action(payload={"service": "linkedin", "text": "Hit cap", "mode": "addToQueue"}))

    assert outcome.status == "failed"
    assert outcome.detail["state"] == "mutation_rejected"
    assert outcome.detail["error_type"] == "LimitReachedError"
    assert "LimitReachedError" in (outcome.error or "")
    assert "[redacted]" in (outcome.error or "")
    assert KEY not in (outcome.error or "")
    assert KEY not in caplog.text

    with pytest.raises(BufferMutationError) as exc_mut:
        await BufferGraphQLClient(api_key=KEY, transport=transport).create_post(build_post_request("ch_1", {"service": "linkedin", "text": "Hit cap", "mode": "addToQueue"}))
    assert exc_mut.value.error_type == "LimitReachedError"
    assert KEY not in str(exc_mut.value)


def test_client_rejects_insecure_remote_api_url_and_embedded_credentials():
    with pytest.raises(InvalidPayloadError, match="https://"):
        BufferGraphQLClient(api_key=KEY, api_url="http://api.buffer.com")
    with pytest.raises(InvalidPayloadError, match="embedded credentials"):
        BufferGraphQLClient(api_key=KEY, api_url="https://user:pass" + "@api.buffer.com")
    # Loopback HTTP is permitted for local mock testing.
    local = BufferGraphQLClient(api_key=KEY, api_url="http://127.0.0.1:8787")
    assert local.api_url == "http://127.0.0.1:8787"


@async_test
async def test_http_401_429_502_and_graphql_errors():
    # 401
    t401, _ = _mock_transport(lambda _r, _b: httpx.Response(401, json={"error": "unauthorized"}))
    a401 = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t401), env_getter=lambda: {"BUFFER_API_KEY": KEY})
    r401 = await a401.execute(_action())
    assert r401.status == "failed" and r401.detail["state"] == "auth_failed"

    # 429 with Retry-After
    t429, _ = _mock_transport(lambda _r, _b: httpx.Response(429, headers={"Retry-After": "60"}, json={"error": "slow down"}))
    a429 = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t429), env_getter=lambda: {"BUFFER_API_KEY": KEY})
    r429 = await a429.execute(_action())
    assert r429.status == "failed" and r429.detail["state"] == "rate_limited" and r429.detail["retry_after"] == "60"

    # 502
    t502, _ = _mock_transport(lambda _r, _b: httpx.Response(502, text="Bad Gateway"))
    a502 = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t502), env_getter=lambda: {"BUFFER_API_KEY": KEY})
    r502 = await a502.execute(_action())
    assert r502.status == "failed" and r502.detail["state"] == "api_error" and r502.detail["http_status"] == 502

    # Top-level GraphQL errors
    tgql, _ = _mock_transport(lambda _r, _b: httpx.Response(200, json={"errors": [{"message": "Invalid field"}]}))
    agql = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=tgql), env_getter=lambda: {"BUFFER_API_KEY": KEY})
    rgql = await agql.execute(_action())
    assert rgql.status == "failed" and rgql.detail["state"] == "graphql_error" and "Invalid field" in (rgql.error or "")

    # Direct client error types
    with pytest.raises(BufferAuthError):
        await BufferGraphQLClient(api_key=KEY, transport=t401).list_organizations()
    with pytest.raises(BufferRateLimitError) as exc_rl:
        await BufferGraphQLClient(api_key=KEY, transport=t429).list_organizations()
    assert exc_rl.value.retry_after == "60"
    with pytest.raises(BufferAPIError):
        await BufferGraphQLClient(api_key=KEY, transport=t502).list_organizations()
    with pytest.raises(BufferGraphQLError):
        await BufferGraphQLClient(api_key=KEY, transport=tgql).list_organizations()


@async_test
async def test_read_timeout_on_mutation_returns_outcome_unknown_while_connect_error_fails():
    async def _timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out waiting for Buffer")

    async def _connect_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    timeout_client = BufferGraphQLClient(api_key=KEY, transport=httpx.MockTransport(_timeout_handler))
    timeout_adapter = BufferPublishAdapter(client_factory=lambda: timeout_client, env_getter=lambda: {"BUFFER_API_KEY": KEY})
    out_unknown = await timeout_adapter.execute(_action())
    assert out_unknown.status == "approved"
    assert out_unknown.detail["state"] == "outcome_unknown"
    assert (out_unknown.error or "").startswith("outcome_unknown:")

    connect_client = BufferGraphQLClient(api_key=KEY, transport=httpx.MockTransport(_connect_handler))
    connect_adapter = BufferPublishAdapter(client_factory=lambda: connect_client, env_getter=lambda: {"BUFFER_API_KEY": KEY})
    out_net = await connect_adapter.execute(_action())
    assert out_net.status == "failed"
    assert out_net.detail["state"] == "network_error"

    with pytest.raises(BufferOutcomeUnknownError):
        await timeout_client.create_post(build_post_request("ch_1", {"service": "linkedin", "text": "Hi"}))
    with pytest.raises(BufferNetworkError):
        await connect_client.create_post(build_post_request("ch_1", {"service": "linkedin", "text": "Hi"}))


# --- Approvals wiring & Slack DM web-only guard ------------------------------


@async_test
async def test_execute_approved_routes_buffer_post_and_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("BUFFER_API_KEY", raising=False)
    monkeypatch.delenv("BUFFER_DRY_RUN", raising=False)
    outcome = await approval_adapters.execute_approved(_action(payload={"service": "gbp", "text": "Update", "mode": "shareNow"}))
    assert outcome.status == "failed"
    assert outcome.detail["state"] == "unconfigured"


@async_test
async def test_slack_approvals_dm_treats_buffer_post_as_web_only():
    cfg = sa.parse_config({"enabled": True, "user_ids": ["U1"], "base_url": "https://momo.example"})
    row = {
        "id": "buf123",
        "action_type": ACTION_TYPE,
        "title": "GBP Update",
        "target": "ch_gbp_001",
        "payload": {"service": "googlebusiness", "text": "Open Saturday 8-5."},
        "status": "pending",
        "agent_name": "momo",
        "user_id": "owner",
    }
    text, blocks = sa.build_message(row, cfg)
    assert "Approval needed in MomoBot" in text
    assert all(b.get("type") != "actions" for b in blocks)
    assert "https://momo.example/workspace/approvals?id=buf123" in blocks[2]["elements"][0]["text"]

    class _FakeStore:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def get(self, _action_id: str) -> dict[str, Any]:
            return row

        async def decide(self, *_args: Any, **_kwargs: Any) -> None:
            self.calls.append("called")
            return None

    store = _FakeStore()
    press = sa.ParsedAction(verb="approve", item_id="buf123", user_id="U1", channel="D1", message_ts="1.2", blocks=[])
    result = await sa.route_action(press, cfg, store)
    assert result.kind == "web_only"
    assert "https://momo.example/workspace/approvals?id=buf123" in result.text
    assert store.calls == []


def test_scrub_secret_redacts_key_and_bearer():
    raw = f"Error with Bearer {KEY} and " + "api_" + "key=abc123456"
    cleaned = scrub_secret(raw, KEY)
    assert KEY not in cleaned
    assert "abc123456" not in cleaned
    assert "[redacted]" in cleaned
