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


def _action(
    target: str = "ch_gbp_001",
    payload: dict[str, Any] | None = None,
    action_id: str = "act_001",
    organization_id: str | None = "ws_default",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": action_id,
        "action_type": ACTION_TYPE,
        "target": target,
        "title": "Weekly local post",
        "status": "approved",
        "payload": payload if payload is not None else {"service": "googlebusiness", "text": "Spring tune-ups open now.", "mode": "draft"},
    }
    if organization_id is not None:
        row["organization_id"] = organization_id
    return row


def _live_env(*channels: str, workspace_id: str = "ws_default", extra: dict[str, str] | None = None) -> dict[str, str]:
    bound = list(channels) or ["ch_gbp_001", "ch_1", "ch_fb"]
    env = {
        "BUFFER_API_KEY": KEY,
        "BUFFER_WORKSPACE_CHANNELS": json.dumps({workspace_id: bound}),
    }
    if extra:
        env.update(extra)
    return env


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
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Test Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "channels": [
                            {"id": f"ch_{expected_service}", "name": "test", "displayName": "Test", "service": expected_service, "isQueuePaused": False}
                        ]
                    }
                },
            )
        assert query == CREATE_POST_MUTATION
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
        env_getter=lambda: _live_env(f"ch_{expected_service}"),
    )

    payload = {"service": service_in, **payload_extra}
    with caplog.at_level(logging.INFO):
        outcome = await adapter.execute(_action(target=f"ch_{expected_service}", payload=payload, action_id=f"act_{expected_service}"))

    assert outcome.status == "executed"
    assert outcome.error is None
    assert len(captured) == 3
    assert all(req["authorization"] == f"Bearer {KEY}" for req in captured)
    sent_input = captured[-1]["body"]["variables"]["input"]
    assert sent_input["channelId"] == f"ch_{expected_service}"
    assert sent_input["schedulingType"] == "automatic"
    for key, expected_val in expected_input_subset.items():
        assert sent_input[key] == expected_val

    receipt = outcome.detail
    assert receipt["provider"] == "buffer"
    expected_state = "draft_saved" if sent_input.get("saveToDraft") else "scheduled"
    assert receipt["state"] == expected_state
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
        (
            "ch_1",
            {
                "service": "gbp",
                "text": "Mixed metadata",
                "metadata": {"google": {"type": "offer"}, "campaign": "Q4"},
            },
            "cannot mix service blocks",
        ),
        (
            "ch_1",
            {"service": "linkedin", "text": "Unknown field", "metadata": {"unknown_key": "value"}},
            "Unsupported linkedin metadata fields",
        ),
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
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Test Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "channels": [
                            {"id": "ch_1", "name": "li", "displayName": "LI", "service": "linkedin", "isQueuePaused": False},
                            {"id": "ch_gbp_001", "name": "li2", "displayName": "LI2", "service": "linkedin", "isQueuePaused": False},
                        ]
                    }
                },
            )
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
        env_getter=_live_env,
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
    a401 = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t401), env_getter=_live_env)
    r401 = await a401.execute(_action())
    assert r401.status == "failed" and r401.detail["state"] == "auth_failed"

    # 429 with Retry-After
    t429, _ = _mock_transport(lambda _r, _b: httpx.Response(429, headers={"Retry-After": "60"}, json={"error": "slow down"}))
    a429 = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t429), env_getter=_live_env)
    r429 = await a429.execute(_action())
    assert r429.status == "failed" and r429.detail["state"] == "rate_limited" and r429.detail["retry_after"] == "60"

    # 502
    t502, _ = _mock_transport(lambda _r, _b: httpx.Response(502, text="Bad Gateway"))
    a502 = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t502), env_getter=_live_env)
    r502 = await a502.execute(_action())
    assert r502.status == "failed" and r502.detail["state"] == "api_error" and r502.detail["http_status"] == 502

    # Top-level GraphQL errors
    tgql, _ = _mock_transport(lambda _r, _b: httpx.Response(200, json={"errors": [{"message": "Invalid field"}]}))
    agql = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=tgql), env_getter=_live_env)
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
    async def _timeout_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Test Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "channels": [
                            {"id": "ch_1", "name": "li", "displayName": "LI", "service": "linkedin", "isQueuePaused": False},
                            {"id": "ch_gbp_001", "name": "gbp", "displayName": "GBP", "service": "googlebusiness", "isQueuePaused": False},
                        ]
                    }
                },
            )
        raise httpx.ReadTimeout("timed out waiting for Buffer")

    async def _connect_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    timeout_client = BufferGraphQLClient(api_key=KEY, transport=httpx.MockTransport(_timeout_handler))
    timeout_adapter = BufferPublishAdapter(client_factory=lambda: timeout_client, env_getter=_live_env)
    out_unknown = await timeout_adapter.execute(_action())
    assert out_unknown.status == "approved"
    assert out_unknown.detail["state"] == "outcome_unknown"
    assert (out_unknown.error or "").startswith("outcome_unknown:")

    connect_client = BufferGraphQLClient(api_key=KEY, transport=httpx.MockTransport(_connect_handler))
    connect_adapter = BufferPublishAdapter(client_factory=lambda: connect_client, env_getter=_live_env)
    out_net = await connect_adapter.execute(_action())
    assert out_net.status == "failed"
    assert out_net.detail["state"] == "network_error"

    with pytest.raises(BufferOutcomeUnknownError):
        await timeout_client.create_post(build_post_request("ch_1", {"service": "linkedin", "text": "Hi"}))
    with pytest.raises(BufferNetworkError):
        await connect_client.create_post(build_post_request("ch_1", {"service": "linkedin", "text": "Hi"}))


