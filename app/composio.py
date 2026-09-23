from __future__ import annotations

import os
import re
from typing import Any

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

DEFAULT_COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v3.1"
DEFAULT_COMPOSIO_TIMEOUT = 20.0
MAX_SEARCH_RESULTS = 12
MAX_DISCOVERED_TOOLS = 32
MAX_QUERY_LENGTH = 500
_TOOLKIT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
_TOOL_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]{1,200}$")
# Session readOnlyHint is a request, not a local guarantee. GitHub write slugs
# are refused here so a search response cannot register a code mutation.
_GITHUB_WRITE_TOKENS = frozenset({
    "ADD", "ARCHIVE", "COMMENT", "CREATE", "DELETE", "DISABLE", "ENABLE",
    "FORK", "INVITE", "LOCK", "MERGE", "PATCH", "PUSH", "REMOVE", "RENAME",
    "REQUEST", "REVERT", "SET", "STAR", "SUBMIT", "TRANSFER", "UNLOCK",
    "UNSTAR", "UPDATE", "UPLOAD", "WRITE",
})

SEARCH_TOOL = "composio.search_tools"
AUTHORIZE_TOOL = "composio.authorize"


def _declares_write(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("destructiveHint") is True or value.get("readOnlyHint") is False:
            return True
        return False
    if isinstance(value, list):
        return "destructiveHint" in value
    return False


def github_slug_is_mutating(slug: str, toolkit: str = "") -> bool:
    """True when a GitHub tool slug names a write, not a read."""
    if toolkit.strip().lower() != "github" and not slug.upper().startswith("GITHUB_"):
        return False
    return any(token in _GITHUB_WRITE_TOKENS for token in slug.upper().split("_"))


def schema_is_write(schema: dict[str, Any]) -> bool:
    if _declares_write(schema.get("tags")) or _declares_write(schema.get("annotations")):
        return True
    slug = schema.get("tool_slug")
    toolkit = schema.get("toolkit")
    if not isinstance(slug, str):
        return False
    return github_slug_is_mutating(slug, toolkit if isinstance(toolkit, str) else "")


class ComposioToolProvider(ToolProvider):
    """Read-only Composio session adapter with concrete policy-visible tool names.

    The provider deliberately does not expose Composio's universal execute meta tool.
    A concrete app tool must first be returned by the session's read-only search, then
    the runtime invokes that exact registered name through its normal PolicyGate.
    """

    provider_id = "composio"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        user_id: str | None = None,
        base_url: str | None = None,
        toolkits: list[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key if api_key is not None else os.getenv("COMPOSIO_API_KEY", "")
        self.user_id = (user_id if user_id is not None else os.getenv("COMPOSIO_USER_ID", "swarm-local")).strip()
        self.base_url = (
            base_url if base_url is not None else os.getenv("COMPOSIO_BASE_URL", DEFAULT_COMPOSIO_BASE_URL)
        ).rstrip("/")
        env_toolkits = [item.strip() for item in os.getenv("COMPOSIO_TOOLKITS", "").split(",") if item.strip()]
        self.toolkits = toolkits if toolkits is not None else env_toolkits
        self.transport = transport
        self._session_id: str | None = None
        self._slug_by_name: dict[str, str] = {}
        self._specs: dict[str, ToolSpec] = {}
        if self.configured():
            self._specs = {spec.name: spec for spec in self._meta_specs()}

    def configured(self) -> bool:
        return bool(self._api_key.strip() and self.user_id and self.base_url)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs.values()) if self.configured() else []

    async def discover(self) -> list[ToolSpec]:
        # Catalog expansion is query-driven so hundreds of schemas never flood prompts.
        return self.list_tools()

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self.configured():
            raise ToolError("Composio is not configured", FailureClass.AUTHORIZATION_REQUIRED)
        arguments = require_arguments(call.arguments)
        if call.name == SEARCH_TOOL:
            output = await self._search(arguments)
        elif call.name == AUTHORIZE_TOOL:
            output = await self._authorize(arguments)
        else:
            slug = self._slug_by_name.get(call.name)
            if slug is None:
                raise ToolError("Composio tool was not discovered for this session", FailureClass.TOOL_MISSING)
            output = await self._execute(slug, arguments)
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
                detail="COMPOSIO_API_KEY is not configured",
            )
        return ToolHealth(
            provider=self.provider_id,
            status="healthy",
            detail="Configured; read-only session initializes on first use",
            tools=[spec.name for spec in self.list_tools()],
        )

    def _meta_specs(self) -> list[ToolSpec]:
        common = {
            "provider": self.provider_id,
            "permissions": ["composio", "network", "read"],
            "risk_class": "external_read_only",
            "environment": ["COMPOSIO_API_KEY"],
        }
        return [
            ToolSpec(
                name=SEARCH_TOOL,
                description="Find read-only Composio app tools for a concrete use case.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "maxLength": MAX_QUERY_LENGTH},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_RESULTS},
                    },
                    "required": ["query"],
                },
                **common,
            ),
            ToolSpec(
                name=AUTHORIZE_TOOL,
                description="Create a user-facing OAuth connection link for a Composio toolkit.",
                input_schema={
                    "type": "object",
                    "properties": {"toolkit": {"type": "string", "maxLength": 80}},
                    "required": ["toolkit"],
                },
                **common,
            ),
        ]

    async def _ensure_session(self) -> str:
        if self._session_id:
            return self._session_id
        body: dict[str, Any] = {
            "user_id": self.user_id,
            "tags": {"enabled": ["readOnlyHint"]},
            "manage_connections": {
                "enable": True,
                "enable_wait_for_connections": False,
                "enable_connection_removal": False,
            },
            "search": {"enable": True},
            "execute": {"enable_multi_execute": False},
        }
        if self.toolkits:
            body["toolkits"] = {"enabled": self.toolkits}
        payload = await self._request("POST", "/tool_router/session", body)
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id.startswith("trs_"):
            raise ToolError("Composio returned an invalid session", FailureClass.TOOL_FAILURE)
        self._session_id = session_id
        return session_id

    async def _search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("composio.search_tools requires a query", FailureClass.TOOL_FAILURE)
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise ToolError("Composio search query is too long", FailureClass.TOOL_FAILURE)
        requested = arguments.get("max_results", 6)
        if not isinstance(requested, int) or isinstance(requested, bool):
            raise ToolError("max_results must be an integer", FailureClass.TOOL_FAILURE)
        limit = min(max(requested, 1), MAX_SEARCH_RESULTS)
        session_id = await self._ensure_session()
        payload = await self._request(
            "POST",
            f"/tool_router/session/{session_id}/search",
            {"queries": [{"use_case": query}], "search_strategy": "tool_search"},
        )
        schemas = payload.get("tool_schemas")
        if not isinstance(schemas, dict):
            raise ToolError("Composio search returned no tool schemas", FailureClass.TOOL_FAILURE)

        discovered: list[dict[str, Any]] = []
        for schema in schemas.values():
            if len(discovered) >= limit:
                break
            if not isinstance(schema, dict):
                continue
            slug = schema.get("tool_slug")
            if not isinstance(slug, str) or not _TOOL_SLUG_RE.fullmatch(slug):
                continue
            if schema_is_write(schema):
                continue
            public_name = self._public_name(slug)
            if public_name not in self._slug_by_name and len(self._slug_by_name) >= MAX_DISCOVERED_TOOLS:
                continue
            input_schema = schema.get("input_schema")
            output_schema = schema.get("output_schema")
            toolkit = str(schema.get("toolkit") or "")
            spec = ToolSpec(
                name=public_name,
                description=str(schema.get("description") or f"Read-only Composio tool {slug}"),
                provider=self.provider_id,
                permissions=["composio", "network", "read"] + ([f"toolkit:{toolkit}"] if toolkit else []),
                risk_class="external_read_only",
                input_schema=input_schema if isinstance(input_schema, dict) else {},
                output_schema=output_schema if isinstance(output_schema, dict) else {},
                environment=["COMPOSIO_API_KEY"],
            )
            self._specs[public_name] = spec
            self._slug_by_name[public_name] = slug
            discovered.append({"name": public_name, "toolkit": toolkit, "description": spec.description})

        results = payload.get("results")
        guidance = None
        if isinstance(results, list) and results and isinstance(results[0], dict):
            guidance = results[0].get("execution_guidance")
        return {
            "tools": discovered,
            "execution_guidance": guidance if isinstance(guidance, str) else None,
            "requires_connection": self._connection_requirements(payload),
        }

    async def _authorize(self, arguments: dict[str, Any]) -> dict[str, Any]:
        toolkit = arguments.get("toolkit")
        if not isinstance(toolkit, str) or not _TOOLKIT_RE.fullmatch(toolkit):
            raise ToolError("composio.authorize requires a valid toolkit slug", FailureClass.TOOL_FAILURE)
        session_id = await self._ensure_session()
        payload = await self._request(
            "POST",
            f"/tool_router/session/{session_id}/link",
            {"toolkit": toolkit},
        )
        redirect_url = payload.get("redirect_url")
        if not isinstance(redirect_url, str) or not redirect_url.startswith("https://"):
            raise ToolError("Composio returned an invalid authorization link", FailureClass.TOOL_FAILURE)
        account_id = payload.get("connected_account_id")
        return {
            "toolkit": toolkit,
            "redirect_url": redirect_url,
            "connected_account_id": account_id if isinstance(account_id, str) else None,
            "status": "authorization_required",
        }

    async def _execute(self, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = await self._ensure_session()
        payload = await self._request(
            "POST",
            f"/tool_router/session/{session_id}/execute",
            {"tool_slug": slug, "arguments": arguments},
        )
        if payload.get("error"):
            raise ToolError("Composio tool reported a failure", FailureClass.TOOL_FAILURE)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ToolError("Composio tool returned an invalid result", FailureClass.TOOL_FAILURE)
        return {"data": data, "log_id": payload.get("log_id")}

    async def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json", "x-api-key": self._api_key}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_COMPOSIO_TIMEOUT, connect=5.0),
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.request(method, f"{self.base_url}{path}", json=body, headers=headers)
        except httpx.TimeoutException:
            raise ToolError("Composio request timed out", FailureClass.TIMEOUT) from None
        except httpx.RequestError:
            raise ToolError("Could not reach Composio", FailureClass.PROVIDER_OUTAGE) from None
        if response.status_code in {401, 403}:
            raise ToolError("Composio authorization failed", FailureClass.AUTHORIZATION_REQUIRED)
        if response.status_code == 429:
            raise ToolError("Composio rate limit reached", FailureClass.RATE_LIMIT)
        if response.status_code >= 500:
            raise ToolError("Composio is unavailable", FailureClass.PROVIDER_OUTAGE)
        if response.is_error:
            raise ToolError("Composio request failed", FailureClass.TOOL_FAILURE)
        try:
            payload = response.json()
        except ValueError:
            raise ToolError("Composio returned invalid JSON", FailureClass.TOOL_FAILURE) from None
        if not isinstance(payload, dict):
            raise ToolError("Composio returned an invalid response", FailureClass.TOOL_FAILURE)
        if payload.get("error"):
            raise ToolError("Composio request reported a failure", FailureClass.TOOL_FAILURE)
        return payload

    @staticmethod
    def _public_name(slug: str) -> str:
        return f"composio.{slug}"

    @staticmethod
    def _connection_requirements(payload: dict[str, Any]) -> list[dict[str, Any]]:
        statuses = payload.get("toolkit_connection_statuses")
        if not isinstance(statuses, list):
            return []
        result = []
        for item in statuses:
            if not isinstance(item, dict) or item.get("has_active_connection") is True:
                continue
            toolkit = item.get("toolkit")
            if isinstance(toolkit, str):
                result.append({"toolkit": toolkit, "status": str(item.get("status_message") or "connection required")})
        return result
