from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .models import FailureClass
from .tools import (
    ToolCall,
    ToolError,
    ToolHealth,
    ToolProvider,
    ToolResult,
    ToolSpec,
    public_tool_data,
    require_arguments,
)

DEFAULT_EXA_BASE_URL = "https://api.exa.ai"
DEFAULT_EXA_TIMEOUT = 20.0
MAX_QUERY_LENGTH = 500
MAX_RESULTS = 10
DEFAULT_RESULTS = 5
MAX_URLS = 5
MAX_TEXT_CHARS = 2000
MAX_HIGHLIGHTS = 8

SEARCH_TOOL = "exa.search"
SEARCH_WEB_TOOL = "search.web"
CONTENTS_TOOL = "exa.contents"
EXA_TOOL_NAMES = (SEARCH_TOOL, SEARCH_WEB_TOOL, CONTENTS_TOOL)


def exa_api_key_configured(raw: str | None = None) -> bool:
    key = raw if raw is not None else os.getenv("EXA_API_KEY", "")
    return bool(key.strip())


class ExaToolProvider(ToolProvider):
    """Opt-in Exa search/contents client. Unconfigured calls fail closed.

    Registered names are concrete (`exa.search`, `search.web`, `exa.contents`)
    so PolicyGate sees the tool, not a generic execute meta-tool. Results keep
    http(s) source URLs and never invent hits.
    """

    provider_id = "exa"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key if api_key is not None else os.getenv("EXA_API_KEY", "")
        configured_base = base_url if base_url is not None else os.getenv("EXA_BASE_URL", DEFAULT_EXA_BASE_URL)
        self.base_url = configured_base.rstrip("/")
        self.transport = transport
        self._specs = {spec.name: spec for spec in self._catalog()} if self.configured() else {}

    def configured(self) -> bool:
        return bool(self._api_key.strip() and self.base_url)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs.values()) if self.configured() else []

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self.configured():
            raise ToolError("Exa search is not configured", FailureClass.TOOL_MISSING)
        if call.name not in self._specs:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        arguments = require_arguments(call.arguments)
        if call.name in {SEARCH_TOOL, SEARCH_WEB_TOOL}:
            output = await self._search(arguments)
        else:
            output = await self._contents(arguments)
        return ToolResult(
            name=call.name,
            call_id=call.call_id,
            ok=True,
            output=public_tool_data(output),
            provider=self.provider_id,
        )

    async def health(self) -> ToolHealth:
        if not self.configured():
            return ToolHealth(
                provider=self.provider_id,
                status="unconfigured",
                detail="EXA_API_KEY is not configured",
            )
        return ToolHealth(
            provider=self.provider_id,
            status="healthy",
            detail="Configured; Exa is called only on invoke",
            tools=[spec.name for spec in self.list_tools()],
        )

    def _catalog(self) -> list[ToolSpec]:
        common = {
            "provider": self.provider_id,
            "permissions": ["network", "read"],
            "risk_class": "external_read_only",
            "environment": ["EXA_API_KEY"],
        }
        search_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
        contents_schema = {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_URLS},
            },
            "required": ["urls"],
            "additionalProperties": False,
        }
        return [
            ToolSpec(
                name=SEARCH_TOOL,
                description="Search the web with Exa and return source URLs plus short extracts.",
                input_schema=search_schema,
                **common,
            ),
            ToolSpec(
                name=SEARCH_WEB_TOOL,
                description="Search the web with Exa and return source URLs plus short extracts.",
                input_schema=search_schema,
                **common,
            ),
            ToolSpec(
                name=CONTENTS_TOOL,
                description="Fetch extracted page text from http(s) URLs via Exa. Every hit includes its source URL.",
                input_schema=contents_schema,
                **common,
            ),
        ]

    async def _search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("exa search requires a query", FailureClass.TOOL_FAILURE)
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise ToolError("exa search query is too long", FailureClass.TOOL_FAILURE)
        num_results = arguments.get("num_results", DEFAULT_RESULTS)
        if isinstance(num_results, bool) or not isinstance(num_results, int):
            raise ToolError("num_results must be an integer", FailureClass.TOOL_FAILURE)
        if num_results < 1 or num_results > MAX_RESULTS:
            raise ToolError("num_results is outside the allowed range", FailureClass.TOOL_FAILURE)
        payload = await self._request("POST", "/search", {
            "query": query,
            "type": "auto",
            "numResults": num_results,
            "contents": {
                "highlights": True,
                "text": {"maxCharacters": MAX_TEXT_CHARS},
            },
        })
        return {"query": query, "results": _public_hits(payload)}

    async def _contents(self, arguments: dict[str, Any]) -> dict[str, Any]:
        urls = _require_urls(arguments.get("urls"))
        payload = await self._request("POST", "/contents", {
            "urls": urls,
            "text": {"maxCharacters": MAX_TEXT_CHARS},
            "highlights": True,
        })
        return {"urls": urls, "results": _public_hits(payload)}

    async def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": self._api_key,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_EXA_TIMEOUT, connect=5.0),
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.request(method, f"{self.base_url}{path}", json=body, headers=headers)
        except httpx.TimeoutException:
            raise ToolError("Exa request timed out", FailureClass.TIMEOUT) from None
        except httpx.RequestError:
            raise ToolError("Could not reach Exa", FailureClass.PROVIDER_OUTAGE) from None
        if response.status_code in {401, 403}:
            raise ToolError("Exa authorization failed", FailureClass.AUTHORIZATION_REQUIRED)
        if response.status_code == 429:
            raise ToolError("Exa rate limit reached", FailureClass.RATE_LIMIT)
        if response.status_code >= 500:
            raise ToolError("Exa is unavailable", FailureClass.PROVIDER_OUTAGE)
        if response.is_error:
            raise ToolError("Exa request failed", FailureClass.TOOL_FAILURE)
        try:
            payload = response.json()
        except ValueError:
            raise ToolError("Exa returned invalid JSON", FailureClass.TOOL_FAILURE) from None
        if not isinstance(payload, dict):
            raise ToolError("Exa returned an invalid response", FailureClass.TOOL_FAILURE)
        if payload.get("error"):
            raise ToolError("Exa request reported a failure", FailureClass.TOOL_FAILURE)
        return payload


