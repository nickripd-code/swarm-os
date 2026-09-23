import base64
import hashlib
import json
import socket
import subprocess
from datetime import datetime
from uuid import UUID

import httpx
import pytest

from app.llm import LLMProvider
from app.models import FailureClass, Mission
from app.policy import PolicyGate, PolicyRequest
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.tools import (
    LOCAL_TOOL_CATALOG, LocalToolProvider, McpToolProvider, ToolCall, ToolError,
    ToolProvider, ToolResult, ToolSpec, build_tool_provider, public_tool_data,
    tools_status,
)
from app.verifier import local_evidence_check


def mcp_transport(handler):
    return httpx.MockTransport(handler)


class ListedTools(ToolProvider):
    """Advertises names PolicyGate may still refuse (including local_only network)."""

    provider_id = "listed"

    def __init__(self, names: list[str]):
        self.names = names

    def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name=name, description=name, provider=self.provider_id) for name in self.names]

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            name=call.name, call_id=call.call_id, ok=True,
            output={"name": call.name}, provider=self.provider_id,
        )


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


class RepeatToolThenFinish(LLMProvider):
    """Controller that requests echo until two completed results exist."""

    async def decide(self, state):
        used = len(state.get("tool_results") or [])
        if used < 2:
            return {"action": "use_tool", "tool": "echo", "arguments": {"text": str(used)}}
        return {"action": "finish", "summary": "Used two echoes"}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class SpawnWaitFinish(LLMProvider):
    """Controller that spawns one analyst, waits, then finishes from worker output."""

    def __init__(self, summary="Worker finished"):
        self.summary = summary

    async def decide(self, state):
        if not any(agent.get("role") == "analyst" for agent in state.get("agents", [])):
            return {"action": "spawn", "role": "analyst", "purpose": "Use an allowed tool",
                    "capabilities": ["reason"]}
        if any(task.get("status") in {"pending", "running"} for task in state.get("tasks", [])):
            return {"action": "wait", "reason": "worker running"}
        return {"action": "finish", "summary": self.summary}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class WorkerEchoThenComplete(SpawnWaitFinish):
    async def work(self, state, agent):
        del agent
        results = state.get("tool_results") or []
        if not results:
            return {"status": "use_tool", "finding": "Need echo", "tool": "echo",
                    "arguments": {"text": "hello from worker"}}
        text = results[0]["output"]["text"]
        return {"status": "completed", "finding": f"echoed: {text}", "limitations": []}


class WorkerEchoViaArgumentsJson(SpawnWaitFinish):
    async def work(self, state, agent):
        del agent
        if not state.get("tool_results"):
            return {"status": "use_tool", "finding": "Need echo", "tool": "echo",
                    "arguments_json": '{"text": "hello from worker json"}'}
        return {"status": "completed", "finding": "echoed via json", "limitations": []}


class WorkerDeniedTool(SpawnWaitFinish):
    async def work(self, state, agent):
        del state, agent
        return {"status": "use_tool", "finding": "Need shell", "tool": "shell", "arguments": {}}


class WorkerMissingTool(SpawnWaitFinish):
    async def work(self, state, agent):
        del state, agent
        return {"status": "use_tool", "finding": "Need lookup", "tool": "lookup", "arguments": {"q": "x"}}


class WorkerRepeatingEcho(SpawnWaitFinish):
    async def work(self, state, agent):
        del agent
        used = len(state.get("tool_results") or [])
        if used < 2:
            return {"status": "use_tool", "finding": f"Need echo {used}", "tool": "echo",
                    "arguments": {"text": str(used)}}
        return {"status": "completed", "finding": "used two echoes", "limitations": []}


class WorkerNetworkTool(SpawnWaitFinish):
    async def work(self, state, agent):
        del state, agent
        return {"status": "use_tool", "finding": "Need http", "tool": "http", "arguments": {}}


