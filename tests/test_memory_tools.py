"""Scoped memory tools: real remember/recall, fail closed, no invented notes."""
import json
from uuid import UUID, uuid4

import pytest

from app.llm import LLMProvider
from app.memory import MAX_NOTE_CHARS, MAX_RECALL_CHARS, MemoryError, MemoryProvider, StoreMemoryProvider
from app.models import FailureClass, Mission, utcnow
from app.policy import PolicyError, PolicyGate, PolicyRequest, memory_tools_enabled, selected_memory_tool_names
from app.runtime import SwarmRuntime
from app.store import MemoryNoteRow, Store
from app.tools import LocalToolProvider, ToolCall, ToolError, build_tool_provider
from app.verifier import local_evidence_check

_QUIET = (
    "SWARM_LOCAL_TOOLS",
    "SWARM_MEMORY_TOOLS",
    "MCP_SERVER_URL",
    "MCP_API_KEY",
    "SWARM_BROWSER",
    "SWARM_SELFMOD",
    "SWARM_SELFMOD_WRITE",
    "COMPOSIO_API_KEY",
)


def _quiet(monkeypatch):
    for key in _QUIET:
        monkeypatch.delenv(key, raising=False)


def _opt_in(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("SWARM_MEMORY_TOOLS", "1")


class _BoomMemory(MemoryProvider):
    provider_id = "boom"

    def remember(self, mission_id, body, *, agent_id=None):
        del mission_id, body, agent_id
        raise MemoryError("Persisted memory note is corrupt", FailureClass.INVALID_OUTPUT)

    def recall(self, mission_id, *, agent_id=None, max_chars=None):
        del mission_id, agent_id, max_chars
        raise MemoryError("Persisted memory note is corrupt", FailureClass.INVALID_OUTPUT)


class _SpawnWaitFinish(LLMProvider):
    def __init__(self, summary):
        self.summary = summary

    async def decide(self, state):
        if not any(agent.get("role") == "analyst" for agent in state.get("agents", [])):
            return {"action": "spawn", "role": "analyst", "purpose": "Remember a fact",
                    "capabilities": ["reason"]}
        if any(task.get("status") in {"pending", "running"} for task in state.get("tasks", [])):
            return {"action": "wait", "reason": "worker running"}
        return {"action": "finish", "summary": self.summary}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class _WorkerRememberRecall(_SpawnWaitFinish):
    async def work(self, state, agent):
        del agent
        results = state.get("tool_results") or []
        if not results:
            return {"status": "use_tool", "finding": "Store a note", "tool": "memory.remember",
                    "arguments": {"body": "worker-fact", "scope": "agent"}}
        if len(results) == 1:
            return {"status": "use_tool", "finding": "Read it back", "tool": "memory.recall",
                    "arguments": {"scope": "agent"}}
        notes = results[1]["output"]["notes"]
        body = notes[0]["body"] if notes else ""
        return {"status": "completed", "finding": body, "limitations": []}


def _runtime(tmp_path, monkeypatch, *, tools=None, memory=None, goal="Remember a fact"):
    _opt_in(monkeypatch)
    store = Store(str(tmp_path / "memory-tools.db"))
    notes = memory if memory is not None else StoreMemoryProvider(store)
    provider = tools if tools is not None else LocalToolProvider(
        allowlist=["memory.remember", "memory.recall"], memory=notes,
    )
    runtime = SwarmRuntime(store, tools=provider, memory=notes)
    mission = Mission(goal=goal)
    store.save_mission(mission)
    return store, runtime, mission, notes


def test_policy_denies_memory_until_opt_in_and_allows_local_only(monkeypatch):
    _quiet(monkeypatch)
    gate = PolicyGate()
    local = Mission(goal="private notes", privacy="local_only")
    assert memory_tools_enabled() is False
    with pytest.raises(PolicyError) as denied:
        gate.authorize(PolicyRequest(action="tool_use", mission=local, tool="memory.remember"))
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL
    monkeypatch.setenv("SWARM_LOCAL_TOOLS", "memory.recall")
    assert selected_memory_tool_names() == ["memory.recall"]
    gate.authorize(PolicyRequest(action="tool_use", mission=local, tool="memory.recall"))
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=local, tool="memory.remember"))
    monkeypatch.setenv("SWARM_MEMORY_TOOLS", "yes")
    gate.authorize(PolicyRequest(action="tool_use", mission=local, tool="memory.remember"))
    with pytest.raises(PolicyError) as network:
        gate.authorize(PolicyRequest(action="tool_use", mission=local, tool="http"))
    assert "local_only" in str(network.value)