@async_test
async def test_daybreak_security_regressions_service_mismatch_allowlist_empty_metadata_5xx():
    # 1) Cross-service mismatch blocks BEFORE createPost is sent.
    def _mismatch_handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={"data": {"channels": [{"id": "ch_fb", "name": "fb", "displayName": "FB", "service": "facebook", "isQueuePaused": False}]}},
            )
        raise AssertionError("createPost must never be invoked when channel service mismatches")

    t_mis, cap_mis = _mock_transport(_mismatch_handler)
    a_mis = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_mis), env_getter=_live_env)
    res_mis = await a_mis.execute(_action(target="ch_fb", payload={"service": "linkedin", "text": "Wrong channel"}))
    assert res_mis.status == "failed"
    assert res_mis.detail["state"] == "mutation_rejected"
    assert res_mis.detail["error_type"] == "ChannelServiceMismatch"
    assert len(cap_mis) == 2

    # 2) Whitespace/comma-only BUFFER_ALLOWED_CHANNEL_IDS fails closed (never falls open).
    t_empty, cap_empty = _mock_transport(lambda _r, _b: httpx.Response(200, json={"data": {}}))
    a_empty = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_empty),
        env_getter=lambda: {"BUFFER_API_KEY": KEY, "BUFFER_ALLOWED_CHANNEL_IDS": " , , "},
    )
    res_empty = await a_empty.execute(_action(target="ch_any", payload={"service": "linkedin", "text": "Blocked"}))
    assert res_empty.status == "failed"
    assert res_empty.detail["state"] == "channel_not_allowed"
    assert cap_empty == []

    # 3) Explicit empty metadata={} is accepted as absent optional metadata.
    req_empty_meta = build_post_request("ch_1", {"service": "linkedin", "text": "Empty meta ok", "metadata": {}})
    assert "metadata" not in req_empty_meta.to_graphql_input()

    # 4) HTTP 5xx on createPost mutation returns outcome_unknown (prevents duplicate reposts).
    def _502_mut_handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "channels": [
                            {"id": "ch_1", "name": "li", "displayName": "LI", "service": "linkedin", "isQueuePaused": False},
                            {"id": "ch_gbp_001", "name": "li2", "displayName": "LI2", "service": "linkedin", "isQueuePaused": False},
                        ]
                    }
                },
            )
        return httpx.Response(502, text="Bad Gateway")

    t_502, _ = _mock_transport(_502_mut_handler)
    a_502 = BufferPublishAdapter(client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_502), env_getter=_live_env)
    res_502 = await a_502.execute(_action(target="ch_1", payload={"service": "linkedin", "text": "May have landed"}))
    assert res_502.status == "approved"
    assert res_502.detail["state"] == "outcome_unknown"
    assert (res_502.error or "").startswith("outcome_unknown:")


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


