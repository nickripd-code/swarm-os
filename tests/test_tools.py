import hashlib
import json
from datetime import datetime

import httpx
import pytest

from app.llm import LLMProvider
from app.models import FailureClass, Mission
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.tools import (
    LOCAL_TOOL_CATALOG, LocalToolProvider, McpToolProvider, ToolCall, ToolError,
    build_tool_provider, public_tool_data,
)
from app.verifier import local_evidence_check


def mcp_transport(handler):
    return httpx.MockTransport(handler)


class ToolThenFinish(LLMProvider):
    def __init__(self, use_json=False):
        self.use_json = use_json

    async def decide(self, state):
        if not state.get("tool_results"):
            if self.use_json:
                return {"action": "use_tool", "tool": "echo", "arguments_json": '{"text": "hello from tool"}'}
            return {"action": "use_tool", "tool": "echo", "arguments": {"text": "hello from tool"}}
        return {"action": "finish", "summary": "Used echo and received hello from tool"}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


@pytest.mark.asyncio
async def test_local_echo_and_hash_are_real(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=LocalToolProvider(allowlist=["echo", "hash.sha256", "clock.utc"]))
    mission = Mission(goal="Real local tools")
    store.save_mission(mission)
    echoed = await runtime.invoke_tool(mission, "echo", {"text": "ping"})
    hashed = await runtime.invoke_tool(mission, "hash.sha256", {"text": "abc"})
    clocked = await runtime.invoke_tool(mission, "clock.utc", {})
    assert echoed["output"]["text"] == "ping"
    assert hashed["output"]["sha256"] == hashlib.sha256(b"abc").hexdigest()
    datetime.fromisoformat(clocked["output"]["utc"])
    completed = [e for e in store.events(mission.id) if e.event_type == "tool.completed"]
    assert len(completed) == 3
    assert runtime.tool_calls_used(mission.id) == 3


@pytest.mark.asyncio
async def test_unknown_local_tool_fails_closed_without_charge(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=LocalToolProvider(allowlist=["echo"]))
    mission = Mission(goal="Unknown tool")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "shell", {"command": "ls"})
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(e.event_type == "tool.started" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_invalid_local_arguments_fail_after_charge(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=LocalToolProvider(allowlist=["echo"]))
    mission = Mission(goal="Bad args")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "echo", {})
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert runtime.tool_calls_used(mission.id) == 1
    started = [e for e in store.events(mission.id) if e.event_type == "tool.started"]
    failed = [e for e in store.events(mission.id) if e.event_type == "tool.failed"]
    assert started and failed[-1].payload["failure_class"] == "TOOL_FAILURE"
    assert not any(e.event_type == "tool.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_controller_use_tool_then_finish(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=ToolThenFinish(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Call a real tool")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert runtime.tool_results(mission.id)[0]["output"]["text"] == "hello from tool"
    events = store.events(mission.id)
    assert any(e.event_type == "tool.started" for e in events)
    assert any(e.event_type == "tool.completed" for e in events)
    assert any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_controller_use_tool_accepts_arguments_json(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=ToolThenFinish(use_json=True),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Call a real tool via JSON")
    store.save_mission(mission)
    await runtime.run(mission)
    assert store.get_mission(mission.id).status == "completed"
    assert runtime.tool_results(mission.id)[0]["output"]["text"] == "hello from tool"


@pytest.mark.asyncio
async def test_mcp_unconfigured_is_missing_not_success():
    provider = McpToolProvider(base_url="")
    assert provider.list_tools() == []
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="lookup", arguments={}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_mcp_unreachable_fails_closed():
    provider = McpToolProvider(
        base_url="http://127.0.0.1:9/mcp",
        transport=mcp_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))),
    )
    health = await provider.health()
    assert health.status == "unavailable"
    assert health.tools == []
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="lookup", arguments={}))
    assert exc.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert "offline" not in str(exc.value)


@pytest.mark.asyncio
async def test_mcp_jsonrpc_call_is_real():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-mcp-secret"
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
                "tools": [{"name": "lookup", "description": "Look up a key",
                           "inputSchema": {"type": "object"}}],
            }})
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "lookup"
        assert body["params"]["arguments"] == {"key": "alpha"}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": "found-alpha"}],
            "isError": False,
            "api_key": "must-not-leak",
        }})

    provider = McpToolProvider(
        base_url="http://mcp.test/rpc",
        api_key="test-mcp-secret",
        transport=mcp_transport(handler),
    )
    names = [spec.name for spec in await provider.discover()]
    assert names == ["lookup"]
    result = await provider.invoke(ToolCall(name="lookup", arguments={"key": "alpha"}))
    assert result.ok
    assert result.output["content"] == ["found-alpha"]
    assert "api_key" not in result.output
    assert "must-not-leak" not in json.dumps(result.output)


@pytest.mark.asyncio
async def test_mcp_error_result_is_not_success():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
                "tools": [{"name": "lookup"}],
            }})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": "nope"}],
            "isError": True,
        }})

    provider = McpToolProvider(base_url="http://mcp.test/rpc", transport=mcp_transport(handler))
    await provider.discover()
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="lookup", arguments={}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE


def test_build_tool_provider_empty_without_env(monkeypatch):
    monkeypatch.delenv("SWARM_LOCAL_TOOLS", raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    assert build_tool_provider() is None


def test_build_tool_provider_local_allowlist(monkeypatch):
    monkeypatch.setenv("SWARM_LOCAL_TOOLS", "echo,not-a-tool,hash.sha256")
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    provider = build_tool_provider()
    assert [spec.name for spec in provider.list_tools()] == ["echo", "hash.sha256"]
    assert "not-a-tool" not in LOCAL_TOOL_CATALOG


def test_public_tool_data_strips_credentials():
    cleaned = public_tool_data({"text": "ok", "api_key": "secret", "nested": {"token": "x", "n": 1}})
    assert cleaned == {"text": "ok", "nested": {"n": 1}}
