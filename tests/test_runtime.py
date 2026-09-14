import pytest
import asyncio
from datetime import timedelta

from app.models import (
    AgentStatus, FailureClass, Mission, MissionStatus, Task, TaskStatus, utcnow,
)
from app.runtime import SwarmRuntime, PolicyError
from app.llm import FallbackController
from app.llm import LLMProvider, ProviderError, DEFAULT_MAX_RETRIES, retry_delay_seconds
from app.store import Store


@pytest.fixture(autouse=True)
def instant_retry_backoff(monkeypatch):
    async def _instant(self, seconds):
        return
    monkeypatch.setattr("app.runtime.SwarmRuntime._sleep", _instant)


@pytest.mark.asyncio
async def test_project_launch_completes_and_replays(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await runtime.run(mission)
    assert store.get_mission(mission.id).status == "completed"
    assert len(store.events(mission.id)) >= 10
    assert any(e.event_type == "mission.completed" for e in store.events(mission.id))
    assert len(runtime.tasks[mission.id]) == 4
    assert len({t.agent_id for t in runtime.tasks[mission.id]}) == 4
    assert all(a.status == "completed" for a in runtime.agents[mission.id])
    assert not store.get_mission(mission.id).result.get("deliverables")


@pytest.mark.asyncio
async def test_spawn_limits_are_enforced(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = Mission(goal="x", limits={"max_agents": 1})
    store.save_mission(mission)
    await runtime.spawn(mission, "root", "root")
    with pytest.raises(PolicyError): await runtime.spawn(mission, "child", "child")


@pytest.mark.asyncio
async def test_payment_defaults_to_simulation_and_enforces_cap(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = Mission(goal="pay", budget=10, limits={"max_payment_amount": 5})
    store.save_mission(mission)
    intent = await runtime.create_payment(mission, "0xabc", 2, "test work")
    assert intent.status == "simulated"
    assert mission.spent == 2
    with pytest.raises(PolicyError): await runtime.create_payment(mission, "0xabc", 6, "too much")


class BrokenProvider(LLMProvider):
    async def decide(self, state):
        raise ProviderError("OpenAI quota or rate limit reached", FailureClass.RATE_LIMIT)


@pytest.mark.asyncio
async def test_failure_never_becomes_fake_success(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=BrokenProvider())
    mission = Mission(goal="Test provider failure")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["error"] == "OpenAI quota or rate limit reached"
    assert saved.result["failure_class"] == "RATE_LIMIT"
    events = store.events(mission.id)
    assert not any(e.event_type in {"controller.fallback", "mission.completed"} for e in events)
    failed = [e for e in events if e.event_type == "mission.failed"]
    assert failed and failed[-1].payload["failure_class"] == "RATE_LIMIT"
    llm_failed = [e for e in events if e.event_type == "llm.failed"]
    assert llm_failed and llm_failed[-1].payload["failure_class"] == "RATE_LIMIT"


class CountingFailProvider(LLMProvider):
    def __init__(self, fail_count: int, failure_class: FailureClass, message: str):
        self.fail_count = fail_count
        self.failure_class = failure_class
        self.message = message
        self.calls = 0

    async def decide(self, state):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise ProviderError(self.message, self.failure_class)
        return {"action": "finish", "summary": "Recovered after retry"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_class,message", [
    (FailureClass.RATE_LIMIT, "OpenAI quota or rate limit reached"),
    (FailureClass.TIMEOUT, "OpenAI request timed out; no demo result was substituted"),
])
async def test_retryable_provider_error_then_success(tmp_path, failure_class, message):
    store = Store(str(tmp_path / "swarm.db"))
    provider = CountingFailProvider(DEFAULT_MAX_RETRIES, failure_class, message)
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Recover from a transient provider error")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "Recovered after retry"
    assert provider.calls == DEFAULT_MAX_RETRIES + 1
    events = store.events(mission.id)
    retries = [e for e in events if e.event_type == "llm.retry"]
    assert len(retries) == DEFAULT_MAX_RETRIES
    assert [e.payload["failure_class"] for e in retries] == [str(failure_class)] * DEFAULT_MAX_RETRIES
    assert [e.payload["delay_seconds"] for e in retries] == [
        retry_delay_seconds(i) for i in range(1, DEFAULT_MAX_RETRIES + 1)
    ]
    assert not any(e.event_type in {"llm.failed", "mission.failed", "controller.fallback"} for e in events)
    assert any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_class,message", [
    (FailureClass.RATE_LIMIT, "OpenAI quota or rate limit reached"),
    (FailureClass.TIMEOUT, "OpenAI request timed out; no demo result was substituted"),
])
async def test_retryable_provider_error_exhausted_fails_closed(tmp_path, failure_class, message):
    store = Store(str(tmp_path / "swarm.db"))
    provider = CountingFailProvider(99, failure_class, message)
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Exhaust retries")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result == {"error": message, "failure_class": str(failure_class)}
    assert provider.calls == DEFAULT_MAX_RETRIES + 1
    events = store.events(mission.id)
    retries = [e for e in events if e.event_type == "llm.retry"]
    assert len(retries) == DEFAULT_MAX_RETRIES
    assert all(e.payload["failure_class"] == str(failure_class) for e in retries)
    llm_failed = [e for e in events if e.event_type == "llm.failed"]
    assert len(llm_failed) == 1
    assert llm_failed[0].payload["failure_class"] == str(failure_class)
    assert llm_failed[0].payload["attempt"] == DEFAULT_MAX_RETRIES + 1
    assert not any(e.event_type in {"mission.completed", "controller.fallback"} for e in events)
    failed = [e for e in events if e.event_type == "mission.failed"]
    assert failed and failed[-1].payload == {"error": message, "failure_class": str(failure_class)}


