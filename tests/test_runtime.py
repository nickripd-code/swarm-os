import pytest
import asyncio

from app.models import Mission
from app.runtime import SwarmRuntime, PolicyError
from app.llm import FallbackController
from app.llm import LLMProvider, ProviderError
from app.store import Store


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
        raise ProviderError("OpenAI quota or rate limit reached")


@pytest.mark.asyncio
async def test_failure_never_becomes_fake_success(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=BrokenProvider())
    mission = Mission(goal="Test provider failure")
    store.save_mission(mission)
    await runtime.run(mission)
    assert store.get_mission(mission.id).status == "failed"
    assert not any(e.event_type in {"controller.fallback", "mission.completed"} for e in store.events(mission.id))


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
    assert store.get_mission(mission.id).status == "failed"
