from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field

from .models import FailureClass, utcnow

_UNSET = object()

DEFAULT_MCP_TIMEOUT = 15.0
MAX_ARGUMENT_BYTES = 8192
_SECRET_KEYS = frozenset({
    "api_key", "apikey", "authorization", "password", "secret", "token",
    "access_token", "refresh_token", "private_key", "link_token",
    "account_sid", "auth_token", "twilio_account_sid", "twilio_auth_token",
})


class ToolError(Exception):
    """Safe tool failure. Messages must never contain credentials or response bodies."""

    def __init__(self, message: str, failure_class: FailureClass = FailureClass.TOOL_FAILURE):
        super().__init__(message)
        self.failure_class = failure_class


class ToolSpec(BaseModel):
    name: str
    description: str
    provider: str
    permissions: list[str] = Field(default_factory=list)
    risk_class: str = "local"
    cost: float = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    environment: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: UUID = Field(default_factory=uuid4)


class ToolResult(BaseModel):
    name: str
    call_id: UUID
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    failure_class: FailureClass | None = None
    provider: str


class ToolHealth(BaseModel):
    provider: str
    status: str
    detail: str | None = None
    tools: list[str] = Field(default_factory=list)


class ToolProvider(ABC):
    """Provider-neutral tool seam owned by Swarm OS. Do not fake success."""

    provider_id: str

    @abstractmethod
    def list_tools(self) -> list[ToolSpec]:
        raise NotImplementedError

    @abstractmethod
    async def invoke(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError

    async def discover(self) -> list[ToolSpec]:
        return self.list_tools()

    async def health(self) -> ToolHealth:
        return ToolHealth(
            provider=self.provider_id,
            status="healthy" if self.list_tools() else "unconfigured",
            tools=[spec.name for spec in self.list_tools()],
        )


def public_tool_data(value: Any) -> Any:
    """Drop credential-shaped keys before events, state, or HTTP."""
    if isinstance(value, dict):
        return {
            key: public_tool_data(item)
            for key, item in value.items()
            if str(key).lower() not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [public_tool_data(item) for item in value]
    return value


def require_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    payload = arguments if isinstance(arguments, dict) else {}
    encoded = json.dumps(payload, default=str)
    if len(encoded.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ToolError("Tool arguments exceed the size limit", FailureClass.TOOL_FAILURE)
    return payload


def _echo(arguments: dict[str, Any]) -> dict[str, Any]:
    text = arguments.get("text")
    if not isinstance(text, str):
        raise ToolError("echo requires a string text argument", FailureClass.TOOL_FAILURE)
    return {"text": text}


def _clock_utc(arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    return {"utc": utcnow().isoformat()}


def _hash_sha256(arguments: dict[str, Any]) -> dict[str, Any]:
    text = arguments.get("text")
    if not isinstance(text, str):
        raise ToolError("hash.sha256 requires a string text argument", FailureClass.TOOL_FAILURE)
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


LOCAL_TOOL_CATALOG: dict[str, tuple[ToolSpec, Any]] = {
    "echo": (
        ToolSpec(
            name="echo",
            description="Return the provided text unchanged.",
            provider="local",
            permissions=["local"],
            risk_class="local",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            output_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        _echo,
    ),
    "clock.utc": (
        ToolSpec(
            name="clock.utc",
            description="Return the current UTC timestamp from this process.",
            provider="local",
            permissions=["local"],
            risk_class="local",
            input_schema={"type": "object", "properties": {}},
            output_schema={
                "type": "object",
                "properties": {"utc": {"type": "string"}},
                "required": ["utc"],
            },
        ),
        _clock_utc,
    ),
    "hash.sha256": (
        ToolSpec(
            name="hash.sha256",
            description="Return the SHA-256 hex digest of the provided text.",
            provider="local",
            permissions=["local"],
            risk_class="local",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            output_schema={
                "type": "object",
                "properties": {"sha256": {"type": "string"}},
                "required": ["sha256"],
            },
        ),
        _hash_sha256,
    ),
}


def local_tools_from_env(raw: str | None = None) -> list[str]:
    text = raw if raw is not None else os.getenv("SWARM_LOCAL_TOOLS", "")
    names: list[str] = []
    for item in text.split(","):
        name = item.strip()
        if name and name in LOCAL_TOOL_CATALOG and name not in names:
            names.append(name)
    return names


class LocalToolProvider(ToolProvider):
    """Allowlisted in-process tools. Unknown names are not registered."""

    provider_id = "local"

    def __init__(self, allowlist: list[str] | None = None):
        requested = list(allowlist) if allowlist is not None else local_tools_from_env()
        self._handlers: dict[str, Any] = {}
        self._specs: list[ToolSpec] = []
        for name in requested:
            entry = LOCAL_TOOL_CATALOG.get(name)
            if entry is None:
                continue
            spec, handler = entry
            self._specs.append(spec)
            self._handlers[name] = handler

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    async def invoke(self, call: ToolCall) -> ToolResult:
        handler = self._handlers.get(call.name)
        if handler is None:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        output = handler(require_arguments(call.arguments))
        return ToolResult(
            name=call.name,
            call_id=call.call_id,
            ok=True,
            output=public_tool_data(output),
            provider=self.provider_id,
        )

    async def health(self) -> ToolHealth:
        names = [spec.name for spec in self._specs]
        return ToolHealth(
            provider=self.provider_id,
            status="healthy" if names else "unconfigured",
            detail="Allowlisted local tools" if names else "No local tools are allowlisted",
            tools=names,
        )


class McpToolProvider(ToolProvider):
    """JSON-RPC MCP client stub. Unconfigured or unreachable stays fail-closed."""

    provider_id = "mcp"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, transport=None):
        self.base_url = (base_url if base_url is not None else os.getenv("MCP_SERVER_URL", "")).rstrip("/")
        self._api_key = api_key if api_key is not None else os.getenv("MCP_API_KEY")
        self.transport = transport
        self._specs: list[ToolSpec] = []

    def configured(self) -> bool:
        return bool(self.base_url)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    async def discover(self) -> list[ToolSpec]:
        if not self.configured():
            self._specs = []
            return []
        result = await self._rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise ToolError("MCP tools/list returned an invalid catalog", FailureClass.TOOL_FAILURE)
        specs: list[ToolSpec] = []
        for item in tools:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            specs.append(ToolSpec(
                name=str(item["name"]),
                description=str(item.get("description") or ""),
                provider=self.provider_id,
                permissions=["mcp"],
                risk_class="mcp",
                input_schema=item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {},
                environment=["MCP_SERVER_URL"],
            ))
        self._specs = specs
        return list(self._specs)

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self.configured():
            raise ToolError("MCP is not configured", FailureClass.TOOL_MISSING)
        if not self._specs:
            await self.discover()
        known = {spec.name for spec in self._specs}
        if known and call.name not in known:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        result = await self._rpc("tools/call", {
            "name": call.name,
            "arguments": require_arguments(call.arguments),
        })
        if not isinstance(result, dict):
            raise ToolError("MCP tools/call returned an invalid result", FailureClass.TOOL_FAILURE)
        if result.get("isError"):
            raise ToolError("MCP tool reported a failure", FailureClass.TOOL_FAILURE)
        return ToolResult(
            name=call.name,
            call_id=call.call_id,
            ok=True,
            output=public_tool_data(_mcp_output(result)),
            provider=self.provider_id,
        )

    async def health(self) -> ToolHealth:
        if not self.configured():
            return ToolHealth(
                provider=self.provider_id,
                status="unconfigured",
                detail="MCP is not configured",
            )
        try:
            await self.discover()
        except ToolError as exc:
            status = "unavailable" if exc.failure_class in {
                FailureClass.TIMEOUT, FailureClass.PROVIDER_OUTAGE, FailureClass.TOOL_FAILURE,
            } else "unavailable"
            return ToolHealth(
                provider=self.provider_id,
                status=status,
                detail="MCP server is not reachable",
            )
        return ToolHealth(
            provider=self.provider_id,
            status="healthy",
            detail="MCP server reachable",
            tools=[spec.name for spec in self._specs],
        )

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.configured():
            raise ToolError("MCP is not configured", FailureClass.TOOL_MISSING)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_MCP_TIMEOUT, connect=5.0),
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.post(self.base_url, json=body, headers=headers)
        except httpx.TimeoutException:
            raise ToolError("MCP request timed out", FailureClass.TIMEOUT) from None
        except httpx.RequestError:
            raise ToolError("Could not reach MCP server", FailureClass.PROVIDER_OUTAGE) from None
        if response.is_error:
            raise ToolError("MCP server returned an error", FailureClass.TOOL_FAILURE)
        try:
            payload = response.json()
        except ValueError:
            raise ToolError("MCP returned an invalid JSON-RPC response", FailureClass.TOOL_FAILURE) from None
        if not isinstance(payload, dict):
            raise ToolError("MCP returned an invalid JSON-RPC response", FailureClass.TOOL_FAILURE)
        if payload.get("error"):
            raise ToolError("MCP JSON-RPC call failed", FailureClass.TOOL_FAILURE)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ToolError("MCP JSON-RPC result was missing", FailureClass.TOOL_FAILURE)
        return result


def _mcp_output(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("content")
    if isinstance(content, list):
        texts = [
            item.get("text") for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return {"content": texts, "structured": public_tool_data(result.get("structuredContent"))}
    if "structuredContent" in result:
        structured = result.get("structuredContent")
        return {"structured": public_tool_data(structured) if isinstance(structured, dict) else structured}
    return public_tool_data({key: value for key, value in result.items() if key != "isError"})


class CompositeToolProvider(ToolProvider):
    """Route by tool name. Local allowlist wins on collisions."""

    provider_id = "composite"

    def __init__(self, providers: list[ToolProvider]):
        self.providers = providers

    def list_tools(self) -> list[ToolSpec]:
        seen: set[str] = set()
        specs: list[ToolSpec] = []
        for provider in self.providers:
            for spec in provider.list_tools():
                if spec.name in seen:
                    continue
                seen.add(spec.name)
                specs.append(spec)
        return specs

    async def discover(self) -> list[ToolSpec]:
        for provider in self.providers:
            await provider.discover()
        return self.list_tools()

    def _provider_for(self, name: str) -> ToolProvider | None:
        for provider in self.providers:
            if any(spec.name == name for spec in provider.list_tools()):
                return provider
        return None

    async def invoke(self, call: ToolCall) -> ToolResult:
        provider = self._provider_for(call.name)
        if provider is None:
            for candidate in self.providers:
                if getattr(candidate, "configured", lambda: True)():
                    await candidate.discover()
            provider = self._provider_for(call.name)
        if provider is None:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        return await provider.invoke(call)

    async def health(self) -> ToolHealth:
        parts = [await provider.health() for provider in self.providers]
        statuses = {item.status for item in parts}
        if statuses == {"healthy"}:
            status = "healthy"
        elif "healthy" in statuses:
            status = "degraded"
        elif statuses <= {"unconfigured"}:
            status = "unconfigured"
        else:
            status = "unavailable"
        return ToolHealth(
            provider=self.provider_id,
            status=status,
            detail="; ".join(f"{item.provider}={item.status}" for item in parts),
            tools=[spec.name for spec in self.list_tools()],
        )


def build_tool_provider(
    local: LocalToolProvider | None = None,
    mcp: McpToolProvider | None = None,
    composio: ToolProvider | None | object = _UNSET,
    browser: ToolProvider | None | object = _UNSET,
    selfmod: ToolProvider | None | object = _UNSET,
    twilio: ToolProvider | None | object = _UNSET,
    transport=None,
) -> ToolProvider | None:
    """Compose opted-in local, MCP, Composio, browser, selfmod, and Twilio SMS tools."""
    providers: list[ToolProvider] = []
    local = local if local is not None else LocalToolProvider()
    if local.list_tools():
        providers.append(local)
    mcp = mcp if mcp is not None else McpToolProvider(transport=transport)
    if mcp.configured():
        providers.append(mcp)
    if composio is _UNSET:
        from .composio import ComposioToolProvider
        composio = ComposioToolProvider(transport=transport)
    if composio is not None and getattr(composio, "configured", lambda: True)():
        providers.append(composio)
    if browser is _UNSET:
        from .browser import BrowserToolProvider
        browser = BrowserToolProvider()
    if browser is not None and getattr(browser, "configured", lambda: True)():
        providers.append(browser)
    if selfmod is _UNSET:
        from .selfmod import SelfModToolProvider
        selfmod = SelfModToolProvider()
    if selfmod is not None and getattr(selfmod, "configured", lambda: True)():
        providers.append(selfmod)
    if twilio is _UNSET:
        from .twilio import TwilioSmsProvider
        twilio = TwilioSmsProvider(transport=transport)
    if twilio is not None and getattr(twilio, "configured", lambda: True)():
        providers.append(twilio)
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return CompositeToolProvider(providers)


def tools_status(provider: ToolProvider | None) -> dict[str, Any]:
    if provider is None:
        return {"configured": False, "provider": None, "tools": []}
    return {
        "configured": True,
        "provider": provider.provider_id,
        "tools": [spec.name for spec in provider.list_tools()],
    }