@pytest.mark.asyncio
async def test_non_retryable_provider_error_fails_immediately(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = CountingFailProvider(99, FailureClass.AUTHORIZATION_REQUIRED, "OpenAI rejected the API key")
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Do not retry auth failures")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "AUTHORIZATION_REQUIRED"
    assert provider.calls == 1
    events = store.events(mission.id)
    assert not any(e.event_type == "llm.retry" for e in events)
    llm_failed = [e for e in events if e.event_type == "llm.failed"]
    assert llm_failed and llm_failed[-1].payload["failure_class"] == "AUTHORIZATION_REQUIRED"


@pytest.mark.asyncio
async def test_retry_skipped_when_backoff_exceeds_mission_deadline(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = CountingFailProvider(99, FailureClass.RATE_LIMIT, "OpenAI quota or rate limit reached")
    runtime = SwarmRuntime(store, controller=provider, retry_base_seconds=30)
    mission = Mission(goal="No time left to retry", limits={"max_runtime_seconds": 1})
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "RATE_LIMIT"
    assert provider.calls == 1
    events = store.events(mission.id)
    assert not any(e.event_type == "llm.retry" for e in events)
    assert any(e.event_type == "mission.failed" and e.payload.get("failure_class") == "RATE_LIMIT"
               for e in events)


class SlowProvider(LLMProvider):
    def __init__(self):
        self.entered = asyncio.Event()
        self.cancelled = False

    async def decide(self, state):
        return {"action": "spawn", "role": "analyst", "purpose": "Analyze", "capabilities": ["reason"]}

    async def work(self, state, agent):
        self.entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_stop_all_interrupts_inflight_workers_and_persists_status(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = SlowProvider()
    runtime = SwarmRuntime(store, controller=provider)
    missions = [Mission(goal="Wait for a worker") for _ in range(2)]
    for mission in missions:
        store.save_mission(mission)
        await runtime.start(mission)
    await asyncio.wait_for(provider.entered.wait(), 2)
    await asyncio.wait_for(runtime.stop_all(), 2)
    assert provider.cancelled
    assert not runtime.runs
    for mission in missions:
        assert store.get_mission(mission.id).status == "stopped"
        assert all(a["status"] == "stopped" for a in store.project(mission.id)["agents"])
        assert all(t["status"] == "stopped" for t in store.project(mission.id)["tasks"])
        assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_runtime_deadline_cancels_worker(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = SlowProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Bounded work", limits={"max_runtime_seconds": 1})
    store.save_mission(mission)
    await runtime.run(mission)
    assert provider.cancelled
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "TIMEOUT"
    assert any(e.event_type == "mission.failed" and e.payload.get("failure_class") == "TIMEOUT"
               for e in store.events(mission.id))


class ResumeProvider(LLMProvider):
    mode = "test"

    def __init__(self):
        self.work_calls = 0
        self.decision_calls = 0

    async def work(self, state, agent):
        self.work_calls += 1
        return {"status": "completed", "finding": "Recovered work completed", "limitations": []}

    async def decide(self, state):
        self.decision_calls += 1
        assert any(task["status"] == "completed" for task in state["tasks"])
        return {"action": "finish", "summary": "Recovered mission completed"}


@pytest.mark.asyncio
async def test_unfinished_mission_rehydrates_and_resumes_without_duplicate_controller(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = ResumeProvider()
    before_crash = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Survive a process crash", status=MissionStatus.RUNNING)
    mission.updated_at = utcnow()
    store.save_mission(mission)
    root = await before_crash.spawn(mission, "mission_controller", "Coordinate",
                                    capabilities=["spawn", "coordinate", "reason"])
    await before_crash.agent_status(root, AgentStatus.RUNNING)
    child = await before_crash.spawn(mission, "researcher", "Recover this assignment", root, ["reason"])
    await before_crash.agent_status(child, AgentStatus.RUNNING)
    interrupted = Task(mission_id=mission.id, agent_id=child.id, title="Researcher",
                       description=child.purpose, status=TaskStatus.RUNNING)
    await before_crash.emit(mission.id, "task.started", interrupted.model_dump(mode="json"), child.id)

    recovered = SwarmRuntime(store, controller=provider)
    await recovered.resume(store.get_mission(mission.id))
    job = recovered.runs[mission.id]
    await job

    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.COMPLETED
    assert saved.result["summary"] == "Recovered mission completed"
    assert provider.work_calls == 1
    assert len(recovered.agents[mission.id]) == 2
    assert len([agent for agent in recovered.agents[mission.id] if agent.parent_id is None]) == 1
    events = store.events(mission.id)
    assert any(event.event_type == "mission.resumed" for event in events)
    old_task_events = [event for event in events
                       if event.payload.get("id") == str(interrupted.id)]
    assert old_task_events[-1].event_type == "task.stopped"
    projected = store.project(mission.id)
    assert sorted(task["status"] for task in projected["tasks"]) == ["completed", "stopped"]


@pytest.mark.asyncio
async def test_resume_keeps_original_runtime_deadline(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = ResumeProvider()
    mission = Mission(goal="Expired work", status=MissionStatus.RUNNING,
                      limits={"max_runtime_seconds": 1})
    mission.updated_at = utcnow() - timedelta(seconds=10)
    store.save_mission(mission)

    recovered = SwarmRuntime(store, controller=provider)
    await recovered.resume(mission)
    await recovered.runs[mission.id]

    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.FAILED
    assert saved.result["failure_class"] == "TIMEOUT"
    assert provider.work_calls == 0
    assert provider.decision_calls == 0


@pytest.mark.asyncio
async def test_process_suspend_preserves_running_mission_for_recovery(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = SlowProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Continue after graceful server restart")
    store.save_mission(mission)
    await runtime.start(mission)
    await asyncio.wait_for(provider.entered.wait(), 2)

    suspended = await asyncio.wait_for(runtime.suspend_all(), 2)

    assert suspended == [mission.id]
    assert provider.cancelled
    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.RUNNING
    assert saved.result is None
    events = store.events(mission.id)
    assert any(event.event_type == "mission.suspended" for event in events)
    assert not any(event.event_type in {"mission.stopped", "mission.failed"} for event in events)
    projected = store.project(mission.id)
    assert any(task["status"] == "running" for task in projected["tasks"])


def test_runtime_deadline_uses_start_anchor_not_later_mission_update(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=ResumeProvider())
    mission = Mission(goal="Do not extend my deadline", status=MissionStatus.RUNNING,
                      limits={"max_runtime_seconds": 5})
    runtime.started_at[mission.id] = utcnow() - timedelta(seconds=10)
    mission.updated_at = utcnow()

    assert runtime.remaining_runtime(mission) < 0
