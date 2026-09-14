import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.llm import LLMProvider
from app.main import kill_mission_agent
from app.models import AgentSpec, FailureClass, Mission, MissionStatus
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.verifier import local_evidence_check


class TwoSpecialistHangProvider(LLMProvider):
    """Spawn two specialists, wait, finish. First worker hangs until cancelled."""

    def __init__(self):
        self.entered_a = asyncio.Event()
        self.entered_b = asyncio.Event()
        self.cancelled_a = False
        self.b_gate = asyncio.Event()
        self.b_finding = "second specialist finished"

    async def decide(self, state):
        roles = {agent.get("role") for agent in state.get("agents", [])}
        if "analyst_a" not in roles:
            return {"action": "spawn", "role": "analyst_a", "purpose": "First analysis",
                    "capabilities": ["reason"]}
        if "analyst_b" not in roles:
            return {"action": "spawn", "role": "analyst_b", "purpose": "Second analysis",
                    "capabilities": ["reason"]}
        if any(task.get("status") in {"pending", "running"} for task in state.get("tasks", [])):
            return {"action": "wait", "reason": "workers running"}
        return {"action": "finish", "summary": "Remaining specialist finished"}

    async def work(self, state, agent):
        if agent.get("role") == "analyst_a":
            self.entered_a.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled_a = True
                raise
        self.entered_b.set()
        await self.b_gate.wait()
        return {"status": "completed", "finding": self.b_finding}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


def _agent_by_role(runtime: SwarmRuntime, mission_id, role: str) -> AgentSpec:
    return next(agent for agent in runtime.agents[mission_id] if agent.role == role)


async def _wait_event(event: asyncio.Event, timeout: float = 2):
    await asyncio.wait_for(event.wait(), timeout)


