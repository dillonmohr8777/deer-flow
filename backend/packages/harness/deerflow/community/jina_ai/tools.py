import asyncio
import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from langchain.tools import tool

from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

logger = logging.getLogger(__name__)

readability_extractor = ReadabilityExtractor()

# Shared output cap for every web_fetch return path.
_MAX_OUTPUT_CHARS = 4096

# Public Google Sheets CSV links are read directly: the anonymous Jina reader
# is blocked for docs.google.com, and the sheet query can hold client data.
_SHEETS_HOST = "docs.google.com"
_SHEETS_PATH_RE = re.compile(r"^/spreadsheets/d/[A-Za-z0-9_-]+/(?P<kind>gviz/tq|export)$")
_SHEETS_MAX_REDIRECTS = 5
_SHEETS_CSV_CONTENT_TYPES = {"text/csv", "text/plain"}
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_timeout(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _coerce_proxy(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    proxy = value.strip()
    return proxy or None


def _is_google_sheets_csv_url(url: str) -> bool:
    """Return True for a public Google Sheets CSV link (gviz/tq out:csv or export format=csv)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != _SHEETS_HOST:
            return False
        if parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    match = _SHEETS_PATH_RE.match(parsed.path)
    if match is None:
        return False
    params = parse_qs(parsed.query)
    if match.group("kind") == "gviz/tq":
        return any("out:csv" in value.split(";") for value in params.get("tqx", []))
    return "csv" in params.get("format", [])


def _is_allowed_sheets_redirect(url: str) -> bool:
    """Redirects from a Sheets link may only land on https Google hosts."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host == _SHEETS_HOST or host.endswith(".googleusercontent.com") or host.endswith(".google.com"))


async def _fetch_google_sheets_csv(url: str, *, timeout: int, proxy: str | None, trust_env: bool) -> str | None:
    """Fetch a public Google Sheets CSV directly; return the body, or None to fall back to Jina.

    No cookies or auth headers are sent. Redirects are followed manually (at most
    ``_SHEETS_MAX_REDIRECTS``) and only to Google https hosts. Failures log host and
    path only, because the sheet query string can hold client data.
    """
    parsed = urlparse(url)
    where = f"host={parsed.hostname} path={parsed.path}"
    try:
        client_kwargs: dict[str, object] = {"trust_env": trust_env}
        if proxy:
            client_kwargs["proxy"] = proxy
        current = url
        async with httpx.AsyncClient(**client_kwargs) as client:
            for _ in range(_SHEETS_MAX_REDIRECTS + 1):
                url_error = await asyncio.to_thread(validate_public_http_url, current)
                if url_error:
                    logger.warning("Direct Google Sheets CSV fetch skipped (%s): URL safety check failed", where)
                    return None
                response = await client.get(current, timeout=timeout, follow_redirects=False)
                client.cookies.clear()
                if response.status_code in _REDIRECT_STATUS_CODES and response.headers.get("location"):
                    current = urljoin(current, response.headers["location"])
                    if not _is_allowed_sheets_redirect(current):
                        logger.warning("Direct Google Sheets CSV fetch refused a redirect to a non-Google host (%s)", where)
                        return None
                    continue
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if response.status_code == 200 and content_type in _SHEETS_CSV_CONTENT_TYPES and response.text.strip():
                    return response.text
                logger.warning("Direct Google Sheets CSV fetch got status %s content-type %r (%s)", response.status_code, content_type, where)
                return None
        logger.warning("Direct Google Sheets CSV fetch exceeded %d redirects (%s)", _SHEETS_MAX_REDIRECTS, where)
    except Exception as e:
        logger.warning("Direct Google Sheets CSV fetch failed (%s): %s", where, type(e).__name__)
    return None


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    timeout = 10
    proxy = None
    trust_env = True
    config = get_app_config().get_tool_config("web_fetch")
    if config is not None:
        timeout = _coerce_timeout(config.model_extra.get("timeout"), timeout)
        proxy = _coerce_proxy(config.model_extra.get("proxy"))
        trust_env = _coerce_bool(config.model_extra.get("trust_env"), trust_env)
    if _is_google_sheets_csv_url(url):
        csv_text = await _fetch_google_sheets_csv(url, timeout=timeout, proxy=proxy, trust_env=trust_env)
        if csv_text is not None:
            return csv_text[:_MAX_OUTPUT_CHARS]
    jina_client = JinaClient()
    html_content = await jina_client.crawl(url, return_format="html", timeout=timeout, proxy=proxy, trust_env=trust_env)
    if isinstance(html_content, str) and html_content.startswith("Error:"):
        return html_content
    article = await asyncio.to_thread(readability_extractor.extract_article, html_content, url=url)
    return article.to_markdown()[:_MAX_OUTPUT_CHARS]
