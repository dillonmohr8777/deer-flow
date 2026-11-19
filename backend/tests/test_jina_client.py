"""Tests for JinaClient async crawl method."""

import logging
from unittest.mock import MagicMock

import httpx
import pytest

import deerflow.community.jina_ai.jina_client as jina_client_module
from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.community.jina_ai.tools import (
    _coerce_bool,
    _coerce_proxy,
    _coerce_timeout,
    web_fetch_tool,
)


@pytest.fixture
def jina_client():
    return JinaClient()


@pytest.mark.anyio
async def test_crawl_success(jina_client, monkeypatch):
    """Test successful crawl returns response text."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="<html><body>Hello</body></html>", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result == "<html><body>Hello</body></html>"


@pytest.mark.anyio
async def test_crawl_non_200_status(jina_client, monkeypatch):
    """Test that non-200 status returns error message."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(429, text="Rate limited", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "429" in result


@pytest.mark.anyio
async def test_crawl_empty_response(jina_client, monkeypatch):
    """Test that empty response returns error message."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "empty" in result.lower()


@pytest.mark.anyio
async def test_crawl_whitespace_only_response(jina_client, monkeypatch):
    """Test that whitespace-only response returns error message."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="   \n  ", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "empty" in result.lower()


@pytest.mark.anyio
async def test_crawl_network_error(jina_client, monkeypatch):
    """Test that network errors are handled gracefully."""

    async def mock_post(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "failed" in result.lower()


@pytest.mark.anyio
async def test_crawl_transient_failure_logs_without_traceback(jina_client, monkeypatch, caplog):
    """Transient network failures must log at WARNING without a traceback and include the exception type."""

    # Keep the missing-key warning independent of test order and shard placement.
    monkeypatch.setenv("JINA_API_KEY", "test-key")

    async def mock_post(self, url, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with caplog.at_level(logging.DEBUG, logger="deerflow.community.jina_ai.jina_client"):
        result = await jina_client.crawl("https://example.com")

    jina_records = [r for r in caplog.records if r.name == "deerflow.community.jina_ai.jina_client"]
    assert len(jina_records) == 1, f"expected exactly one log record, got {len(jina_records)}"
    record = jina_records[0]
    assert record.levelno == logging.WARNING, f"expected WARNING, got {record.levelname}"
    assert record.exc_info is None, "transient failures must not attach a traceback"
    assert "ConnectTimeout" in record.getMessage()
    assert result.startswith("Error:")
    assert "ConnectTimeout" in result


@pytest.mark.anyio
async def test_crawl_passes_headers(jina_client, monkeypatch):
    """Test that correct headers are sent."""
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    await jina_client.crawl("https://example.com", return_format="markdown", timeout=30)
    assert captured_headers["X-Return-Format"] == "markdown"
    assert captured_headers["X-Timeout"] == "30"


@pytest.mark.anyio
async def test_crawl_passes_proxy_to_httpx_client(jina_client, monkeypatch):
    """Explicit proxy config should be passed to httpx.AsyncClient."""
    captured_client_kwargs = {}

    class MockAsyncClient:
        def __init__(self, **kwargs):
            captured_client_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await jina_client.crawl("https://example.com", proxy="http://127.0.0.1:7890")

    assert result == "ok"
    assert captured_client_kwargs["proxy"] == "http://127.0.0.1:7890"
    assert captured_client_kwargs["trust_env"] is True


@pytest.mark.anyio
async def test_crawl_can_disable_trust_env(jina_client, monkeypatch):
    """Callers can disable environment proxy lookup for deterministic networking."""
    captured_client_kwargs = {}

    class MockAsyncClient:
        def __init__(self, **kwargs):
            captured_client_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await jina_client.crawl("https://example.com", trust_env=False)

    assert result == "ok"
    assert captured_client_kwargs == {"trust_env": False}


@pytest.mark.anyio
async def test_crawl_includes_api_key_when_set(jina_client, monkeypatch):
    """Test that Authorization header is set when JINA_API_KEY is available."""
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setenv("JINA_API_KEY", "test-key-123")
    await jina_client.crawl("https://example.com")
    assert captured_headers["Authorization"] == "Bearer test-key-123"


@pytest.mark.anyio
async def test_crawl_warns_once_when_api_key_missing(jina_client, monkeypatch, caplog):
    """Test that the missing API key warning is logged only once."""
    jina_client_module._api_key_warned = False

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("JINA_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.jina_ai.jina_client"):
        await jina_client.crawl("https://example.com")
        await jina_client.crawl("https://example.com")

    warning_count = sum(1 for record in caplog.records if "Jina API key is not set" in record.message)
    assert warning_count == 1


@pytest.mark.anyio
async def test_crawl_no_auth_header_without_api_key(jina_client, monkeypatch):
    """Test that no Authorization header is set when JINA_API_KEY is not available."""
    jina_client_module._api_key_warned = False
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    await jina_client.crawl("https://example.com")
    assert "Authorization" not in captured_headers


@pytest.mark.anyio
async def test_web_fetch_tool_returns_error_on_crawl_failure(monkeypatch):
    """Test that web_fetch_tool short-circuits and returns the error string when crawl fails."""

    async def mock_crawl(self, url, **kwargs):
        return "Error: Jina API returned status 429: Rate limited"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert result.startswith("Error:")
    assert "429" in result


@pytest.mark.anyio
async def test_web_fetch_tool_returns_markdown_on_success(monkeypatch):
    """Test that web_fetch_tool returns extracted markdown on successful crawl."""

    async def mock_crawl(self, url, **kwargs):
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert "Hello world" in result
    assert not result.startswith("Error:")


@pytest.mark.anyio
async def test_web_fetch_tool_forwards_proxy_and_trust_env(monkeypatch):
    """web_fetch tool config should be forwarded to JinaClient.crawl."""
    captured_crawl_kwargs = {}

    async def mock_crawl(self, url, **kwargs):
        captured_crawl_kwargs.update(kwargs)
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_tool_config = MagicMock()
    mock_tool_config.model_extra = {
        "timeout": "20",
        "proxy": "http://host.docker.internal:7890",
        "trust_env": "false",
    }
    mock_config.get_tool_config.return_value = mock_tool_config
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    result = await web_fetch_tool.ainvoke("https://example.com")

    assert "Hello world" in result
    assert captured_crawl_kwargs == {
        "return_format": "html",
        "timeout": 20,
        "proxy": "http://host.docker.internal:7890",
        "trust_env": False,
    }


@pytest.mark.anyio
async def test_web_fetch_tool_ignores_empty_proxy(monkeypatch):
    """Empty proxy values from unresolved env vars should not be passed to httpx."""
    captured_crawl_kwargs = {}

    async def mock_crawl(self, url, **kwargs):
        captured_crawl_kwargs.update(kwargs)
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_tool_config = MagicMock()
    mock_tool_config.model_extra = {"proxy": "   ", "trust_env": True}
    mock_config.get_tool_config.return_value = mock_tool_config
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    result = await web_fetch_tool.ainvoke("https://example.com")

    assert "Hello world" in result
    assert captured_crawl_kwargs["proxy"] is None
    assert captured_crawl_kwargs["trust_env"] is True


@pytest.mark.anyio
async def test_web_fetch_tool_offloads_extraction_to_thread(monkeypatch):
    """Test that readability extraction is offloaded via asyncio.to_thread to avoid blocking the event loop."""
    import asyncio

    async def mock_crawl(self, url, **kwargs):
        return "<html><body><p>threaded</p></body></html>"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    to_thread_called = False
    original_to_thread = asyncio.to_thread

    async def tracking_to_thread(func, *args, **kwargs):
        nonlocal to_thread_called
        to_thread_called = True
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr("deerflow.community.jina_ai.tools.asyncio.to_thread", tracking_to_thread)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert to_thread_called, "extract_article must be called via asyncio.to_thread to avoid blocking the event loop"
    assert "threaded" in result


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (True, False, True),
        (False, True, False),
        ("true", False, True),
        ("YES", False, True),
        (" on ", False, True),
        ("1", False, True),
        ("false", True, False),
        ("No", True, False),
        ("off", True, False),
        ("0", True, False),
        ("maybe", True, True),
        ("maybe", False, False),
        (None, True, True),
        (123, False, False),
    ],
)
def test_coerce_bool(value, default, expected):
    """_coerce_bool normalizes booleans, known strings, and falls back to the default."""
    assert _coerce_bool(value, default) is expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (30, 10, 30),
        ("45", 10, 45),
        ("not-a-number", 10, 10),
        (True, 10, 10),
        (False, 10, 10),
        (None, 10, 10),
        (1.5, 10, 10),
    ],
)
def test_coerce_timeout(value, default, expected):
    """_coerce_timeout accepts ints and numeric strings, rejecting bools and junk."""
    assert _coerce_timeout(value, default) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
        ("  http://proxy:8080  ", "http://proxy:8080"),
        ("", None),
        ("   ", None),
        (None, None),
        (123, None),
    ],
)
def test_coerce_proxy(value, expected):
    """_coerce_proxy trims strings and treats empty/non-string values as None."""
    assert _coerce_proxy(value) == expected