@async_test
async def test_workspace_binding_blocks_cross_workspace_and_multi_org_discovery():
    def _multi_org_handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "account": {
                            "id": "acc_1",
                            "organizations": [
                                {"id": "org_alpha", "name": "Alpha"},
                                {"id": "org_beta", "name": "Beta"},
                            ],
                        }
                    }
                },
            )
        if "GetChannels" in query:
            org_id = body["variables"]["organizationId"]
            if org_id == "org_alpha":
                return httpx.Response(
                    200,
                    json={"data": {"channels": [{"id": "ch_alpha", "name": "A", "displayName": "A", "service": "linkedin", "isQueuePaused": False}]}},
                )
            return httpx.Response(
                200,
                json={"data": {"channels": [{"id": "ch_beta", "name": "B", "displayName": "B", "service": "linkedin", "isQueuePaused": False}]}},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "createPost": {
                        "__typename": "PostActionSuccess",
                        "post": {"id": "post_alpha_1", "text": "Scoped", "status": "scheduled", "dueAt": None, "externalLink": None},
                    }
                }
            },
        )

    # 1) Unbound multi-org client refuses account-wide channel discovery.
    t_multi, cap_multi = _mock_transport(_multi_org_handler)
    client_multi = BufferGraphQLClient(api_key=KEY, transport=t_multi)
    with pytest.raises(BufferMutationError) as exc_org:
        await client_multi.create_post(build_post_request("ch_beta", {"service": "linkedin", "text": "Unbound"}))
    assert exc_org.value.error_type == "OrganizationBindingRequired"
    assert len(cap_multi) == 1

    # 2) Approval without workspace_id fails closed on live publish.
    t_missing_ws, cap_missing_ws = _mock_transport(_multi_org_handler)
    adapter_missing_ws = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_missing_ws),
        env_getter=lambda: {"BUFFER_API_KEY": KEY, "BUFFER_WORKSPACE_CHANNELS": json.dumps({"ws_alpha": ["ch_alpha"]})},
    )
    res_missing_ws = await adapter_missing_ws.execute(_action(target="ch_alpha", payload={"service": "linkedin", "text": "No WS"}, organization_id=None))
    assert res_missing_ws.status == "failed"
    assert res_missing_ws.detail["state"] in {"workspace_not_bound", "workspace_channel_not_allowed"}
    assert cap_missing_ws == []

    # 2b) Approval without workspace_id fails closed even when BUFFER_WORKSPACE_CHANNELS is unset.
    t_no_ws_no_cfg, cap_no_ws_no_cfg = _mock_transport(_multi_org_handler)
    adapter_no_ws_no_cfg = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_no_ws_no_cfg),
        env_getter=lambda: {"BUFFER_API_KEY": KEY},
    )
    res_no_ws_no_cfg = await adapter_no_ws_no_cfg.execute(_action(target="ch_alpha", payload={"service": "linkedin", "text": "No WS"}, organization_id=None))
    assert res_no_ws_no_cfg.status == "failed"
    assert res_no_ws_no_cfg.detail["state"] == "workspace_not_bound"
    assert cap_no_ws_no_cfg == []

    # 2c) BUFFER_WORKSPACE_ORGANIZATIONS alone (without BUFFER_WORKSPACE_CHANNELS) still fails closed on live publish.
    t_org_only, cap_org_only = _mock_transport(_multi_org_handler)
    adapter_org_only = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_org_only),
        env_getter=lambda: {"BUFFER_API_KEY": KEY, "BUFFER_WORKSPACE_ORGANIZATIONS": json.dumps({"ws_alpha": "org_alpha"})},
    )
    ws_action = {**_action(target="ch_alpha", payload={"service": "linkedin", "text": "Scoped"}), "organization_id": "ws_alpha"}
    res_org_only = await adapter_org_only.execute(ws_action)
    assert res_org_only.status == "failed"
    assert res_org_only.detail["state"] == "workspace_not_bound"
    assert cap_org_only == []

    # 2d) Approval carrying workspace_id fails closed if no workspace binding map is configured.
    t_unbound, cap_unbound = _mock_transport(_multi_org_handler)
    adapter_unbound = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_unbound),
        env_getter=lambda: {"BUFFER_API_KEY": KEY},
    )
    res_unbound = await adapter_unbound.execute(ws_action)
    assert res_unbound.status == "failed"
    assert res_unbound.detail["state"] == "workspace_not_bound"
    assert cap_unbound == []

    # 3) Explicit workspace channel + org binding blocks cross-workspace channel and allows own channel.
    env_bound = {
        "BUFFER_API_KEY": KEY,
        "BUFFER_WORKSPACE_CHANNELS": json.dumps({"ws_alpha": ["ch_alpha"], "ws_beta": ["ch_beta"]}),
        "BUFFER_WORKSPACE_ORGANIZATIONS": json.dumps({"ws_alpha": "org_alpha", "ws_beta": "org_beta"}),
    }
    t_bound, cap_bound = _mock_transport(_multi_org_handler)
    adapter_bound = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_bound),
        env_getter=lambda: env_bound,
    )
    cross = await adapter_bound.execute({**_action(target="ch_beta", payload={"service": "linkedin", "text": "Cross"}), "organization_id": "ws_alpha"})
    assert cross.status == "failed"
    assert cross.detail["state"] == "workspace_channel_not_allowed"
    assert cap_bound == []

    allowed = await adapter_bound.execute(ws_action)
    assert allowed.status == "executed"
    assert allowed.detail["post_id"] == "post_alpha_1"
    # Skips GetOrganizations completely because org_alpha is pinned directly.
    assert [c["body"]["query"] for c in cap_bound] == [GET_CHANNELS_QUERY, CREATE_POST_MUTATION]
    assert cap_bound[0]["body"]["variables"] == {"organizationId": "org_alpha"}