@pytest.mark.asyncio
async def test_kill_running_agent_cancels_work_and_mission_continues(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = TwoSpecialistHangProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Kill one specialist; the other should finish")
    store.save_mission(mission)
    await runtime.start(mission)
    job = runtime.runs[mission.id]
    await _wait_event(provider.entered_a)
    killed = _agent_by_role(runtime, mission.id, "analyst_a")
    survivor = _agent_by_role(runtime, mission.id, "analyst_b")
    result = await runtime.kill_agent(mission.id, killed.id)
    assert result.status == "stopped"
    assert provider.cancelled_a
    assert store.get_mission(mission.id).status in {"running", "waiting"}
    assert mission.id not in runtime.stopped
    provider.b_gate.set()
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "Remaining specialist finished"
    projection = store.project(mission.id)
    by_id = {agent["id"]: agent for agent in projection["agents"]}
    assert by_id[str(killed.id)]["status"] == "stopped"
    assert by_id[str(survivor.id)]["status"] == "completed"
    tasks = {task["agent_id"]: task for task in projection["tasks"]}
    assert tasks[str(killed.id)]["status"] == "stopped"
    assert tasks[str(survivor.id)]["status"] == "completed"
    events = store.events(mission.id)
    assert any(
        event.event_type == "agent.killed" and event.payload.get("agent_id") == str(killed.id)
        for event in events
    )
    assert any(event.event_type == "task.stopped" and str(event.actor_id) == str(killed.id) for event in events)
    assert not any(event.event_type == "mission.stopped" for event in events)
    assert not any(event.event_type == "mission.failed" for event in events)
    assert any(event.event_type == "mission.completed" for event in events)


@pytest.mark.asyncio
async def test_kill_unknown_agent_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = TwoSpecialistHangProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Unknown kill id should not emit")
    store.save_mission(mission)
    await runtime.start(mission)
    await _wait_event(provider.entered_a)
    with pytest.raises(PolicyError) as exc:
        await runtime.kill_agent(mission.id, uuid4())
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "unknown agent" in str(exc.value).lower()
    after = store.events(mission.id)
    assert not any(event.event_type == "agent.killed" for event in after)
    assert store.get_mission(mission.id).status != "stopped"
    await asyncio.wait_for(runtime.stop(mission.id), 2)


@pytest.mark.asyncio
async def test_kill_after_stop_all_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = TwoSpecialistHangProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Stop-all then kill is finished")
    store.save_mission(mission)
    await runtime.start(mission)
    await _wait_event(provider.entered_a)
    target = _agent_by_role(runtime, mission.id, "analyst_a")
    await asyncio.wait_for(runtime.stop_all(), 2)
    assert store.get_mission(mission.id).status == "stopped"
    with pytest.raises(PolicyError) as exc:
        await runtime.kill_agent(mission.id, target.id)
    assert "finished mission" in str(exc.value).lower()
    assert not any(event.event_type == "agent.killed" for event in store.events(mission.id))
    assert not any(event.event_type == "mission.completed" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_kill_then_stop_all_stops_remaining(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = TwoSpecialistHangProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Kill one then stop-all")
    store.save_mission(mission)
    await runtime.start(mission)
    job = runtime.runs[mission.id]
    await _wait_event(provider.entered_a)
    killed = _agent_by_role(runtime, mission.id, "analyst_a")
    await runtime.kill_agent(mission.id, killed.id)
    assert provider.cancelled_a
    await _wait_event(provider.entered_b)
    await asyncio.wait_for(runtime.stop_all(), 2)
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "stopped"
    events = store.events(mission.id)
    assert any(event.event_type == "agent.killed" for event in events)
    assert any(event.event_type == "mission.stopped" for event in events)
    assert not any(event.event_type == "mission.completed" for event in events)
    projection = store.project(mission.id)
    assert {agent["status"] for agent in projection["agents"]} <= {"stopped", "completed", "created"}
    assert all(agent["status"] != "running" for agent in projection["agents"])


@pytest.mark.asyncio
async def test_kill_on_completed_mission_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=TwoSpecialistHangProvider())
    mission = Mission(goal="Already done", status=MissionStatus.COMPLETED)
    store.save_mission(mission)
    agent = AgentSpec(mission_id=mission.id, role="analyst", purpose="Done work")
    store.save_agent(agent)
    with pytest.raises(PolicyError) as exc:
        await runtime.kill_agent(mission.id, agent.id)
    assert "finished mission" in str(exc.value).lower()
    assert not store.events(mission.id)


@pytest.mark.asyncio
async def test_http_kill_unknown_agent_is_404(tmp_path, monkeypatch):
    from app import main

    store = Store(str(tmp_path / "api.db"))
    provider = TwoSpecialistHangProvider()
    runtime = SwarmRuntime(store, controller=provider)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)
    mission = Mission(goal="HTTP unknown agent")
    store.save_mission(mission)
    await runtime.start(mission)
    await _wait_event(provider.entered_a)
    with pytest.raises(HTTPException) as exc:
        await kill_mission_agent(mission.id, uuid4())
    assert exc.value.status_code == 404
    assert not any(event.event_type == "agent.killed" for event in store.events(mission.id))
    await asyncio.wait_for(runtime.stop(mission.id), 2)


@pytest.mark.asyncio
async def test_http_kill_unknown_mission_is_404(tmp_path, monkeypatch):
    from app import main

    store = Store(str(tmp_path / "api.db"))
    runtime = SwarmRuntime(store, controller=TwoSpecialistHangProvider())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)
    with pytest.raises(HTTPException) as exc:
        await kill_mission_agent(uuid4(), uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_http_kill_finished_mission_is_409(tmp_path, monkeypatch):
    from app import main

    store = Store(str(tmp_path / "api.db"))
    runtime = SwarmRuntime(store, controller=TwoSpecialistHangProvider())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)
    mission = Mission(goal="HTTP finished", status=MissionStatus.STOPPED)
    store.save_mission(mission)
    agent = AgentSpec(mission_id=mission.id, role="analyst", purpose="Stopped")
    store.save_agent(agent)
    with pytest.raises(HTTPException) as exc:
        await kill_mission_agent(mission.id, agent.id)
    assert exc.value.status_code == 409
    assert not any(event.event_type == "agent.killed" for event in store.events(mission.id))