@pytest.mark.asyncio
async def test_remember_and_recall_are_real_and_scoped(tmp_path, monkeypatch):
    store, runtime, mission, memory = _runtime(tmp_path, monkeypatch)
    other = Mission(goal="other mission")
    store.save_mission(other)
    actor = uuid4()
    written = await runtime.invoke_tool(mission, "memory.remember", {"body": " Prefer sequential review. "})
    note = written["output"]["note"]
    assert written["ok"] is True
    assert note["body"] == "Prefer sequential review."
    assert note["scope"] == "mission"
    assert note["agent_id"] is None
    read = await runtime.invoke_tool(mission, "memory.recall", {})
    assert read["output"]["notes"] == [note]
    assert [item.body for item in memory.recall(mission.id)] == ["Prefer sequential review."]
    empty_other = await runtime.invoke_tool(other, "memory.recall", {})
    assert empty_other["output"]["notes"] == []
    agent_note = await runtime.invoke_tool(
        mission, "memory.remember", {"body": "private fact", "scope": "agent"}, actor,
    )
    assert agent_note["output"]["note"]["agent_id"] == str(actor)
    mission_only = await runtime.invoke_tool(mission, "memory.recall", {})
    assert [item["body"] for item in mission_only["output"]["notes"]] == ["Prefer sequential review."]
    agent_read = await runtime.invoke_tool(mission, "memory.recall", {"scope": "agent"}, actor)
    assert [item["body"] for item in agent_read["output"]["notes"]] == [
        "Prefer sequential review.", "private fact",
    ]
    events = store.events(mission.id)
    started = [event for event in events if event.event_type == "tool.started"]
    completed = [event for event in events if event.event_type == "tool.completed"]
    assert len(started) == 5
    assert len(completed) == 5
    assert runtime.tool_calls_used(mission.id) == 5
    assert not any(event.event_type == "tool.failed" for event in events)


@pytest.mark.asyncio
async def test_empty_recall_returns_empty_list(tmp_path, monkeypatch):
    store, runtime, mission, memory = _runtime(tmp_path, monkeypatch)
    result = await runtime.invoke_tool(mission, "memory.recall", {})
    assert result["ok"] is True
    assert result["output"] == {"notes": []}
    assert memory.recall(mission.id) == []
    completed = [event for event in store.events(mission.id) if event.event_type == "tool.completed"]
    assert completed[-1].payload["output"]["notes"] == []


