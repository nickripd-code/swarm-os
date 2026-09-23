from __future__ import annotations

import asyncio

import pytest

import app.runtime as runtime_module
from app.events import EventType
from app.mission_jobs import (
    MISSION_AGENT_TASK_KIND,
    build_mission_worker_pool,
    configured_process_worker_count,
    execute_mission_agent_task,
    mission_task_job_id,
    mission_task_payload,
    parse_mission_task_item,
)
from app.models import (
    AgentSpec,
    AgentStatus,
    Mission,
    MissionEvent,
    MissionStatus,
    Task,
    TaskStatus,
    FailureClass,
)
from app.queue import WorkQueue
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.workers import ProcessWorkerPool, WorkerContext, WorkerPoolError


class WorkerController:
    mode = "test"
    model = "test-worker"

    def configured(self):
        return True

    async def work(self, state, agent):
        _ = state, agent
        return {"status": "completed", "finding": "real handler result"}


class KillDuringWorkController(WorkerController):
    def __init__(self, store, mission, agent, task):
        self.store = store
        self.mission = mission
        self.agent = agent
        self.task = task

    async def work(self, state, agent):
        _ = state, agent
        self.agent.status = AgentStatus.STOPPED
        self.task.status = TaskStatus.STOPPED
        self.store.save_agent(self.agent)
        self.store.save_task(self.task)
        self.store.append(MissionEvent(
            mission_id=self.mission.id,
            event_type=EventType.AGENT_KILLED,
            actor_id=self.agent.id,
            payload={"agent_id": str(self.agent.id), "id": str(self.agent.id)},
        ))
        return {"status": "completed", "finding": "late result must be discarded"}


def _mission_graph(store: Store):
    mission = Mission(goal="execute a durable specialist task", status=MissionStatus.WAITING)
    root = AgentSpec(mission_id=mission.id, role="mission_controller", purpose=mission.goal,
                     status=AgentStatus.RUNNING)
    agent = AgentSpec(mission_id=mission.id, parent_id=root.id, role="researcher",
                      purpose="research the durable task")
    task = Task(mission_id=mission.id, agent_id=agent.id, title="Research",
                description=agent.purpose)
    store.save_mission(mission)
    store.save_agent(root)
    store.save_agent(agent)
    store.save_task(task)
    return mission, root, agent, task


def _item(store: Store, mission, agent, task, payload=None):
    return WorkQueue(store).enqueue(
        mission_id=str(mission.id),
        kind=MISSION_AGENT_TASK_KIND,
        item_id=mission_task_job_id(task.id),
        payload=payload or mission_task_payload(mission, task, agent),
    )