@async_test
@parametrize(
    "mutation_response",
    [
        httpx.Response(200, json={"data": {}}),
        httpx.Response(200, json={"data": {"createPost": {"__typename": "PostActionSuccess", "post": {}}}}),
        httpx.Response(
            200,
            json={
                "errors": [{"message": "Partial downstream error"}],
                "data": {"createPost": {"__typename": "PostActionSuccess", "post": {"id": "post_1"}}},
            },
        ),
        httpx.Response(200, json={"errors": [{"message": "Field error"}], "data": {"createPost": None}}),
        httpx.Response(200, json={"data": {"createPost": {"__typename": "UnexpectedUnionVariant"}}}),
        httpx.Response(200, text="not-valid-json"),
    ],
)
async def test_ambiguous_post_mutation_responses_return_outcome_unknown(mutation_response: httpx.Response):
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={"data": {"channels": [{"id": "ch_1", "name": "li", "displayName": "LI", "service": "linkedin", "isQueuePaused": False}]}},
            )
        return mutation_response

    transport, _ = _mock_transport(_handler)
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=transport),
        env_getter=_live_env,
    )
    outcome = await adapter.execute(_action(target="ch_1", payload={"service": "linkedin", "text": "Ambiguous"}))
    assert outcome.status == "approved"
    assert outcome.detail["state"] == "outcome_unknown"
    assert (outcome.error or "").startswith("outcome_unknown:")


@async_test
async def test_dry_run_receipt_redacts_signed_asset_and_metadata_url_query_params():
    transport, captured = _mock_transport(lambda _r, _b: httpx.Response(200, json={"data": {}}))
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=transport),
        env_getter=lambda: {"BUFFER_API_KEY": KEY, "BUFFER_DRY_RUN": "true"},
    )
    signed_param = "access_" + "token=topsecret999"
    outcome = await adapter.execute(
        _action(
            target="ch_fb_01",
            payload={
                "service": "facebook",
                "text": f"Preview with signed link https://cdn.example.com/dl?{signed_param}",
                "assets": [{"type": "image", "url": "https://cdn.example.com/media/patio.jpg?X-Amz-Signature=sig12345&sig=abc"}],
                "metadata": {"type": "post", "first_comment": f"Check https://example.com/p?sig=xyz {KEY}"},
            },
        )
    )
    assert outcome.status == "approved"
    assert outcome.detail["state"] == "dry_run"
    assert captured == []
    serialized = json.dumps(outcome.detail)
    assert "sig12345" not in serialized
    assert "topsecret999" not in serialized
    assert "sig=xyz" not in serialized
    assert KEY not in serialized
    assert outcome.detail["graphql_input"]["assets"] == [{"image": {"url": "https://cdn.example.com/media/patio.jpg?[redacted]"}}]