@pytest.mark.asyncio
async def test_oversize_corrupt_and_unbounded_recall_fail_closed(tmp_path, monkeypatch):
    store, runtime, mission, memory = _runtime(tmp_path, monkeypatch)
    with pytest.raises(PolicyError) as oversize:
        await runtime.invoke_tool(mission, "memory.remember", {"body": "n" * (MAX_NOTE_CHARS + 1)})
    assert oversize.value.failure_class == FailureClass.CONTEXT_LIMIT
    assert memory.recall(mission.id) == []
    with pytest.raises(PolicyError) as empty:
        await runtime.invoke_tool(mission, "memory.remember", {"body": "   "})
    assert empty.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(PolicyError) as huge:
        await runtime.invoke_tool(mission, "memory.recall", {"max_chars": MAX_RECALL_CHARS + 1})
    assert huge.value.failure_class == FailureClass.CONTEXT_LIMIT
    with store.sessions.begin() as db:
        db.add(MemoryNoteRow(
            id=str(uuid4()),
            mission_id=str(mission.id),
            agent_id=None,
            body="   ",
            created_at=utcnow(),
        ))
    with pytest.raises(PolicyError) as corrupt:
        await runtime.invoke_tool(mission, "memory.recall", {})
    assert corrupt.value.failure_class == FailureClass.INVALID_OUTPUT
    events = store.events(mission.id)
    assert any(event.event_type == "tool.failed" for event in events)
    assert not any(event.event_type == "tool.completed" for event in events)
    assert any(event.event_type == "tool.started" for event in events)


