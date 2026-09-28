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
MAX_QUERY_LENGTH = 400
MAX_RESULTS = 10
MAX_URLS = 5
MAX_TEXT_CHARS = 4000
SEARCH_TOOL = "exa.search"
CONTENTS_TOOL = "exa.contents"


def exa_api_key() -> str:
    return os.getenv("EXA_API_KEY", "").strip()


class ExaToolProvider(ToolProvider):
    """Opt-in Exa search and contents. Successful results keep provider source URLs.

    `EXA_API_KEY` is the only opt-in. `EXA_BASE_URL` selects the endpoint after that
    key is set and never enables the provider by itself. There is no execute meta-tool.
    """

    provider_id = "exa"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key if api_key is not None else exa_api_key()
        raw_base = base_url if base_url is not None else os.getenv("EXA_BASE_URL", "")
        self.base_url = (raw_base.strip() or DEFAULT_EXA_BASE_URL).rstrip("/")
        self.transport = transport
        self._specs = {spec.name: spec for spec in self._tool_specs()} if self.configured() else {}

    def configured(self) -> bool:
        return bool(self._api_key.strip() and self.base_url)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs.values()) if self.configured() else []

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self.configured():
            raise ToolError("Exa is not configured", FailureClass.TOOL_MISSING)
        arguments = require_arguments(call.arguments)
        if call.name == SEARCH_TOOL:
            output = await self._search(arguments)
        elif call.name == CONTENTS_TOOL:
            output = await self._contents(arguments)
        else:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
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
            detail="Configured; search runs on invoke",
            tools=[spec.name for spec in self.list_tools()],
        )

    def _tool_specs(self) -> list[ToolSpec]:
        common = {
            "provider": self.provider_id,
            "permissions": ["exa", "network", "read"],
            "risk_class": "external_read_only",
            "environment": ["EXA_API_KEY"],
        }
        return [
            ToolSpec(
                name=SEARCH_TOOL,
                description="Search the web with Exa. Each result includes a source URL.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "maxLength": MAX_QUERY_LENGTH},
                        "num_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
                    },
                    "required": ["query"],
                },
                **common,
            ),
            ToolSpec(
                name=CONTENTS_TOOL,
                description="Fetch extracted page text for explicit http(s) source URLs.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": MAX_URLS,
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["urls"],
                },
                **common,
            ),
        ]

    async def _search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("exa.search requires a query", FailureClass.TOOL_FAILURE)
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise ToolError("Exa search query is too long", FailureClass.TOOL_FAILURE)
        limit = _bounded_int(arguments.get("num_results", 5), "num_results", 1, MAX_RESULTS)
        payload = await self._request("POST", "/search", {
            "query": query,
            "numResults": limit,
            "contents": {"text": {"maxCharacters": MAX_TEXT_CHARS}},
        })
        results = _sourced_results(payload)
        return {"query": query, "results": results}

    async def _contents(self, arguments: dict[str, Any]) -> dict[str, Any]:
        urls = _require_urls(arguments.get("urls"))
        payload = await self._request("POST", "/contents", {
            "urls": urls,
            "text": {"maxCharacters": MAX_TEXT_CHARS},
        })
        return {"urls": urls, "results": _sourced_results(payload)}

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
        if response.status_code in {301, 302, 303, 307, 308}:
            raise ToolError("Exa returned an unexpected redirect", FailureClass.TOOL_FAILURE)
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


def _bounded_int(value: Any, name: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolError(f"{name} must be an integer", FailureClass.TOOL_FAILURE)
    if value < low or value > high:
        raise ToolError(f"{name} is outside the allowed range", FailureClass.TOOL_FAILURE)
    return value


def _require_urls(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ToolError("exa.contents requires urls", FailureClass.TOOL_FAILURE)
    if len(value) > MAX_URLS:
        raise ToolError("exa.contents accepts at most 5 urls", FailureClass.TOOL_FAILURE)
    urls: list[str] = []
    for item in value:
        url = public_http_url(item) if isinstance(item, str) else None
        if url is None:
            raise ToolError("exa.contents requires http(s) urls", FailureClass.TOOL_FAILURE)
        urls.append(url)
    return urls


def public_http_url(value: str) -> str | None:
    text = value.strip()
    if not text or len(text) > 2000:
        return None
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))


def _sourced_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("results")
    if not isinstance(raw, list):
        raise ToolError("Exa returned no results", FailureClass.TOOL_FAILURE)
    results: list[dict[str, Any]] = []
    for item in raw:
        sourced = _sourced_result(item)
        if sourced is not None:
            results.append(sourced)
    if not results:
        raise ToolError("Exa returned no sourced results", FailureClass.TOOL_FAILURE)
    return results


def _sourced_result(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    url = item.get("url")
    public = public_http_url(url) if isinstance(url, str) else None
    if public is None:
        return None
    result: dict[str, Any] = {"url": public}
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        result["title"] = title.strip()[:300]
    author = item.get("author")
    if isinstance(author, str) and author.strip():
        result["author"] = author.strip()[:200]
    published = item.get("publishedDate")
    if isinstance(published, str) and published.strip():
        result["published_date"] = published.strip()[:40]
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        result["text"] = text.strip()[:MAX_TEXT_CHARS]
    score = item.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        result["score"] = score
    return result
