"""Buffer GraphQL API (2026) client and approval payload contract.

Talks to Buffer's official GraphQL endpoint (``https://api.buffer.com``) with
Bearer token authentication (``BUFFER_API_KEY``). Nothing here runs before a
human approves the pending action in the Approvals inbox.

Safety invariants:
- Fail-closed when ``BUFFER_API_KEY`` is unset or blank (zero network calls).
- Supports dry-run mode (``BUFFER_DRY_RUN=true`` or ``payload.dry_run=True``);
  an operator-set ``BUFFER_DRY_RUN=true`` cannot be disabled by a payload.
- Optional ``BUFFER_ALLOWED_CHANNEL_IDS`` allowlist pins allowed channel IDs.
- API keys and bearer tokens are scrubbed from all errors, receipts, and logs.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from deerflow.approvals.workflow import InvalidPayloadError, register_action_type

ACTION_TYPE = "buffer_post"

DEFAULT_BUFFER_API_URL = "https://api.buffer.com"
DEFAULT_TIMEOUT_SECONDS = 30.0

BUFFER_API_KEY_ENV = "BUFFER_API_KEY"
BUFFER_API_URL_ENV = "BUFFER_API_URL"
BUFFER_DRY_RUN_ENV = "BUFFER_DRY_RUN"
BUFFER_ORGANIZATION_ID_ENV = "BUFFER_ORGANIZATION_ID"
BUFFER_ALLOWED_CHANNEL_IDS_ENV = "BUFFER_ALLOWED_CHANNEL_IDS"
BUFFER_WORKSPACE_CHANNELS_ENV = "BUFFER_WORKSPACE_CHANNELS"
BUFFER_WORKSPACE_ORGANIZATIONS_ENV = "BUFFER_WORKSPACE_ORGANIZATIONS"

TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})

SUPPORTED_SERVICES: dict[str, str] = {
    "googlebusiness": "google",
    "linkedin": "linkedin",
    "facebook": "facebook",
    "instagram": "instagram",
    "twitter": "twitter",
}

SERVICE_ALIASES: dict[str, str] = {
    "gbp": "googlebusiness",
    "google": "googlebusiness",
    "google_business": "googlebusiness",
    "google_business_profile": "googlebusiness",
    "googlebusiness": "googlebusiness",
    "linkedin": "linkedin",
    "facebook": "facebook",
    "fb": "facebook",
    "instagram": "instagram",
    "ig": "instagram",
    "twitter": "twitter",
    "x": "twitter",
}

SHARE_MODES = ("addToQueue", "customScheduled", "shareNow", "shareNext")
INPUT_MODES = ("draft", *SHARE_MODES)
SCHEDULING_TYPES = ("automatic", "notification")
ASSET_TYPES = ("image", "video", "document")
GBP_POST_TYPES = ("post", "offer", "event")
FACEBOOK_POST_TYPES = ("post", "story", "reel")

_CREDENTIAL_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth(?:orization)?|bearer|password|passwd|secret|private[_-]?key|client[_-]?secret|cookie)",
    re.IGNORECASE,
)
_INLINE_SECRET_RE = re.compile(r"(Bearer\s+[\w.~+/=-]{6,}|(?i:(?:api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*)\S+)")

GET_ORGANIZATIONS_QUERY = """
query GetOrganizations {
  account {
    id
    email
    organizations {
      id
      name
    }
  }
}
""".strip()

GET_CHANNELS_QUERY = """
query GetChannels($organizationId: OrganizationId!) {
  channels(input: { organizationId: $organizationId }) {
    id
    name
    displayName
    service
    avatar
    isQueuePaused
  }
}
""".strip()

CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess {
      post {
        id
        text
        status
        dueAt
        externalLink
      }
    }
    ... on MutationError {
      message
    }
  }
}
""".strip()


class BufferError(RuntimeError):
    """Base error for Buffer API operations."""


class BufferNotConfiguredError(BufferError):
    """Raised when BUFFER_API_KEY is unset or blank."""


class BufferAuthError(BufferError):
    """Raised on HTTP 401/403 from Buffer."""


