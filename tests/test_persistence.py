import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, delete, inspect, text

from app.llm import FallbackController, LLMProvider
from app.models import AgentSpec, AgentStatus, Mission, MissionEvent, MissionStatus, Task, TaskStatus
from app.runtime import SwarmRuntime
from app.store import AgentRow, Store, TaskRow


def seed_partial_mission(store: Store, status: MissionStatus = MissionStatus.RUNNING):
    mission = Mission(goal="Launch a small project", status=status)
    store.save_mission(mission)
    root = AgentSpec(
        mission_id=mission.id, role="mission_controller",
        purpose="Delegate work, inspect results and deliver the mission.",
        capabilities=["spawn", "coordinate", "reason"], status=AgentStatus.RUNNING,
    )
    planner = AgentSpec(
        mission_id=mission.id, parent_id=root.id, role="planner",
        purpose="Define the smallest concrete path from the goal to completion.",
        capabilities=["project_work", "report"], status=AgentStatus.COMPLETED,
        output={"status": "completed", "finding": "Simulated test output for planner",
                "limitations": ["Demo only"]},
    )
    store.save_agent(root)
    store.save_agent(planner)
    task = Task(
        mission_id=mission.id, agent_id=planner.id, title="Planner",
        description=planner.purpose, status=TaskStatus.COMPLETED, output=planner.output,
    )
    store.save_task(task)
    return mission, root, planner, task


async def wait_for_runs(runtime: SwarmRuntime):
    jobs = list(runtime.runs.values())
    if jobs:
        await asyncio.gather(*jobs)