def test_mission_task_payload_is_ids_only_and_rejects_extra_config(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, _, agent, task = _mission_graph(store)
    payload = mission_task_payload(mission, task, agent)
    assert payload == {
        "mission_id": str(mission.id),
        "task_id": str(task.id),
        "agent_id": str(agent.id),
    }
    item = _item(store, mission, agent, task, {**payload, "OPENAI_API_KEY": "not-allowed"})
    with pytest.raises(WorkerPoolError, match="only entity identifiers"):
        parse_mission_task_item(item)


def test_real_mission_task_handler_builds_runtime_inside_worker(monkeypatch, tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, _, agent, task = _mission_graph(store)
    item = _item(store, mission, agent, task)
    monkeypatch.setattr(runtime_module, "build_controller", lambda **_kwargs: WorkerController())
    context = WorkerContext(store, WorkQueue(store), "worker-1", str(tmp_path / "swarm.db"))

    result = execute_mission_agent_task(item, context)

    saved_task = next(value for value in store.load_tasks(mission.id) if value.id == task.id)
    saved_agent = next(value for value in store.load_agents(mission.id) if value.id == agent.id)
    assert result == {
        "mission_id": str(mission.id),
        "task_id": str(task.id),
        "agent_id": str(agent.id),
        "status": "completed",
        "output": {"status": "completed", "finding": "real handler result"},
    }
    assert saved_task.status == TaskStatus.COMPLETED
    assert saved_agent.status == AgentStatus.COMPLETED
    assert EventType.TASK_STARTED in [event.event_type for event in store.events(mission.id)]
    assert EventType.TASK_COMPLETED in [event.event_type for event in store.events(mission.id)]


def test_process_handler_does_not_overwrite_durable_agent_kill(monkeypatch, tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission, _, agent, task = _mission_graph(store)
    item = _item(store, mission, agent, task)
    controller = KillDuringWorkController(store, mission, agent, task)
    monkeypatch.setattr(runtime_module, "build_controller", lambda **_kwargs: controller)
    context = WorkerContext(store, WorkQueue(store), "worker-1", str(tmp_path / "swarm.db"))

    with pytest.raises(asyncio.CancelledError):
        execute_mission_agent_task(item, context)

    saved_task = next(value for value in store.load_tasks(mission.id) if value.id == task.id)
    saved_agent = next(value for value in store.load_agents(mission.id) if value.id == agent.id)
    assert saved_task.status == TaskStatus.STOPPED
    assert saved_agent.status == AgentStatus.STOPPED
    assert EventType.TASK_COMPLETED not in [
        event.event_type for event in store.events(mission.id)
    ]


@pytest.mark.asyncio
async def test_runtime_dispatches_specialist_task_through_process_pool(tmp_path):
    path = tmp_path / "swarm.db"
    store = Store(str(path))
    mission, root, agent, task = _mission_graph(store)
    runtime = SwarmRuntime(
        store,
        controller=WorkerController(),
        tools=None,
        process_tasks=True,
    )
    runtime.agents[mission.id] = [root, agent]
    runtime.tasks[mission.id] = [task]
    pool = ProcessWorkerPool(
        path,
        {MISSION_AGENT_TASK_KIND: "tests.worker_handlers:complete_mission_task"},
        poll_interval_seconds=0.01,
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.1,
    )
    try:
        pool.start()
        await runtime._run_tasks(mission)
    finally:
        pool.stop()

    assert runtime.tasks[mission.id][0].status == TaskStatus.COMPLETED
    assert runtime.agents[mission.id][1].status == AgentStatus.COMPLETED
    item = runtime.queue.get(mission_task_job_id(task.id))
    assert item.status == "completed"
    assert set(item.payload) == {"mission_id", "task_id", "agent_id"}
    event_types = [event.event_type for event in store.events(mission.id)]
    assert EventType.JOB_ENQUEUED in event_types
    assert EventType.JOB_COMPLETED in event_types
    assert EventType.LEASE_RELEASED in event_types


@pytest.mark.asyncio
async def test_runtime_process_dispatch_propagates_classified_failure(tmp_path):
    path = tmp_path / "swarm.db"
    store = Store(str(path))
    mission, root, agent, task = _mission_graph(store)
    runtime = SwarmRuntime(
        store,
        controller=WorkerController(),
        tools=None,
        process_tasks=True,
    )
    runtime.agents[mission.id] = [root, agent]
    runtime.tasks[mission.id] = [task]
    pool = ProcessWorkerPool(
        path,
        {MISSION_AGENT_TASK_KIND: "tests.worker_handlers:authorization_failure"},
        poll_interval_seconds=0.01,
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.1,
    )
    try:
        pool.start()
        with pytest.raises(PolicyError) as raised:
            await runtime._run_tasks(mission)
    finally:
        pool.stop()

    assert raised.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    item = runtime.queue.get(mission_task_job_id(task.id))
    assert item.status == "failed"
    assert item.result["failure_class"] == "AUTHORIZATION_REQUIRED"
    assert EventType.JOB_FAILED in [event.event_type for event in store.events(mission.id)]


def test_process_worker_count_is_bounded_and_opt_in(tmp_path):
    assert configured_process_worker_count({}) == 0
    assert build_mission_worker_pool(tmp_path / "swarm.db", env={}) is None
    pool = build_mission_worker_pool(
        tmp_path / "swarm.db", env={"SWARM_PROCESS_WORKERS": "2"}
    )
    assert isinstance(pool, ProcessWorkerPool)
    pool.stop()
    with pytest.raises(WorkerPoolError, match="between 0 and 8"):
        configured_process_worker_count({"SWARM_PROCESS_WORKERS": "9"})
    with pytest.raises(WorkerPoolError, match="must be an integer"):
        configured_process_worker_count({"SWARM_PROCESS_WORKERS": "many"})


@pytest.mark.asyncio
async def test_fastapi_lifespan_starts_and_stops_process_pool(monkeypatch):
    from app import main

    calls = []

    class RuntimeLifecycle:
        async def resume_incomplete(self):
            calls.append("resume")

        async def suspend_all(self):
            calls.append("suspend")

    class PoolLifecycle:
        def start(self):
            calls.append("pool.start")

        def stop(self):
            calls.append("pool.stop")

    monkeypatch.setattr(main, "runtime", RuntimeLifecycle())
    monkeypatch.setattr(main, "process_pool", PoolLifecycle())

    async with main.lifespan(main.app):
        calls.append("serve")

    assert calls == ["resume", "pool.start", "serve", "suspend", "pool.stop"]
