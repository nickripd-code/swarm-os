import pytest
import asyncio

from app.models import Mission, FailureClass
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