@pytest.mark.asyncio
async def test_policy_deny_does_not_charge_or_invent(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    store = Store(str(tmp_path / "denied.db"))
    memory = StoreMemoryProvider(store)
    runtime = SwarmRuntime(
        store,
        tools=LocalToolProvider(allowlist=["memory.remember", "memory.recall"], memory=memory),
        memory=memory,
    )
    mission = Mission(goal="denied memory", privacy="local_only")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "memory.remember", {"body": "should not stick"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    assert memory.recall(mission.id) == []
    assert not any(event.event_type == "tool.started" for event in store.events(mission.id))
    failed = [event for event in store.events(mission.id) if event.event_type == "tool.failed"]
    assert failed and failed[-1].payload["failure_class"] == "POLICY_REFUSAL"
    with pytest.raises(PolicyError) as network:
        await runtime.invoke_tool(mission, "http", {})
    assert network.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(network.value)


@pytest.mark.asyncio
async def test_scope_mismatch_and_missing_provider_do_not_succeed(tmp_path, monkeypatch):
    store, runtime, mission, memory = _runtime(tmp_path, monkeypatch)
    stranger = uuid4()
    actor = uuid4()
    with pytest.raises(PolicyError) as wrong_mission:
        await runtime.invoke_tool(
            mission, "memory.remember", {"body": "nope", "mission_id": str(uuid4())},
        )
    assert wrong_mission.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError) as wrong_agent:
        await runtime.invoke_tool(
            mission, "memory.remember",
            {"body": "nope", "scope": "agent", "agent_id": str(stranger)}, actor,
        )
    assert wrong_agent.value.failure_class == FailureClass.POLICY_REFUSAL
    assert memory.recall(mission.id) == []
    provider = LocalToolProvider(allowlist=["memory.remember"], memory=memory)
    with pytest.raises(ToolError) as unbound:
        await provider.invoke(ToolCall(name="memory.remember", arguments={"body": "x"}))
    assert unbound.value.failure_class == FailureClass.INVALID_OUTPUT
    boom = _BoomMemory()
    failing = SwarmRuntime(
        store,
        tools=LocalToolProvider(allowlist=["memory.remember", "memory.recall"], memory=boom),
        memory=boom,
    )
    with pytest.raises(PolicyError) as exploded:
        await failing.invoke_tool(mission, "memory.recall", {})
    assert exploded.value.failure_class == FailureClass.INVALID_OUTPUT
    assert not any(
        event.event_type == "tool.completed" and event.payload.get("ok")
        for event in store.events(mission.id)
    )
    missing = SwarmRuntime(
        store,
        tools=LocalToolProvider(allowlist=["memory.recall"], memory=None),
        memory=None,
    )
    with pytest.raises(PolicyError) as unconfigured:
        await missing.invoke_tool(mission, "memory.recall", {})
    assert unconfigured.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_credential_keys_are_stripped_and_recall_stays_bounded(tmp_path, monkeypatch):
    store, runtime, mission, memory = _runtime(tmp_path, monkeypatch)
    secret = "sk-secret-must-not-leak"
    written = await runtime.invoke_tool(mission, "memory.remember", {
        "body": json.dumps({"api_key": secret, "fact": "keep"}),
        "token": "sibling-secret",
    })
    body = written["output"]["note"]["body"]
    assert json.loads(body) == {"fact": "keep"}
    assert secret not in json.dumps(written)
    with pytest.raises(PolicyError) as only_secret:
        await runtime.invoke_tool(mission, "memory.remember", {
            "body": json.dumps({"password": secret}),
        })
    assert only_secret.value.failure_class == FailureClass.INVALID_OUTPUT
    bound_mission = Mission(goal="bounded recall")
    store.save_mission(bound_mission)
    for body in ("a" * 10, "b" * 10, "c" * 10):
        await runtime.invoke_tool(bound_mission, "memory.remember", {"body": body})
    bounded = await runtime.invoke_tool(bound_mission, "memory.recall", {"max_chars": 20})
    bodies = [item["body"] for item in bounded["output"]["notes"]]
    assert bodies == ["b" * 10, "c" * 10]
    assert sum(len(item) for item in bodies) <= 20
    blob = json.dumps([event.payload for event in store.events(mission.id)])
    assert secret not in blob
    assert "sibling-secret" not in blob


@pytest.mark.asyncio
async def test_worker_on_local_only_mission_remembers_and_recalls(tmp_path, monkeypatch):
    _opt_in(monkeypatch)
    store = Store(str(tmp_path / "worker.db"))
    memory = StoreMemoryProvider(store)
    runtime = SwarmRuntime(
        store,
        controller=_WorkerRememberRecall("Worker remembered worker-fact"),
        tools=LocalToolProvider(allowlist=["memory.remember", "memory.recall"], memory=memory),
        memory=memory,
    )
    mission = Mission(goal="Worker stores a local note", privacy="local_only")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    agents = store.project(mission.id)["agents"]
    worker = next(agent for agent in agents if agent["role"] == "analyst")
    assert [note.body for note in memory.recall(mission.id)] == []
    assert [note.body for note in memory.recall(mission.id, agent_id=UUID(str(worker["id"])))] == ["worker-fact"]
    assert runtime.tool_calls_used(mission.id) == 2
    completed = [event for event in store.events(mission.id) if event.event_type == "tool.completed"]
    assert [event.payload["tool"] for event in completed] == ["memory.remember", "memory.recall"]
    assert completed[1].payload["output"]["notes"][-1]["body"] == "worker-fact"


def test_env_opt_in_registers_memory_tools_on_the_provider(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("SWARM_LOCAL_TOOLS", "echo,memory.recall,not-a-tool")
    memory = StoreMemoryProvider(Store(str(tmp_path / "env.db")))
    provider = build_tool_provider(memory=memory)
    assert [spec.name for spec in provider.list_tools()] == ["echo", "memory.recall"]
    _quiet(monkeypatch)
    monkeypatch.setenv("SWARM_MEMORY_TOOLS", "on")
    flagged = build_tool_provider(memory=memory)
    assert [spec.name for spec in flagged.list_tools()] == ["memory.remember", "memory.recall"]


@pytest.mark.asyncio
async def test_default_runtime_hides_memory_tools_until_opt_in(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    store = Store(str(tmp_path / "default.db"))
    runtime = SwarmRuntime(store)
    mission = Mission(goal="no memory tools yet")
    store.save_mission(mission)
    assert "memory.remember" not in runtime.available_tools(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "memory.remember", {"body": "nope"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    monkeypatch.setenv("SWARM_MEMORY_TOOLS", "1")
    opted = SwarmRuntime(store)
    assert opted.available_tools(mission) == ["memory.remember", "memory.recall"]
    written = await opted.invoke_tool(mission, "memory.remember", {"body": "from-default"})
    assert written["output"]["note"]["body"] == "from-default"
    assert [note.body for note in opted.memory.recall(mission.id)] == ["from-default"]