@pytest.mark.asyncio
async def test_run_persists_agents_and_tasks_for_a_new_runtime(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await runtime.run(mission)

    restored = SwarmRuntime(store, controller=FallbackController())
    restored.hydrate(mission.id)
    assert store.get_mission(mission.id).status == "completed"
    assert len(restored.agents[mission.id]) == len(runtime.agents[mission.id])
    assert len(restored.tasks[mission.id]) == 4
    assert {a.role for a in restored.agents[mission.id]} == {a.role for a in runtime.agents[mission.id]}
    assert all(a.status == "completed" for a in store.load_agents(mission.id))
    assert all(t.status == "completed" for t in store.load_tasks(mission.id))


@pytest.mark.asyncio
async def test_resume_continues_persisted_graph_without_new_root(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, root, planner, _ = seed_partial_mission(store)
    runtime = SwarmRuntime(store, controller=FallbackController())
    resumed = await runtime.resume_incomplete()
    assert resumed == [mission.id]
    await wait_for_runs(runtime)

    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    controllers = [a for a in runtime.agents[mission.id] if a.role == "mission_controller"]
    assert len(controllers) == 1
    assert controllers[0].id == root.id
    assert any(a.id == planner.id and a.status == "completed" for a in runtime.agents[mission.id])
    planner_tasks = [t for t in runtime.tasks[mission.id] if t.agent_id == planner.id]
    assert len(planner_tasks) == 1
    roles = {a.role for a in runtime.agents[mission.id]}
    assert roles == {"mission_controller", "planner", "researcher", "builder", "reviewer"}
    events = store.events(mission.id)
    assert any(e.event_type == "mission.resumed" for e in events)
    assert not any(e.event_type == "mission.started" for e in events)
    assert not any(e.event_type == "mission.stopped" for e in events)


@pytest.mark.asyncio
async def test_resume_retries_interrupted_running_task(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, root, _, _ = seed_partial_mission(store)
    researcher = AgentSpec(
        mission_id=mission.id, parent_id=root.id, role="researcher",
        purpose="Find requirements, constraints, and useful options.",
        capabilities=["project_work", "report"], status=AgentStatus.RUNNING,
    )
    store.save_agent(researcher)
    store.save_task(Task(
        mission_id=mission.id, agent_id=researcher.id, title="Researcher",
        description=researcher.purpose, status=TaskStatus.RUNNING,
    ))
    runtime = SwarmRuntime(store, controller=FallbackController())
    await runtime.resume_incomplete()
    await wait_for_runs(runtime)

    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    research_tasks = [t for t in store.load_tasks(mission.id) if t.agent_id == researcher.id]
    assert len(research_tasks) == 2
    assert {task.status for task in research_tasks} == {TaskStatus.STOPPED, TaskStatus.COMPLETED}
    completed = next(task for task in research_tasks if task.status == TaskStatus.COMPLETED)
    assert completed.output and completed.output.get("finding")
    stopped = next(task for task in research_tasks if task.status == TaskStatus.STOPPED)
    assert any(
        event.event_type == "task.stopped" and event.payload.get("id") == str(stopped.id)
        for event in store.events(mission.id)
    )


@pytest.mark.asyncio
async def test_waiting_and_pending_missions_resume(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    waiting, *_ = seed_partial_mission(store, MissionStatus.WAITING)
    pending = Mission(goal="Launch a small project", status=MissionStatus.PENDING)
    store.save_mission(pending)
    runtime = SwarmRuntime(store, controller=FallbackController())
    resumed = await runtime.resume_incomplete()
    assert set(resumed) == {waiting.id, pending.id}
    await wait_for_runs(runtime)
    assert store.get_mission(waiting.id).status == "completed"
    assert store.get_mission(pending.id).status == "completed"
    assert any(e.event_type == "mission.resumed" for e in store.events(waiting.id))
    assert any(e.event_type == "mission.started" for e in store.events(pending.id))


@pytest.mark.asyncio
async def test_terminal_missions_are_not_resumed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    for status in (MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.STOPPED, MissionStatus.BLOCKED):
        store.save_mission(Mission(goal="done", status=status))
    runtime = SwarmRuntime(store, controller=FallbackController())
    assert await runtime.resume_incomplete() == []
    assert not runtime.runs


class UnconfiguredProvider(LLMProvider):
    def configured(self):
        return False

    async def decide(self, state):
        raise AssertionError("unconfigured provider must not resume execution")


@pytest.mark.asyncio
async def test_unconfigured_provider_keeps_durable_state_without_stopping(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, *_ = seed_partial_mission(store)
    runtime = SwarmRuntime(store, controller=UnconfiguredProvider())
    assert await runtime.resume_incomplete() == []
    assert not runtime.runs
    saved = store.get_mission(mission.id)
    assert saved.status == "running"
    assert store.load_agents(mission.id)
    assert not any(e.event_type == "mission.stopped" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_stop_without_live_job_persists_stopped_graph(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, root, planner, _ = seed_partial_mission(store)
    interrupted = AgentSpec(
        mission_id=mission.id, parent_id=root.id, role="researcher",
        purpose="Find requirements", capabilities=["reason"], status=AgentStatus.RUNNING,
    )
    store.save_agent(interrupted)
    store.save_task(Task(
        mission_id=mission.id, agent_id=interrupted.id, title="Researcher",
        description=interrupted.purpose, status=TaskStatus.RUNNING,
    ))
    runtime = SwarmRuntime(store, controller=FallbackController())
    stopped = await runtime.stop(mission.id)
    assert stopped.status == "stopped"
    agents = {a.id: a for a in store.load_agents(mission.id)}
    assert agents[root.id].status == "stopped"
    assert agents[planner.id].status == "completed"
    assert agents[interrupted.id].status == "stopped"
    assert all(t.status != "running" for t in store.load_tasks(mission.id))
    assert any(e.event_type == "mission.stopped" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_stop_all_still_cancels_inflight_and_persists(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))

    class SlowProvider(LLMProvider):
        def __init__(self):
            self.entered = asyncio.Event()

        async def decide(self, state):
            if any(task.get("status") in {"pending", "running"} for task in state.get("tasks", [])):
                return {"action": "wait", "reason": "worker running"}
            return {"action": "spawn", "role": "analyst", "purpose": "Analyze", "capabilities": ["reason"]}

        async def work(self, state, agent):
            self.entered.set()
            await asyncio.Future()

    provider = SlowProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Wait for a worker")
    store.save_mission(mission)
    await runtime.start(mission)
    await asyncio.wait_for(provider.entered.wait(), 2)
    await asyncio.wait_for(runtime.stop_all(), 2)
    assert store.get_mission(mission.id).status == "stopped"
    assert all(a.status == "stopped" for a in store.load_agents(mission.id))
    assert all(t.status == "stopped" for t in store.load_tasks(mission.id))
    assert all(a["status"] == "stopped" for a in store.project(mission.id)["agents"])


@pytest.mark.asyncio
async def test_graceful_suspend_keeps_mission_and_attempt_recoverable(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))

    class SlowProvider(LLMProvider):
        def __init__(self):
            self.entered = asyncio.Event()
            self.cancelled = False

        async def decide(self, state):
            if any(task.get("status") in {"pending", "running"} for task in state.get("tasks", [])):
                return {"action": "wait", "reason": "worker running"}
            return {"action": "spawn", "role": "analyst", "purpose": "Analyze", "capabilities": ["reason"]}

        async def work(self, state, agent):
            self.entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    provider = SlowProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Continue after a graceful restart")
    store.save_mission(mission)
    await runtime.start(mission)
    await asyncio.wait_for(provider.entered.wait(), 2)

    suspended = await asyncio.wait_for(runtime.suspend_all(), 2)

    assert suspended == [mission.id]
    assert provider.cancelled
    assert store.get_mission(mission.id).status == MissionStatus.WAITING
    assert any(task.status == TaskStatus.RUNNING for task in store.load_tasks(mission.id))
    events = store.events(mission.id)
    assert any(event.event_type == "mission.waiting" for event in events)
    assert any(event.event_type == "mission.suspended" for event in events)
    assert not any(event.event_type in {"mission.stopped", "mission.failed"} for event in events)


@pytest.mark.asyncio
async def test_resume_uses_original_deadline_not_recent_state_update(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))

    class NeverCalledProvider(LLMProvider):
        def __init__(self):
            self.calls = 0

        async def decide(self, state):
            self.calls += 1
            raise AssertionError("expired mission must not call a model")

    provider = NeverCalledProvider()
    mission, *_ = seed_partial_mission(store)
    original_start = datetime.now(timezone.utc) - timedelta(seconds=10)
    store.append(MissionEvent(
        mission_id=mission.id,
        event_type="mission.started",
        payload={"goal": mission.goal, "mode": "test"},
        created_at=original_start,
    ))
    mission.updated_at = datetime.now(timezone.utc)
    store.save_mission(mission)
    mission.limits.max_runtime_seconds = 1
    store.save_mission(mission)

    runtime = SwarmRuntime(store, controller=provider)
    await runtime.resume_incomplete()
    await wait_for_runs(runtime)

    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.FAILED
    assert saved.result["failure_class"] == "TIMEOUT"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_stop_all_also_stops_unscheduled_durable_missions(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, *_ = seed_partial_mission(store)
    runtime = SwarmRuntime(store, controller=FallbackController())

    stopped = await runtime.stop_all()

    assert stopped == [mission.id]
    assert store.get_mission(mission.id).status == MissionStatus.STOPPED
    assert all(agent.status not in {AgentStatus.CREATED, AgentStatus.RUNNING}
               for agent in store.load_agents(mission.id))


@pytest.mark.asyncio
async def test_hydrate_backfills_from_events_when_rows_are_missing(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await runtime.run(mission)
    missing_agent = runtime.agents[mission.id][-1]
    with store.sessions.begin() as db:
        db.execute(delete(AgentRow).where(AgentRow.id == str(missing_agent.id)))
        db.execute(delete(TaskRow))
    assert missing_agent.id not in {agent.id for agent in store.load_agents(mission.id)}
    projected = store.project_events(mission.id)
    assert projected["agents"] and projected["tasks"]

    restored = SwarmRuntime(store, controller=FallbackController())
    restored.hydrate(mission.id)
    assert len(restored.agents[mission.id]) == len(runtime.agents[mission.id])
    assert len(store.load_agents(mission.id)) == len(runtime.agents[mission.id])
    assert len(store.load_tasks(mission.id)) == 4


def test_additive_schema_preserves_existing_missions_and_events(tmp_path):
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    mission = Mission(goal="Keep this mission", status=MissionStatus.COMPLETED,
                      result={"summary": "already done"})
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE missions (
                id VARCHAR(36) PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE mission_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id VARCHAR(36),
                event_type VARCHAR(100),
                actor_id VARCHAR(36),
                payload TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(text("INSERT INTO missions (id, payload, updated_at) VALUES (:id, :payload, :updated_at)"),
                     {"id": str(mission.id), "payload": mission.model_dump_json(), "updated_at": now})
        conn.execute(text(
            "INSERT INTO mission_events (mission_id, event_type, actor_id, payload, created_at) "
            "VALUES (:mission_id, :event_type, NULL, :payload, :created_at)"
        ), {"mission_id": str(mission.id), "event_type": "mission.completed",
            "payload": '{"summary": "already done"}', "created_at": now})

    store = Store(str(path))
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.goal == "Keep this mission"
    assert loaded.status == "completed"
    assert loaded.result == {"summary": "already done"}
    events = store.events(mission.id)
    assert len(events) == 1
    assert events[0].event_type == "mission.completed"
    names = set(inspect(store.engine).get_table_names())
    assert {"missions", "mission_events", "agents", "tasks", "worker_leases", "idempotency_keys",
            "work_items", "memory_notes", "provider_outcomes"} <= names
    assert store.load_agents(mission.id) == []
    assert store.load_tasks(mission.id) == []