class BufferRateLimitError(BufferError):
    """Raised on HTTP 429 from Buffer."""

    def __init__(self, message: str, *, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BufferAPIError(BufferError):
    """Raised on non-200 HTTP responses or malformed payloads from Buffer."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BufferGraphQLError(BufferError):
    """Raised when Buffer returns top-level GraphQL ``errors``."""

    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class BufferMutationError(BufferError):
    """Raised when ``createPost`` returns a typed ``MutationError`` union member."""

    def __init__(self, message: str, *, error_type: str = "MutationError") -> None:
        super().__init__(message)
        self.error_type = error_type


class BufferNetworkError(BufferError):
    """Raised when Buffer could not be reached before the request was sent."""


class BufferOutcomeUnknownError(BufferError):
    """Raised when a write request timed out or broke after send; reconcile before retrying."""


@dataclass(frozen=True)
class BufferOrganization:
    id: str
    name: str


@dataclass(frozen=True)
class BufferChannel:
    id: str
    name: str
    display_name: str
    service: str
    organization_id: str
    organization_name: str = ""
    avatar: str | None = None
    is_queue_paused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "service": self.service,
            "organization_id": self.organization_id,
            "organization_name": self.organization_name,
            "avatar": self.avatar,
            "is_queue_paused": self.is_queue_paused,
        }


@dataclass(frozen=True)
class BufferPostRequest:
    channel_id: str
    service: str
    text: str
    mode: str
    scheduling_type: str = "automatic"
    save_to_draft: bool = False
    due_at: str | None = None
    assets: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def to_graphql_input(self) -> dict[str, Any]:
        graphql_input: dict[str, Any] = {
            "channelId": self.channel_id,
            "schedulingType": self.scheduling_type,
            "mode": self.mode,
        }
        if self.text:
            graphql_input["text"] = self.text
        if self.save_to_draft:
            graphql_input["saveToDraft"] = True
        if self.due_at:
            graphql_input["dueAt"] = self.due_at
        if self.assets:
            graphql_input["assets"] = list(self.assets)
        if self.metadata:
            graphql_input["metadata"] = self.metadata
        return graphql_input


@dataclass(frozen=True)
class BufferPostResult:
    provider: str
    channel_id: str
    service: str
    mode: str
    scheduling_type: str
    save_to_draft: bool
    dry_run: bool
    status: str
    post_id: str | None = None
    post_status: str | None = None
    due_at: str | None = None
    external_link: str | None = None
    http_status: int | None = None
    elapsed_ms: int = 0
    api_key_configured: bool = False
    graphql_input: dict[str, Any] | None = None
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_receipt(self, *, action_id: str | None = None, secret: str | None = None) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "provider": self.provider,
            "state": self.status,
            "channel_id": self.channel_id,
            "service": self.service,
            "mode": self.mode,
            "scheduling_type": self.scheduling_type,
            "save_to_draft": self.save_to_draft,
            "dry_run": self.dry_run,
            "api_key_configured": self.api_key_configured,
            "post_id": self.post_id,
            "post_status": self.post_status,
            "due_at": self.due_at,
            "external_link": sanitize_receipt_value(self.external_link, secret=secret) if self.external_link is not None else None,
            "http_status": self.http_status,
            "elapsed_ms": self.elapsed_ms,
            "timestamp_utc": self.timestamp_utc,
        }
        if action_id is not None:
            receipt["action_id"] = action_id
        if self.dry_run and self.graphql_input is not None:
            receipt["graphql_input"] = sanitize_receipt_value(self.graphql_input, secret=secret)
        return receipt


_HTTP_URL_INLINE_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def redact_url_credentials(url: str) -> str:
    """Strip query strings, fragments, and embedded userinfo from an HTTP(S) URL for safe receipt storage."""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return url
        host = parsed.hostname or ""
        if not host:
            return "[redacted-url]"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parsed.port
        netloc = f"{host}:{port}" if port is not None else host
        query = "[redacted]" if parsed.query else ""
        return urlunparse((parsed.scheme, netloc, parsed.path, "", query, ""))
    except ValueError:
        return "[redacted-url]"


def sanitize_receipt_value(value: Any, secret: str | None = None) -> Any:
    """Recursively scrub secrets and query-bearing URL credentials before persisting a dry-run receipt."""
    if isinstance(value, str):
        cleaned = _HTTP_URL_INLINE_RE.sub(lambda m: redact_url_credentials(m.group(0)), value)
        return scrub_secret(cleaned, secret)
    if isinstance(value, list):
        return [sanitize_receipt_value(item, secret) for item in value]
    if isinstance(value, tuple):
        return [sanitize_receipt_value(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(k): sanitize_receipt_value(v, secret) for k, v in value.items()}
    return value


def scrub_secret(text: str, secret: str | None = None) -> str:
    """Remove any API key or inline bearer/secret tokens before logging or returning text."""
    cleaned = text
    if secret:
        trimmed = secret.strip()
        if trimmed:
            cleaned = cleaned.replace(trimmed, "[redacted]")
    return _INLINE_SECRET_RE.sub("[redacted]", cleaned)


def env_dry_run_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(BUFFER_DRY_RUN_ENV, "").strip().lower() in TRUTHY_ENV_VALUES


def parse_allowed_channel_ids(env: Mapping[str, str] | None = None) -> frozenset[str] | None:
    source = os.environ if env is None else env
    if BUFFER_ALLOWED_CHANNEL_IDS_ENV not in source:
        return None
    raw = source.get(BUFFER_ALLOWED_CHANNEL_IDS_ENV) or ""
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def parse_workspace_channel_map(env: Mapping[str, str] | None = None) -> dict[str, frozenset[str]] | None:
    """Parse ``BUFFER_WORKSPACE_CHANNELS`` JSON mapping ``{workspace_id: [channel_ids]}``; fail closed if invalid."""
    source = os.environ if env is None else env
    if BUFFER_WORKSPACE_CHANNELS_ENV not in source:
        return None
    raw = (source.get(BUFFER_WORKSPACE_CHANNELS_ENV) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise InvalidPayloadError("BUFFER_WORKSPACE_CHANNELS must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidPayloadError("BUFFER_WORKSPACE_CHANNELS must be a JSON object")
    out: dict[str, frozenset[str]] = {}
    for ws_id, channels in parsed.items():
        ws = str(ws_id or "").strip()
        if not ws or not isinstance(channels, list) or not all(isinstance(c, str) for c in channels):
            raise InvalidPayloadError("BUFFER_WORKSPACE_CHANNELS entries must map workspace IDs to lists of channel IDs")
        out[ws] = frozenset(c.strip() for c in channels if c.strip())
    return out


def parse_workspace_org_map(env: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """Parse ``BUFFER_WORKSPACE_ORGANIZATIONS`` JSON mapping ``{workspace_id: buffer_org_id}``; fail closed if invalid."""
    source = os.environ if env is None else env
    if BUFFER_WORKSPACE_ORGANIZATIONS_ENV not in source:
        return None
    raw = (source.get(BUFFER_WORKSPACE_ORGANIZATIONS_ENV) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise InvalidPayloadError("BUFFER_WORKSPACE_ORGANIZATIONS must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidPayloadError("BUFFER_WORKSPACE_ORGANIZATIONS must be a JSON object")
    out: dict[str, str] = {}
    for ws_id, org_id in parsed.items():
        ws = str(ws_id or "").strip()
        org = str(org_id or "").strip() if isinstance(org_id, str) else ""
        if not ws or not org:
            raise InvalidPayloadError("BUFFER_WORKSPACE_ORGANIZATIONS entries must map workspace IDs to non-empty Buffer org IDs")
        out[ws] = org
    return out


def normalize_service(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidPayloadError("Buffer post requires payload.service (googlebusiness, linkedin, facebook, instagram, or twitter)")
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    canonical = SERVICE_ALIASES.get(key)
    if canonical is None:
        allowed = ", ".join(sorted(SUPPORTED_SERVICES))
        raise InvalidPayloadError(f"Unsupported Buffer service {raw!r}; expected one of: {allowed}")
    return canonical


def _validate_http_url(url: Any, field_name: str, *, allow_loopback_http: bool = False) -> str:
    if not isinstance(url, str) or not url.strip():
        raise InvalidPayloadError(f"{field_name} must be a non-empty HTTP(S) URL")
    trimmed = url.strip()
    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"}:
        raise InvalidPayloadError(f"{field_name} must use http:// or https://")
    if not parsed.netloc or not parsed.hostname:
        raise InvalidPayloadError(f"{field_name} must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidPayloadError(f"{field_name} must not contain embedded credentials")
    if parsed.scheme == "http" and allow_loopback_http and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise InvalidPayloadError(f"{field_name} must use https:// for non-local hosts")
    return trimmed


def _reject_credential_keys(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            if _CREDENTIAL_KEY_RE.search(key_str):
                raise InvalidPayloadError(f"Credential-bearing field {path}.{key_str!r} is not allowed in Buffer post payloads")
            _reject_credential_keys(child, f"{path}.{key_str}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _reject_credential_keys(item, f"{path}[{idx}]")


def _normalize_due_at(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidPayloadError("due_at must be a timezone-aware ISO-8601 timestamp")
    candidate = raw.strip()
    iso_candidate = candidate[:-1] + "+00:00" if candidate.endswith(("Z", "z")) else candidate
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError as exc:
        raise InvalidPayloadError("due_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidPayloadError("due_at must include an explicit timezone offset or trailing 'Z'")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_assets(raw_assets: Any) -> tuple[dict[str, Any], ...]:
    if raw_assets is None:
        return ()
    if not isinstance(raw_assets, list):
        raise InvalidPayloadError("payload.assets must be a list of media objects")
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_assets):
        if not isinstance(item, dict):
            raise InvalidPayloadError(f"payload.assets[{idx}] must be an object")
        # Support either Buffer-native {"image": {"url": ...}} or flat {"type": "image", "url": ...}
        native_keys = [k for k in ASSET_TYPES if k in item]
        if native_keys:
            if len(native_keys) != 1 or len(item) != 1:
                raise InvalidPayloadError(f"payload.assets[{idx}] must specify exactly one of image, video, or document")
            kind = native_keys[0]
            body = item[kind]
            if not isinstance(body, dict):
                raise InvalidPayloadError(f"payload.assets[{idx}].{kind} must be an object")
            url = _validate_http_url(body.get("url"), f"payload.assets[{idx}].{kind}.url")
            entry: dict[str, Any] = {"url": url}
            if "metadata" in body and body["metadata"] is not None:
                if not isinstance(body["metadata"], dict):
                    raise InvalidPayloadError(f"payload.assets[{idx}].{kind}.metadata must be an object")
                entry["metadata"] = body["metadata"]
            normalized.append({kind: entry})
            continue
        kind = str(item.get("type") or "").strip().lower()
        if kind not in ASSET_TYPES:
            raise InvalidPayloadError(f"payload.assets[{idx}].type must be one of: image, video, document")
        url = _validate_http_url(item.get("url"), f"payload.assets[{idx}].url")
        entry = {"url": url}
        if "metadata" in item and item["metadata"] is not None:
            if not isinstance(item["metadata"], dict):
                raise InvalidPayloadError(f"payload.assets[{idx}].metadata must be an object")
            entry["metadata"] = item["metadata"]
        normalized.append({kind: entry})
    return tuple(normalized)


_SERVICE_METADATA_FIELDS: dict[str, frozenset[str]] = {
    "googlebusiness": frozenset(
        {
            "type",
            "post_type",
            "title",
            "detailsWhatsNew",
            "details_whats_new",
            "cta_button",
            "button",
            "cta_link",
            "link",
            "detailsOffer",
            "details_offer",
            "detailsEvent",
            "details_event",
        }
    ),
    "linkedin": frozenset({"firstComment", "first_comment", "linkAttachment", "link_attachment", "annotations"}),
    "facebook": frozenset({"type", "post_type", "firstComment", "first_comment", "linkAttachment", "link_attachment", "annotations"}),
    "instagram": frozenset({"shouldShareToFeed", "should_share_to_feed", "firstComment", "first_comment", "link", "geolocation", "isAiGenerated", "is_ai_generated"}),
    "twitter": frozenset({"url", "link", "thread", "replyToId", "reply_to_id"}),
}


def _normalize_service_metadata(service: str, raw_meta: Any, *, has_assets: bool) -> dict[str, Any]:
    if raw_meta is None:
        return {}
    if not isinstance(raw_meta, dict):
        raise InvalidPayloadError("payload.metadata must be an object")
    if not raw_meta:
        return {}
    meta_key = SUPPORTED_SERVICES[service]
    # Accept either {"google": {...}} / {"linkedin": {...}} or flat platform fields — never mixed.
    service_keys = set(SUPPORTED_SERVICES.values())
    present_service_keys = set(raw_meta) & service_keys
    unknown_top = set(raw_meta) - service_keys
    if present_service_keys:
        if unknown_top:
            raise InvalidPayloadError(
                f"payload.metadata cannot mix service blocks with flat top-level fields: {', '.join(sorted(unknown_top))}"
            )
        if meta_key not in raw_meta:
            raise InvalidPayloadError(f"payload.metadata does not match service {service!r} (expected {meta_key!r})")
        section = raw_meta[meta_key]
        if not isinstance(section, dict):
            raise InvalidPayloadError(f"payload.metadata.{meta_key} must be an object")
        other_keys = [k for k in raw_meta if k != meta_key and raw_meta[k] is not None]
        if other_keys:
            raise InvalidPayloadError(f"payload.metadata contains unrelated service blocks: {', '.join(sorted(other_keys))}")
    else:
        section = raw_meta

    allowed_fields = _SERVICE_METADATA_FIELDS[service]
    unsupported_fields = [k for k in section if k not in allowed_fields]
    if unsupported_fields:
        raise InvalidPayloadError(f"Unsupported {service} metadata fields: {', '.join(sorted(unsupported_fields))}")

    cleaned: dict[str, Any] = {}
    if service == "googlebusiness":
        if section.get("type") is not None and section.get("post_type") is not None:
            raise InvalidPayloadError("Google Business Profile metadata cannot specify both type and post_type")
        post_type = str(section.get("type") or section.get("post_type") or "post").strip().lower()
        if post_type not in GBP_POST_TYPES:
            raise InvalidPayloadError(f"Google Business Profile post type must be one of: {', '.join(GBP_POST_TYPES)}")
        cleaned["type"] = post_type
        title = section.get("title")
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise InvalidPayloadError("Google Business Profile metadata.title must be a non-empty string")
            cleaned["title"] = title.strip()
        if section.get("detailsWhatsNew") is not None and section.get("details_whats_new") is not None:
            raise InvalidPayloadError("Google Business Profile metadata cannot specify both detailsWhatsNew and details_whats_new")
        if section.get("cta_button") is not None and section.get("button") is not None:
            raise InvalidPayloadError("Google Business Profile metadata cannot specify both cta_button and button")
        if section.get("cta_link") is not None and section.get("link") is not None:
            raise InvalidPayloadError("Google Business Profile metadata cannot specify both cta_link and link")
        whats_new = section.get("detailsWhatsNew") if section.get("detailsWhatsNew") is not None else section.get("details_whats_new")
        cta_button = section.get("cta_button") if section.get("cta_button") is not None else section.get("button")
        cta_link = section.get("cta_link") if section.get("cta_link") is not None else section.get("link")
        if whats_new is not None and (cta_button is not None or cta_link is not None):
            raise InvalidPayloadError(
                "Google Business Profile metadata cannot combine detailsWhatsNew with flat cta_button/button/cta_link/link fields"
            )
        if whats_new is not None:
            if not isinstance(whats_new, dict):
                raise InvalidPayloadError("Google Business Profile detailsWhatsNew must be an object")
            wn_clean = dict(whats_new)
            if "link" in wn_clean and wn_clean["link"] is not None:
                wn_clean["link"] = _validate_http_url(wn_clean["link"], "metadata.google.detailsWhatsNew.link")
            cleaned["detailsWhatsNew"] = wn_clean
        elif cta_button is not None or cta_link is not None:
            wn_clean = {}
            if cta_button is not None:
                if not isinstance(cta_button, str) or not cta_button.strip():
                    raise InvalidPayloadError("Google Business Profile CTA button must be a non-empty string")
                wn_clean["button"] = cta_button.strip()
            if cta_link is not None:
                wn_clean["link"] = _validate_http_url(cta_link, "metadata.google.cta_link")
            cleaned["detailsWhatsNew"] = wn_clean
        for detail_key, alt_key in (("detailsOffer", "details_offer"), ("detailsEvent", "details_event")):
            if section.get(detail_key) is not None and section.get(alt_key) is not None:
                raise InvalidPayloadError(f"Google Business Profile metadata cannot specify both {detail_key} and {alt_key}")
            detail_val = section.get(detail_key) if section.get(detail_key) is not None else section.get(alt_key)
            if detail_val is not None:
                if not isinstance(detail_val, dict):
                    raise InvalidPayloadError(f"Google Business Profile {detail_key} must be an object")
                detail_clean = dict(detail_val)
                for url_field in ("link", "redeemOnlineUrl"):
                    if url_field in detail_clean and detail_clean[url_field] is not None:
                        detail_clean[url_field] = _validate_http_url(detail_clean[url_field], f"metadata.google.{detail_key}.{url_field}")
                cleaned[detail_key] = detail_clean

    elif service == "linkedin":
        if section.get("firstComment") is not None and section.get("first_comment") is not None:
            raise InvalidPayloadError("LinkedIn metadata cannot specify both firstComment and first_comment")
        first_comment = section.get("firstComment") if section.get("firstComment") is not None else section.get("first_comment")
        if first_comment is not None:
            if not isinstance(first_comment, str) or not first_comment.strip():
                raise InvalidPayloadError("LinkedIn firstComment must be a non-empty string")
            cleaned["firstComment"] = first_comment.strip()
        if section.get("linkAttachment") is not None and section.get("link_attachment") is not None:
            raise InvalidPayloadError("LinkedIn metadata cannot specify both linkAttachment and link_attachment")
        link_attachment = section.get("linkAttachment") if section.get("linkAttachment") is not None else section.get("link_attachment")
        if link_attachment is not None:
            if has_assets:
                raise InvalidPayloadError("LinkedIn linkAttachment cannot be combined with non-empty assets")
            if not isinstance(link_attachment, dict):
                raise InvalidPayloadError("LinkedIn linkAttachment must be an object")
            la_clean = dict(link_attachment)
            if "url" in la_clean and la_clean["url"] is not None:
                la_clean["url"] = _validate_http_url(la_clean["url"], "metadata.linkedin.linkAttachment.url")
            cleaned["linkAttachment"] = la_clean
        if "annotations" in section and section["annotations"] is not None:
            if not isinstance(section["annotations"], list):
                raise InvalidPayloadError("LinkedIn annotations must be a list")
            cleaned["annotations"] = section["annotations"]

    elif service == "facebook":
        if section.get("type") is not None and section.get("post_type") is not None:
            raise InvalidPayloadError("Facebook metadata cannot specify both type and post_type")
        post_type = section.get("type") if section.get("type") is not None else section.get("post_type")
        if post_type is not None:
            normalized_fb_type = str(post_type).strip().lower()
            if normalized_fb_type not in FACEBOOK_POST_TYPES:
                raise InvalidPayloadError(f"Facebook post type must be one of: {', '.join(FACEBOOK_POST_TYPES)}")
            cleaned["type"] = normalized_fb_type
        if section.get("firstComment") is not None and section.get("first_comment") is not None:
            raise InvalidPayloadError("Facebook metadata cannot specify both firstComment and first_comment")
        first_comment = section.get("firstComment") if section.get("firstComment") is not None else section.get("first_comment")
        if first_comment is not None:
            if not isinstance(first_comment, str) or not first_comment.strip():
                raise InvalidPayloadError("Facebook firstComment must be a non-empty string")
            cleaned["firstComment"] = first_comment.strip()
        if section.get("linkAttachment") is not None and section.get("link_attachment") is not None:
            raise InvalidPayloadError("Facebook metadata cannot specify both linkAttachment and link_attachment")
        link_attachment = section.get("linkAttachment") if section.get("linkAttachment") is not None else section.get("link_attachment")
        if link_attachment is not None:
            if has_assets:
                raise InvalidPayloadError("Facebook linkAttachment cannot be combined with non-empty assets")
            if not isinstance(link_attachment, dict):
                raise InvalidPayloadError("Facebook linkAttachment must be an object")
            la_clean = dict(link_attachment)
            if "url" in la_clean and la_clean["url"] is not None:
                la_clean["url"] = _validate_http_url(la_clean["url"], "metadata.facebook.linkAttachment.url")
            cleaned["linkAttachment"] = la_clean
        if "annotations" in section and section["annotations"] is not None:
            if not isinstance(section["annotations"], list):
                raise InvalidPayloadError("Facebook annotations must be a list")
            cleaned["annotations"] = section["annotations"]

    elif service == "instagram":
        if section.get("shouldShareToFeed") is not None and section.get("should_share_to_feed") is not None:
            raise InvalidPayloadError("Instagram metadata cannot specify both shouldShareToFeed and should_share_to_feed")
        share_to_feed = section.get("shouldShareToFeed") if section.get("shouldShareToFeed") is not None else section.get("should_share_to_feed")
        if share_to_feed is not None:
            if not isinstance(share_to_feed, bool):
                raise InvalidPayloadError("Instagram shouldShareToFeed must be a boolean")
            cleaned["shouldShareToFeed"] = share_to_feed
        if section.get("firstComment") is not None and section.get("first_comment") is not None:
            raise InvalidPayloadError("Instagram metadata cannot specify both firstComment and first_comment")
        first_comment = section.get("firstComment") if section.get("firstComment") is not None else section.get("first_comment")
        if first_comment is not None:
            if not isinstance(first_comment, str) or not first_comment.strip():
                raise InvalidPayloadError("Instagram firstComment must be a non-empty string")
            cleaned["firstComment"] = first_comment.strip()
        if "link" in section and section["link"] is not None:
            cleaned["link"] = _validate_http_url(section["link"], "metadata.instagram.link")
        if "geolocation" in section and section["geolocation"] is not None:
            if not isinstance(section["geolocation"], dict):
                raise InvalidPayloadError("Instagram geolocation must be an object")
            cleaned["geolocation"] = dict(section["geolocation"])
        if section.get("isAiGenerated") is not None and section.get("is_ai_generated") is not None:
            raise InvalidPayloadError("Instagram metadata cannot specify both isAiGenerated and is_ai_generated")
        ai_flag = section.get("isAiGenerated") if section.get("isAiGenerated") is not None else section.get("is_ai_generated")
        if ai_flag is not None:
            if not isinstance(ai_flag, bool):
                raise InvalidPayloadError("Instagram isAiGenerated must be a boolean")
            cleaned["isAiGenerated"] = ai_flag

    elif service == "twitter":
        for key, value in section.items():
            if value is None:
                continue
            if key in {"url", "link"}:
                cleaned[key] = _validate_http_url(value, f"metadata.twitter.{key}")
            else:
                cleaned[key] = value

    return {meta_key: cleaned} if cleaned else {}


def build_post_request(target: str, payload: Any) -> BufferPostRequest:
    """Validate and normalize an approved ``buffer_post`` action into a ``BufferPostRequest``."""
    if not isinstance(payload, dict):
        raise InvalidPayloadError("Buffer post payload must be an object")
    _reject_credential_keys(payload)

    target_id = target.strip() if isinstance(target, str) else ""
    payload_channel_raw = payload.get("channel_id") if "channel_id" in payload else payload.get("channelId")
    payload_channel = payload_channel_raw.strip() if isinstance(payload_channel_raw, str) else ""
    if payload_channel_raw is not None and not isinstance(payload_channel_raw, str):
        raise InvalidPayloadError("payload.channel_id must be a string")
    if target_id and payload_channel and target_id != payload_channel:
        raise InvalidPayloadError("target and payload.channel_id must match")
    channel_id = target_id or payload_channel
    if not channel_id:
        raise InvalidPayloadError("Buffer post requires a non-empty target channel_id")

    service = normalize_service(payload.get("service"))

    raw_text = payload.get("text", "")
    if raw_text is None:
        raw_text = ""
    if not isinstance(raw_text, str):
        raise InvalidPayloadError("payload.text must be a string")
    text = raw_text.strip()

    assets = _normalize_assets(payload.get("assets"))
    if not text and not assets:
        raise InvalidPayloadError("Buffer post requires non-empty payload.text or at least one asset")
    if service == "instagram":
        has_visual = any("image" in asset or "video" in asset for asset in assets)
        if not has_visual:
            raise InvalidPayloadError("Instagram posts require at least one image or video asset")

    raw_save_to_draft = payload.get("save_to_draft") if "save_to_draft" in payload else payload.get("saveToDraft")
    if raw_save_to_draft is not None and not isinstance(raw_save_to_draft, bool):
        raise InvalidPayloadError("payload.save_to_draft must be a boolean")

    raw_mode = payload.get("mode")
    if raw_mode is None:
        input_mode = "draft" if raw_save_to_draft is not False else "addToQueue"
    elif isinstance(raw_mode, str) and raw_mode.strip() in INPUT_MODES:
        input_mode = raw_mode.strip()
    else:
        raise InvalidPayloadError(f"payload.mode must be one of: {', '.join(INPUT_MODES)}")

    raw_due_at = payload.get("due_at") if "due_at" in payload else payload.get("dueAt")
    due_at = _normalize_due_at(raw_due_at) if raw_due_at is not None else None

    if input_mode == "draft":
        if raw_save_to_draft is False:
            raise InvalidPayloadError("payload.mode='draft' conflicts with save_to_draft=false")
        save_to_draft = True
        graphql_mode = "customScheduled" if due_at is not None else "addToQueue"
    else:
        save_to_draft = bool(raw_save_to_draft)
        graphql_mode = input_mode
        if save_to_draft and graphql_mode == "shareNow":
            raise InvalidPayloadError("payload.mode='shareNow' conflicts with save_to_draft=true")

    if graphql_mode == "customScheduled" and due_at is None:
        raise InvalidPayloadError("payload.mode='customScheduled' requires payload.due_at (ISO-8601 UTC timestamp)")
    if graphql_mode != "customScheduled" and due_at is not None:
        raise InvalidPayloadError("payload.due_at is only valid with mode='customScheduled' (or mode='draft')")

    raw_sched = payload.get("scheduling_type") if "scheduling_type" in payload else payload.get("schedulingType", "automatic")
    if not isinstance(raw_sched, str) or raw_sched.strip() not in SCHEDULING_TYPES:
        raise InvalidPayloadError(f"payload.scheduling_type must be one of: {', '.join(SCHEDULING_TYPES)}")
    scheduling_type = raw_sched.strip()

    raw_dry_run = payload.get("dry_run", False)
    if not isinstance(raw_dry_run, bool):
        raise InvalidPayloadError("payload.dry_run must be a boolean")

    metadata = _normalize_service_metadata(service, payload.get("metadata"), has_assets=bool(assets))

    return BufferPostRequest(
        channel_id=channel_id,
        service=service,
        text=text,
        mode=graphql_mode,
        scheduling_type=scheduling_type,
        save_to_draft=save_to_draft,
        due_at=due_at,
        assets=assets,
        metadata=metadata,
        dry_run=raw_dry_run,
    )


def validate_buffer_post_payload(target: str, payload: dict[str, Any]) -> None:
    """Approvals inbox validator registered for action type ``buffer_post``."""
    build_post_request(target, payload)


register_action_type(ACTION_TYPE, validate_buffer_post_payload)


class BufferGraphQLClient:
    """Async client for Buffer's official GraphQL API (``https://api.buffer.com``)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        source = os.environ if env is None else env
        raw_key = source.get(BUFFER_API_KEY_ENV, "") if api_key is None else api_key
        self._key = raw_key.strip() if isinstance(raw_key, str) else ""
        raw_url = source.get(BUFFER_API_URL_ENV, DEFAULT_BUFFER_API_URL) if api_url is None else api_url
        self._api_url = _validate_http_url(raw_url or DEFAULT_BUFFER_API_URL, BUFFER_API_URL_ENV, allow_loopback_http=True)
        self._timeout = timeout
        self._transport = transport
        self._default_org_id = (source.get(BUFFER_ORGANIZATION_ID_ENV) or "").strip() or None

    @property
    def is_configured(self) -> bool:
        return bool(self._key)

    @property
    def api_url(self) -> str:
        return self._api_url

    def _require_key(self) -> str:
        if not self._key:
            raise BufferNotConfiguredError("BUFFER_API_KEY is not configured; refusing to call Buffer API")
        return self._key

    async def _post_graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        is_mutation: bool = False,
    ) -> tuple[dict[str, Any], int, int]:
        buf_key = self._require_key()
        headers = {
            "Authorization": f"Bearer {buf_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body: dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(self._api_url, json=body, headers=headers)
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            raise BufferNetworkError(f"Could not connect to Buffer API: {type(exc).__name__}") from exc
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
            if is_mutation:
                raise BufferOutcomeUnknownError(f"Buffer request did not confirm receipt after send ({type(exc).__name__})") from exc
            raise BufferNetworkError(f"Buffer request failed: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            if is_mutation:
                raise BufferOutcomeUnknownError(f"Buffer transport error during mutation ({type(exc).__name__})") from exc
            raise BufferNetworkError(f"Buffer transport error: {type(exc).__name__}") from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)

        if response.status_code in {401, 403}:
            raise BufferAuthError(f"Buffer API rejected credentials (HTTP {response.status_code})")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            suffix = f"; retry after {retry_after}s" if retry_after else ""
            raise BufferRateLimitError(f"Buffer API rate limit reached (HTTP 429{suffix})", retry_after=retry_after)
        if response.status_code >= 500 and is_mutation:
            raise BufferOutcomeUnknownError(
                scrub_secret(
                    f"Buffer API returned HTTP {response.status_code} after mutation; check Buffer before retrying",
                    buf_key,
                )
            )
        if response.status_code >= 400:
            raise BufferAPIError(
                scrub_secret(f"Buffer API returned HTTP {response.status_code}", buf_key),
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            if is_mutation:
                raise BufferOutcomeUnknownError("Buffer returned non-JSON response after mutation; check Buffer before retrying") from exc
            raise BufferAPIError("Buffer API returned invalid JSON", status_code=response.status_code) from exc

        if not isinstance(payload, dict):
            if is_mutation:
                raise BufferOutcomeUnknownError("Buffer returned unexpected non-object response after mutation; check Buffer before retrying")
            raise BufferAPIError("Buffer API returned unexpected response shape", status_code=response.status_code)

        errors = payload.get("errors")
        data = payload.get("data")
        if isinstance(errors, list) and errors:
            messages = [scrub_secret(str(err.get("message") or err), buf_key) for err in errors if isinstance(err, dict)]
            summary = "; ".join(m for m in messages if m) or "GraphQL error"
            if is_mutation and "data" in payload:
                raise BufferOutcomeUnknownError(f"Buffer returned GraphQL errors with response data after mutation ({summary})")
            raise BufferGraphQLError(summary, errors=errors)

        if not isinstance(data, dict):
            if is_mutation:
                raise BufferOutcomeUnknownError("Buffer response missing data payload after mutation; check Buffer before retrying")
            raise BufferAPIError("Buffer API response missing data payload", status_code=response.status_code)
        return data, response.status_code, elapsed_ms

    async def list_organizations(self) -> list[BufferOrganization]:
        data, _, _ = await self._post_graphql(GET_ORGANIZATIONS_QUERY)
        account = data.get("account")
        if not isinstance(account, dict):
            raise BufferAPIError("Buffer GetOrganizations response missing account")
        raw_orgs = account.get("organizations")
        if not isinstance(raw_orgs, list):
            raise BufferAPIError("Buffer GetOrganizations response missing organizations")
        orgs: list[BufferOrganization] = []
        for entry in raw_orgs:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            orgs.append(BufferOrganization(id=str(entry["id"]), name=str(entry.get("name") or "")))
        return orgs

    async def list_channels(
        self,
        organization_id: str | None = None,
        *,
        services: Iterable[str] | None = None,
    ) -> list[BufferChannel]:
        allowed_services = {normalize_service(svc) for svc in services} if services is not None else None
        org_id = (organization_id or self._default_org_id or "").strip() or None
        if org_id is not None:
            orgs = [BufferOrganization(id=org_id, name="")]
        else:
            orgs = await self.list_organizations()

        channels: list[BufferChannel] = []
        for org in orgs:
            data, _, _ = await self._post_graphql(GET_CHANNELS_QUERY, {"organizationId": org.id})
            raw_channels = data.get("channels")
            if not isinstance(raw_channels, list):
                raise BufferAPIError(f"Buffer GetChannels response missing channels for organization {org.id!r}")
            for entry in raw_channels:
                if not isinstance(entry, dict) or not entry.get("id"):
                    continue
                raw_service = str(entry.get("service") or "").strip().lower()
                canonical_service = SERVICE_ALIASES.get(raw_service, raw_service)
                if allowed_services is not None and canonical_service not in allowed_services:
                    continue
                channels.append(
                    BufferChannel(
                        id=str(entry["id"]),
                        name=str(entry.get("name") or ""),
                        display_name=str(entry.get("displayName") or entry.get("name") or ""),
                        service=canonical_service,
                        organization_id=org.id,
                        organization_name=org.name,
                        avatar=str(entry["avatar"]) if entry.get("avatar") else None,
                        is_queue_paused=bool(entry.get("isQueuePaused", False)),
                    )
                )
        return channels

    async def create_post(
        self,
        request: BufferPostRequest,
        *,
        dry_run: bool = False,
        organization_id: str | None = None,
    ) -> BufferPostResult:
        graphql_input = request.to_graphql_input()
        if dry_run or request.dry_run:
            return BufferPostResult(
                provider="buffer",
                channel_id=request.channel_id,
                service=request.service,
                mode=request.mode,
                scheduling_type=request.scheduling_type,
                save_to_draft=request.save_to_draft,
                dry_run=True,
                status="dry_run",
                due_at=request.due_at,
                api_key_configured=self.is_configured,
                graphql_input=graphql_input,
            )

        pinned_org_id = (organization_id or self._default_org_id or "").strip() or None
        if pinned_org_id is None:
            orgs = await self.list_organizations()
            if len(orgs) == 0:
                raise BufferMutationError("No Buffer organizations accessible on this account", error_type="OrganizationNotFound")
            if len(orgs) > 1:
                raise BufferMutationError(
                    "Multiple Buffer organizations are accessible; explicit organization_id binding is required before publishing",
                    error_type="OrganizationBindingRequired",
                )
            pinned_org_id = orgs[0].id

        channels = await self.list_channels(organization_id=pinned_org_id)
        matched_channel = next((ch for ch in channels if ch.id == request.channel_id), None)
        if matched_channel is None:
            raise BufferMutationError(
                f"Buffer channel {request.channel_id!r} was not found in bound Buffer organization {pinned_org_id!r}",
                error_type="ChannelNotFound",
            )
        if matched_channel.service != request.service:
            raise BufferMutationError(
                f"Buffer channel {request.channel_id!r} belongs to service {matched_channel.service!r}, "
                f"not approved service {request.service!r}",
                error_type="ChannelServiceMismatch",
            )

        data, http_status, elapsed_ms = await self._post_graphql(
            CREATE_POST_MUTATION,
            {"input": graphql_input},
            is_mutation=True,
        )
        result = data.get("createPost")
        if not isinstance(result, dict):
            raise BufferOutcomeUnknownError(
                "Buffer createPost response missing createPost payload after mutation; check Buffer before retrying"
            )

        typename = str(result.get("__typename") or "")
        post = result.get("post")
        if typename == "PostActionSuccess" or (not typename and isinstance(post, dict) and post.get("id")):
            if not isinstance(post, dict) or not post.get("id"):
                raise BufferOutcomeUnknownError(
                    "Buffer PostActionSuccess response missing post.id after mutation; check Buffer before retrying"
                )
            raw_post_status = str(post.get("status") or "").strip().lower()
            resolved_post_status = raw_post_status or ("draft" if request.save_to_draft else "scheduled")
            if request.save_to_draft or resolved_post_status == "draft":
                receipt_state = "draft_saved"
            elif raw_post_status in {"sent", "published"}:
                receipt_state = "published"
            elif resolved_post_status in {"scheduled", "buffer", "queued"}:
                receipt_state = "scheduled"
            else:
                receipt_state = "created_in_buffer"
            return BufferPostResult(
                provider="buffer",
                channel_id=request.channel_id,
                service=request.service,
                mode=request.mode,
                scheduling_type=request.scheduling_type,
                save_to_draft=request.save_to_draft,
                dry_run=False,
                status=receipt_state,
                post_id=str(post["id"]),
                post_status=resolved_post_status,
                due_at=str(post["dueAt"]) if post.get("dueAt") else request.due_at,
                external_link=str(post["externalLink"]) if post.get("externalLink") else None,
                http_status=http_status,
                elapsed_ms=elapsed_ms,
                api_key_configured=True,
            )

        if typename.endswith("Error") and post is None:
            message = scrub_secret(str(result.get("message") or "Buffer rejected createPost request"), self._key)
            raise BufferMutationError(message, error_type=typename)

        raise BufferOutcomeUnknownError(
            scrub_secret(
                f"Buffer returned ambiguous createPost response (__typename={typename or 'missing'}); check Buffer before retrying",
                self._key,
            )
        )