@async_test
async def test_live_receipt_redacts_external_link_credentials_query_and_fragment():
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={"data": {"channels": [{"id": "ch_1", "name": "li", "displayName": "LI", "service": "linkedin", "isQueuePaused": False}]}},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "createPost": {
                        "__typename": "PostActionSuccess",
                        "post": {
                            "id": "post_live_99",
                            "text": "Live post",
                            "status": "scheduled",
                            "dueAt": None,
                            "externalLink": "https://user:pass" + "@social.example.com/posts/99?sig=secret123#frag",
                        },
                    }
                }
            },
        )

    transport, _ = _mock_transport(_handler)
    adapter = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=transport),
        env_getter=_live_env,
    )
    outcome = await adapter.execute(_action(target="ch_1", payload={"service": "linkedin", "text": "Live post"}))
    assert outcome.status == "executed"
    assert outcome.detail["external_link"] == "https://social.example.com/posts/99?[redacted]"
    assert "user:pass" not in json.dumps(outcome.detail)
    assert "secret123" not in json.dumps(outcome.detail)
    assert "#frag" not in json.dumps(outcome.detail)


@async_test
async def test_malformed_url_in_text_or_external_link_never_crashes_receipt_generation():
    # 1) Dry-run post text containing a malformed port URL succeeds and redacts safely.
    t_dry, cap_dry = _mock_transport(lambda _r, _b: httpx.Response(200, json={"data": {}}))
    a_dry = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_dry),
        env_getter=lambda: {"BUFFER_API_KEY": KEY, "BUFFER_DRY_RUN": "true"},
    )
    dry_res = await a_dry.execute(
        _action(
            target="ch_1",
            payload={"service": "linkedin", "text": "Malformed link https://example.com:abc/path?sig=leak999"},
        )
    )
    assert dry_res.status == "approved"
    assert dry_res.detail["state"] == "dry_run"
    assert "leak999" not in json.dumps(dry_res.detail)
    assert "[redacted-url]" in dry_res.detail["graphql_input"]["text"]
    assert cap_dry == []

    # 2) Live createPost returning a malformed externalLink still reports executed (never failed).
    def _bad_link_handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "")
        if "GetOrganizations" in query:
            return httpx.Response(200, json={"data": {"account": {"id": "acc_1", "organizations": [{"id": "org_1", "name": "Org"}]}}})
        if "GetChannels" in query:
            return httpx.Response(
                200,
                json={"data": {"channels": [{"id": "ch_1", "name": "li", "displayName": "LI", "service": "linkedin", "isQueuePaused": False}]}},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "createPost": {
                        "__typename": "PostActionSuccess",
                        "post": {
                            "id": "post_live_malformed",
                            "text": "Live post",
                            "status": "scheduled",
                            "dueAt": None,
                            "externalLink": "https://social.example.com:badport/p?sig=leak888",
                        },
                    }
                }
            },
        )

    t_live, _ = _mock_transport(_bad_link_handler)
    a_live = BufferPublishAdapter(
        client_factory=lambda: BufferGraphQLClient(api_key=KEY, transport=t_live),
        env_getter=_live_env,
    )
    live_res = await a_live.execute(_action(target="ch_1", payload={"service": "linkedin", "text": "Live post"}))
    assert live_res.status == "executed"
    assert live_res.detail["post_id"] == "post_live_malformed"
    assert live_res.detail["external_link"] == "[redacted-url]"
    assert "leak888" not in json.dumps(live_res.detail)