# --- Direct fetch of public Google Sheets CSV links ---------------------------------

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz_0123456789-abcd"
GVIZ_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Communities&tq=select%20*"
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
CSV_BODY = "name,city\nAcme,Austin\n"


class _SheetsHarness:
    """Records the direct GETs and the Jina crawls made by one web_fetch_tool call."""

    def __init__(self, monkeypatch, responder):
        self.get_urls: list[str] = []
        self.get_kwargs: list[dict] = []
        self.client_kwargs: list[dict] = []
        self.jina_urls: list[str] = []

        harness = self
        real_init = httpx.AsyncClient.__init__

        def tracking_init(client_self, **kwargs):
            harness.client_kwargs.append(dict(kwargs))
            real_init(client_self, **kwargs)

        async def mock_get(client_self, url, **kwargs):
            harness.get_urls.append(str(url))
            harness.get_kwargs.append(kwargs)
            status, headers, text = responder(str(url))
            return httpx.Response(status, headers=headers, text=text, request=httpx.Request("GET", url))

        async def mock_crawl(jina_self, url, **kwargs):
            harness.jina_urls.append(url)
            return "<html><body><p>from jina</p></body></html>"

        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = None
        monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
        monkeypatch.setattr("deerflow.community.jina_ai.tools.validate_public_http_url", lambda *a, **k: None)
        monkeypatch.setattr(httpx.AsyncClient, "__init__", tracking_init)
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        monkeypatch.setattr(JinaClient, "crawl", mock_crawl)