class WorkerOmitsToolName(SpawnWaitFinish):
    async def work(self, state, agent):
        del state, agent
        return {"status": "use_tool", "finding": "Need a tool", "tool": None}


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
        await runtime.invoke_tool(mission, "lookup", {"query": "unknown"})
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
async def test_controller_use_tool_under_limit_succeeds(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=RepeatToolThenFinish(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Two allowed tool calls", limits={"max_tool_calls": 2})
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert runtime.tool_calls_used(mission.id) == 2
    events = store.events(mission.id)
    assert len([e for e in events if e.event_type == "tool.started"]) == 2
    assert len([e for e in events if e.event_type == "tool.completed"]) == 2
    assert not any(e.event_type == "tool.failed" for e in events)
    assert any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_controller_use_tool_at_limit_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=RepeatToolThenFinish(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="One tool only", limits={"max_tool_calls": 1})
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "RESOURCE_EXHAUSTED"
    assert runtime.tool_calls_used(mission.id) == 1
    events = store.events(mission.id)
    started = [e for e in events if e.event_type == "tool.started"]
    completed = [e for e in events if e.event_type == "tool.completed"]
    failed = [e for e in events if e.event_type == "tool.failed"]
    assert len(started) == 1 and len(completed) == 1
    assert failed and failed[-1].payload["failure_class"] == "RESOURCE_EXHAUSTED"
    assert not any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_worker_use_tool_then_complete(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerEchoThenComplete(summary="Worker used echo and received hello from worker"),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Worker calls a real tool")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert runtime.tool_results(mission.id)[0]["output"]["text"] == "hello from worker"
    assert runtime.tool_calls_used(mission.id) == 1
    tasks = store.project(mission.id)["tasks"]
    assert tasks[0]["output"]["finding"] == "echoed: hello from worker"
    events = store.events(mission.id)
    started = [e for e in events if e.event_type == "tool.started"]
    completed = [e for e in events if e.event_type == "tool.completed"]
    assert started and completed
    agents = store.project(mission.id)["agents"]
    controller = next(agent for agent in agents if agent["role"] == "mission_controller")
    worker = next(agent for agent in agents if agent["role"] == "analyst")
    assert str(started[0].actor_id) == str(completed[0].actor_id) == worker["id"]
    assert str(started[0].actor_id) != controller["id"]
    assert not any(e.event_type == "tool.failed" for e in events)
    assert any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_worker_use_tool_accepts_arguments_json(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerEchoViaArgumentsJson(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Worker calls a tool via JSON")
    store.save_mission(mission)
    await runtime.run(mission)
    assert store.get_mission(mission.id).status == "completed"
    assert runtime.tool_results(mission.id)[0]["output"]["text"] == "hello from worker json"


@pytest.mark.asyncio
async def test_worker_denied_tool_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerDeniedTool(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Worker must not get shell")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    assert runtime.tool_calls_used(mission.id) == 0
    events = store.events(mission.id)
    failed = [e for e in events if e.event_type == "tool.failed"]
    assert failed and failed[-1].payload["failure_class"] == "POLICY_REFUSAL"
    assert not any(e.event_type == "tool.started" for e in events)
    assert not any(e.event_type == "tool.completed" for e in events)
    assert not any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_worker_unknown_tool_is_missing_without_charge(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerMissingTool(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Worker must not invent lookup")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "TOOL_MISSING"
    assert runtime.tool_calls_used(mission.id) == 0
    events = store.events(mission.id)
    failed = [e for e in events if e.event_type == "tool.failed"]
    assert failed and failed[-1].payload["failure_class"] == "TOOL_MISSING"
    assert not any(e.event_type == "tool.started" for e in events)
    assert not any(e.event_type == "tool.completed" for e in events)


@pytest.mark.asyncio
async def test_worker_tool_budget_under_limit_succeeds(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerRepeatingEcho(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Two worker tools", limits={"max_tool_calls": 2})
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert runtime.tool_calls_used(mission.id) == 2
    events = store.events(mission.id)
    assert len([e for e in events if e.event_type == "tool.started"]) == 2
    assert len([e for e in events if e.event_type == "tool.completed"]) == 2
    assert not any(e.event_type == "tool.failed" for e in events)
    assert any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_worker_tool_budget_exhausts_fail_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerRepeatingEcho(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="One tool only", limits={"max_tool_calls": 1})
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "RESOURCE_EXHAUSTED"
    assert runtime.tool_calls_used(mission.id) == 1
    assert runtime.tool_results(mission.id)[0]["output"]["text"] == "0"
    events = store.events(mission.id)
    started = [e for e in events if e.event_type == "tool.started"]
    completed = [e for e in events if e.event_type == "tool.completed"]
    failed = [e for e in events if e.event_type == "tool.failed"]
    assert len(started) == 1 and len(completed) == 1
    assert failed and failed[-1].payload["failure_class"] == "RESOURCE_EXHAUSTED"
    assert not any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_worker_local_only_denies_network_tool(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerNetworkTool(),
        tools=ListedTools(["http"]),
    )
    mission = Mission(goal="Stay local", privacy="local_only")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    assert "local_only" in saved.result["error"]
    assert runtime.tool_calls_used(mission.id) == 0
    events = store.events(mission.id)
    failed = [e for e in events if e.event_type == "tool.failed"]
    assert failed and failed[-1].payload["failure_class"] == "POLICY_REFUSAL"
    assert not any(e.event_type == "tool.started" for e in events)
    assert not any(e.event_type == "tool.completed" for e in events)


@pytest.mark.asyncio
async def test_worker_use_tool_without_name_is_invalid(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=WorkerOmitsToolName(),
        tools=LocalToolProvider(allowlist=["echo"]),
    )
    mission = Mission(goal="Worker omitted the tool")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "INVALID_OUTPUT"
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(e.event_type == "tool.started" for e in store.events(mission.id))
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


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
    monkeypatch.delenv("SWARM_BROWSER", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD_WRITE", raising=False)
    assert build_tool_provider() is None


def test_build_tool_provider_local_allowlist(monkeypatch):
    monkeypatch.setenv("SWARM_LOCAL_TOOLS", "echo,not-a-tool,hash.sha256")
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("SWARM_BROWSER", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD_WRITE", raising=False)
    provider = build_tool_provider()
    assert [spec.name for spec in provider.list_tools()] == ["echo", "hash.sha256"]
    assert "not-a-tool" not in LOCAL_TOOL_CATALOG


def test_public_tool_data_strips_credentials():
    cleaned = public_tool_data({"text": "ok", "api_key": "secret", "nested": {"token": "x", "n": 1}})
    assert cleaned == {"text": "ok", "nested": {"n": 1}}


UTILITY_TOOLS = ("json.pretty", "uuid.v4", "text.bytes_len", "text.b64decode")


def _utility_provider() -> LocalToolProvider:
    return LocalToolProvider(allowlist=list(UTILITY_TOOLS))


@pytest.mark.asyncio
async def test_local_utility_tools_happy_path_strips_secrets(tmp_path, monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("utility tool attempted shell or network")

    monkeypatch.setattr(subprocess, "Popen", blocked)
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(httpx, "Client", blocked)
    monkeypatch.setattr(httpx, "AsyncClient", blocked)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=_utility_provider())
    mission = Mission(goal="Local utilities", privacy="local_only", limits={"max_tool_calls": 4})
    store.save_mission(mission)
    gate = PolicyGate()
    for name in UTILITY_TOOLS:
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool=name, tool_calls_used=0))

    pretty = await runtime.invoke_tool(mission, "json.pretty", {
        "text": '{"z":1,"api_key":"sekret","nested":{"token":"t","ok":true}}',
    })
    rendered = pretty["output"]["text"]
    assert json.loads(rendered) == {"nested": {"ok": True}, "z": 1}
    assert "sekret" not in rendered and "api_key" not in rendered and "token" not in rendered

    minted = await runtime.invoke_tool(mission, "uuid.v4", {})
    parsed = UUID(minted["output"]["uuid"])
    assert parsed.version == 4

    measured = await runtime.invoke_tool(mission, "text.bytes_len", {"text": "café"})
    assert measured["output"] == {"bytes": len("café".encode("utf-8"))}
    assert "café" not in json.dumps(measured["output"])

    encoded = base64.b64encode(b'{"token":"abc","ok":1}').decode("ascii")
    decoded = await runtime.invoke_tool(mission, "text.b64decode", {"text": encoded})
    assert json.loads(decoded["output"]["text"]) == {"ok": 1}
    assert "abc" not in decoded["output"]["text"]

    events = store.events(mission.id)
    assert len([e for e in events if e.event_type == "tool.started"]) == 4
    assert len([e for e in events if e.event_type == "tool.completed"]) == 4
    assert runtime.tool_calls_used(mission.id) == 4
    health = await runtime.tools.health()
    assert health.status == "healthy"
    assert health.tools == list(UTILITY_TOOLS)
    assert tools_status(runtime.tools)["tools"] == list(UTILITY_TOOLS)


@pytest.mark.asyncio
async def test_local_utility_bad_input_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=_utility_provider())
    mission = Mission(goal="Bad utility input", limits={"max_tool_calls": 8})
    store.save_mission(mission)
    cases = [
        ("json.pretty", {"text": "{not json"}, FailureClass.INVALID_OUTPUT),
        ("json.pretty", {"text": 1}, FailureClass.INVALID_OUTPUT),
        ("uuid.v4", {"text": "nope"}, FailureClass.INVALID_OUTPUT),
        ("text.bytes_len", {}, FailureClass.INVALID_OUTPUT),
        ("text.b64decode", {"text": "!!!!"}, FailureClass.INVALID_OUTPUT),
        ("text.b64decode", {"text": base64.b64encode(b"\xff").decode("ascii")}, FailureClass.INVALID_OUTPUT),
    ]
    for name, arguments, failure in cases:
        with pytest.raises(PolicyError) as exc:
            await runtime.invoke_tool(mission, name, arguments)
        assert exc.value.failure_class == failure
    started = [e for e in store.events(mission.id) if e.event_type == "tool.started"]
    failed = [e for e in store.events(mission.id) if e.event_type == "tool.failed"]
    assert len(started) == len(cases)
    assert [e.payload["failure_class"] for e in failed] == ["INVALID_OUTPUT"] * len(cases)
    assert not any(e.event_type == "tool.completed" for e in store.events(mission.id))
    assert runtime.tool_calls_used(mission.id) == len(cases)


@pytest.mark.asyncio
async def test_local_utility_oversize_is_tool_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("app.tools.MAX_UTILITY_OUTPUT_BYTES", 8)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=_utility_provider())
    mission = Mission(goal="Oversize utility output")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as pretty_exc:
        await runtime.invoke_tool(mission, "json.pretty", {"text": '{"hello":"world"}'})
    assert pretty_exc.value.failure_class == FailureClass.TOOL_FAILURE
    payload = base64.b64encode(b"hello-world").decode("ascii")
    with pytest.raises(PolicyError) as decode_exc:
        await runtime.invoke_tool(mission, "text.b64decode", {"text": payload})
    assert decode_exc.value.failure_class == FailureClass.TOOL_FAILURE
    failed = [e for e in store.events(mission.id) if e.event_type == "tool.failed"]
    assert [e.payload["failure_class"] for e in failed] == ["TOOL_FAILURE", "TOOL_FAILURE"]


@pytest.mark.asyncio
async def test_local_utility_disabled_when_opt_in_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("SWARM_LOCAL_TOOLS", raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("SWARM_BROWSER", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    assert build_tool_provider() is None
    empty = LocalToolProvider()
    health = await empty.health()
    assert health.status == "unconfigured"
    assert health.tools == []
    assert tools_status(empty) == {"configured": True, "provider": "local", "tools": []}
    assert tools_status(None) == {"configured": False, "provider": None, "tools": []}
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=empty)
    mission = Mission(goal="Utilities off", privacy="local_only")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "json.pretty", {"text": "{}"})
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(e.event_type == "tool.started" for e in store.events(mission.id))
    assert "json.pretty" in LOCAL_TOOL_CATALOG


def test_local_utility_allowlist_ignores_unknown_names(monkeypatch):
    monkeypatch.setenv(
        "SWARM_LOCAL_TOOLS",
        "json.pretty, shell, uuid.v4, text.bytes_len, text.b64decode, not-a-tool",
    )
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("SWARM_BROWSER", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    provider = build_tool_provider()
    assert [spec.name for spec in provider.list_tools()] == list(UTILITY_TOOLS)


@pytest.mark.asyncio
async def test_local_utility_budget_charges_only_on_started(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=_utility_provider())
    mission = Mission(goal="One utility call", privacy="local_only", limits={"max_tool_calls": 1})
    store.save_mission(mission)
    first = await runtime.invoke_tool(mission, "uuid.v4", {})
    assert UUID(first["output"]["uuid"]).version == 4
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "text.bytes_len", {"text": "next"})
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    events = store.events(mission.id)
    assert len([e for e in events if e.event_type == "tool.started"]) == 1
    assert runtime.tool_calls_used(mission.id) == 1
    denied = [e for e in events if e.event_type == "tool.failed"]
    assert denied and denied[-1].payload["failure_class"] == "RESOURCE_EXHAUSTED"