def _require_urls(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ToolError("exa.contents requires a list of urls", FailureClass.TOOL_FAILURE)
    if len(value) > MAX_URLS:
        raise ToolError("exa.contents accepts at most 5 urls", FailureClass.TOOL_FAILURE)
    urls: list[str] = []
    for item in value:
        url = _http_url(item)
        if url is None:
            raise ToolError("exa.contents urls must be http(s) without userinfo", FailureClass.TOOL_FAILURE)
        if url not in urls:
            urls.append(url)
    return urls


def _public_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        raise ToolError("Exa returned an invalid result list", FailureClass.TOOL_FAILURE)
    hits: list[dict[str, Any]] = []
    for item in results:
        hit = _public_hit(item)
        if hit is not None:
            hits.append(hit)
    return hits


def _public_hit(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    url = _http_url(item.get("url")) or _http_url(item.get("id"))
    if url is None:
        return None
    title = item.get("title")
    text = item.get("text") if isinstance(item.get("text"), str) else ""
    highlights = []
    raw_highlights = item.get("highlights")
    if isinstance(raw_highlights, list):
        for piece in raw_highlights[:MAX_HIGHLIGHTS]:
            if isinstance(piece, str) and piece.strip():
                highlights.append(piece.strip()[:MAX_TEXT_CHARS])
    published = item.get("publishedDate") or item.get("published_date")
    hit: dict[str, Any] = {
        "url": url,
        "title": title.strip()[:300] if isinstance(title, str) else "",
        "text": text.strip()[:MAX_TEXT_CHARS],
        "highlights": highlights,
    }
    if isinstance(published, str) and published.strip():
        hit["published_date"] = published.strip()[:40]
    return hit


def _http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