def _csv_ok(_url):
    return 200, {"content-type": "text/csv; charset=utf-8"}, CSV_BODY


@pytest.mark.anyio
@pytest.mark.parametrize("url", [GVIZ_URL, EXPORT_URL])
async def test_web_fetch_google_sheets_csv_is_read_directly(monkeypatch, url):
    harness = _SheetsHarness(monkeypatch, _csv_ok)

    result = await web_fetch_tool.ainvoke(url)

    assert result == CSV_BODY
    assert harness.get_urls == [url]
    assert harness.jina_urls == []
    assert harness.get_kwargs[0]["follow_redirects"] is False
    assert "headers" not in harness.get_kwargs[0]


@pytest.mark.anyio
async def test_web_fetch_google_sheets_honors_timeout_proxy_and_trust_env(monkeypatch):
    harness = _SheetsHarness(monkeypatch, _csv_ok)
    mock_tool_config = MagicMock()
    mock_tool_config.model_extra = {"timeout": "20", "proxy": "http://host.docker.internal:7890", "trust_env": "false"}
    config = MagicMock()
    config.get_tool_config.return_value = mock_tool_config
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: config)

    result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert result == CSV_BODY
    assert harness.client_kwargs == [{"trust_env": False, "proxy": "http://host.docker.internal:7890"}]
    assert harness.get_kwargs[0]["timeout"] == 20


@pytest.mark.anyio
async def test_web_fetch_google_sheets_output_is_capped_at_4096(monkeypatch):
    long_csv = "a,b\n" * 5000
    harness = _SheetsHarness(monkeypatch, lambda _url: (200, {"content-type": "text/plain"}, long_csv))

    result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert len(result) == 4096
    assert result == long_csv[:4096]
    assert harness.jina_urls == []


@pytest.mark.anyio
async def test_web_fetch_google_non_csv_url_still_goes_to_jina(monkeypatch):
    harness = _SheetsHarness(monkeypatch, _csv_ok)
    edit_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

    result = await web_fetch_tool.ainvoke(edit_url)

    assert "from jina" in result
    assert harness.get_urls == []
    assert harness.jina_urls == [edit_url]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:json",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx",
        f"http://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv",
        f"https://docs.google.com.evil.example/spreadsheets/d/{SHEET_ID}/export?format=csv",
        f"https://evil.example/spreadsheets/d/{SHEET_ID}/export?format=csv&x=docs.google.com",
        f"https://docs.google.com@evil.example/spreadsheets/d/{SHEET_ID}/export?format=csv",
        f"https://docs.google.com:8443/spreadsheets/d/{SHEET_ID}/export?format=csv",
        f"https://docs.google.com/other/spreadsheets/d/{SHEET_ID}/export?format=csv",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export/extra?format=csv",
    ],
)
async def test_web_fetch_lookalike_urls_are_not_treated_as_sheets_csv(monkeypatch, url):
    harness = _SheetsHarness(monkeypatch, _csv_ok)

    await web_fetch_tool.ainvoke(url)

    assert harness.get_urls == []
    assert harness.jina_urls == [url]


@pytest.mark.anyio
async def test_web_fetch_google_sheets_html_response_falls_back_to_jina(monkeypatch, caplog):
    harness = _SheetsHarness(monkeypatch, lambda _url: (200, {"content-type": "text/html; charset=utf-8"}, "<html>Sign in</html>"))

    with caplog.at_level(logging.WARNING, logger="deerflow.community.jina_ai.tools"):
        result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert "from jina" in result
    assert harness.jina_urls == [GVIZ_URL]
    warnings = [r.getMessage() for r in caplog.records if r.name == "deerflow.community.jina_ai.tools"]
    assert len(warnings) == 1
    assert "docs.google.com" in warnings[0]
    assert f"/spreadsheets/d/{SHEET_ID}/gviz/tq" in warnings[0]
    assert "Communities" not in warnings[0]
    assert "select" not in warnings[0]


@pytest.mark.anyio
async def test_web_fetch_google_sheets_non_200_falls_back_to_jina(monkeypatch):
    harness = _SheetsHarness(monkeypatch, lambda _url: (404, {"content-type": "text/csv"}, CSV_BODY))

    result = await web_fetch_tool.ainvoke(EXPORT_URL)

    assert "from jina" in result
    assert harness.jina_urls == [EXPORT_URL]


@pytest.mark.anyio
async def test_web_fetch_google_sheets_follows_google_redirect(monkeypatch):
    final = "https://doc-0c-8k-sheets.googleusercontent.com/export/abc?format=csv"

    def responder(url):
        if url.startswith("https://docs.google.com/"):
            return 307, {"location": final}, ""
        return _csv_ok(url)

    harness = _SheetsHarness(monkeypatch, responder)

    result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert result == CSV_BODY
    assert harness.get_urls == [GVIZ_URL, final]
    assert harness.jina_urls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/steal?format=csv",
        "http://docs.google.com/spreadsheets/d/x/export?format=csv",
        "https://evilgoogle.com/x",
        "https://docs.google.com.evil.example/x",
        "https://169.254.169.254/latest/meta-data",
    ],
)
async def test_web_fetch_google_sheets_refuses_redirect_to_other_hosts(monkeypatch, caplog, target):
    harness = _SheetsHarness(monkeypatch, lambda _url: (302, {"location": target}, ""))

    with caplog.at_level(logging.WARNING, logger="deerflow.community.jina_ai.tools"):
        result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert "from jina" in result
    assert harness.get_urls == [GVIZ_URL]
    assert harness.jina_urls == [GVIZ_URL]
    assert not any("Communities" in r.getMessage() for r in caplog.records)


@pytest.mark.anyio
async def test_web_fetch_google_sheets_redirect_loop_stops_after_five(monkeypatch):
    harness = _SheetsHarness(monkeypatch, lambda _url: (302, {"location": "https://docs.google.com/loop"}, ""))

    result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert "from jina" in result
    assert len(harness.get_urls) == 6  # the original request plus five redirects
    assert harness.jina_urls == [GVIZ_URL]


@pytest.mark.anyio
async def test_web_fetch_google_sheets_exception_falls_back_to_jina(monkeypatch, caplog):
    def responder(_url):
        raise httpx.ConnectTimeout("timed out reaching ?tq=secret-client-query")

    harness = _SheetsHarness(monkeypatch, responder)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.jina_ai.tools"):
        result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert "from jina" in result
    assert harness.jina_urls == [GVIZ_URL]
    messages = " ".join(r.getMessage() for r in caplog.records if r.name == "deerflow.community.jina_ai.tools")
    assert "ConnectTimeout" in messages
    assert "secret-client-query" not in messages


@pytest.mark.anyio
async def test_web_fetch_google_sheets_url_safety_failure_falls_back_to_jina(monkeypatch):
    harness = _SheetsHarness(monkeypatch, _csv_ok)
    monkeypatch.setattr("deerflow.community.jina_ai.tools.validate_public_http_url", lambda *a, **k: "Error: Refusing to fetch a private, loopback, or metadata address")

    result = await web_fetch_tool.ainvoke(GVIZ_URL)

    assert "from jina" in result
    assert harness.get_urls == []
    assert harness.jina_urls == [GVIZ_URL]


@pytest.mark.anyio
async def test_web_fetch_non_google_url_is_unchanged(monkeypatch):
    harness = _SheetsHarness(monkeypatch, _csv_ok)
    url = "https://example.com/data.csv"

    result = await web_fetch_tool.ainvoke(url)

    assert "from jina" in result
    assert harness.get_urls == []
    assert harness.jina_urls == [url]


@pytest.mark.anyio
async def test_web_fetch_normal_output_is_capped_at_4096(monkeypatch):
    harness = _SheetsHarness(monkeypatch, _csv_ok)
    long_html = "<html><body>" + "<p>" + ("word " * 3000) + "</p></body></html>"

    async def mock_crawl(jina_self, url, **kwargs):
        harness.jina_urls.append(url)
        return long_html

    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    result = await web_fetch_tool.ainvoke("https://example.com/long")

    assert len(result) == 4096
