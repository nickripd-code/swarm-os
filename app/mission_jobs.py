"""Durable process-pool handler for specialist mission tasks.

Only durable entity identifiers cross the queue boundary.  The worker reopens
the Store supplied by ProcessWorkerPool and constructs SwarmRuntime inside the
child, so provider and tool configuration stays in trusted process environment.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from uuid import UUID

from .events import event_type_for_task
from .models import AgentSpec, AgentStatus, FailureClass, Mission, MissionStatus, Task, TaskStatus
from .queue import WorkItem
from .workers import ProcessWorkerPool, WorkerContext, WorkerPoolError

MISSION_AGENT_TASK_KIND = "mission.agent_task"
MAX_PROCESS_WORKERS = 8
_PAYLOAD_KEYS = frozenset({"mission_id", "task_id", "agent_id"})


class MissionTaskJobError(WorkerPoolError):
    failure_class = FailureClass.INVALID_OUTPUT


@dataclass(frozen=True)
class MissionTaskIds:
    mission_id: UUID
    task_id: UUID
    agent_id: UUID


def mission_task_job_id(task_id: UUID) -> str:
    return f"mission-agent-task:{task_id}"


def mission_task_payload(mission: Mission, task: Task, agent: AgentSpec) -> dict[str, str]:
    """Return the complete, credential-free payload accepted by the worker."""
    if task.mission_id != mission.id or agent.mission_id != mission.id:
        raise MissionTaskJobError("Mission task entities do not belong to the same mission")
    if task.agent_id != agent.id:
        raise MissionTaskJobError("Mission task does not belong to the selected agent")
    return {
        "mission_id": str(mission.id),
        "task_id": str(task.id),
        "agent_id": str(agent.id),
    }


def parse_mission_task_item(item: WorkItem) -> MissionTaskIds:
    if item.kind != MISSION_AGENT_TASK_KIND:
        raise MissionTaskJobError("Work item is not a mission agent task")
    if set(item.payload) != _PAYLOAD_KEYS:
        raise MissionTaskJobError(
            "Mission agent task payload must contain only entity identifiers"
        )
    try:
        ids = MissionTaskIds(
            mission_id=UUID(str(item.payload["mission_id"])),
            task_id=UUID(str(item.payload["task_id"])),
            agent_id=UUID(str(item.payload["agent_id"])),
        )
    except (TypeError, ValueError) as exc:
        raise MissionTaskJobError(
            "Mission agent task payload contains an invalid identifier"
        ) from exc
    if str(ids.mission_id) != item.mission_id:
        raise MissionTaskJobError("Mission agent task payload does not match its queue mission")
    return ids


def configured_process_worker_count(env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = str(source.get("SWARM_PROCESS_WORKERS", "0")).strip()
    try:
        count = int(raw or "0")
    except ValueError as exc:
        raise WorkerPoolError("SWARM_PROCESS_WORKERS must be an integer") from exc
    if count < 0 or count > MAX_PROCESS_WORKERS:
        raise WorkerPoolError(
            f"SWARM_PROCESS_WORKERS must be between 0 and {MAX_PROCESS_WORKERS}"
        )
    return count


def build_mission_worker_pool(
    database_path: str | os.PathLike[str],
    *,
    env: Mapping[str, str] | None = None,
) -> ProcessWorkerPool | None:
    count = configured_process_worker_count(env)
    if count == 0:
        return None
    return ProcessWorkerPool(
        Path(database_path),
        {MISSION_AGENT_TASK_KIND: "app.mission_jobs:execute_mission_agent_task"},
        process_count=count,
    )


def _find_entities(store, ids: MissionTaskIds) -> tuple[Mission, Task, AgentSpec]:
    mission = store.get_mission(ids.mission_id)
    if mission is None:
        raise MissionTaskJobError("Mission agent task references a missing mission")
    task = next((value for value in store.load_tasks(ids.mission_id)
                 if value.id == ids.task_id), None)
    agent = next((value for value in store.load_agents(ids.mission_id)
                  if value.id == ids.agent_id), None)
    if task is None or agent is None:
        raise MissionTaskJobError("Mission agent task references a missing task or agent")
    if task.mission_id != mission.id or agent.mission_id != mission.id or task.agent_id != agent.id:
        raise MissionTaskJobError("Mission agent task references inconsistent durable entities")
    return mission, task, agent


def _failure_details(exc: BaseException) -> tuple[str, FailureClass]:
    message = (str(exc).strip() or type(exc).__name__)[:1000]
    raw_class = getattr(exc, "failure_class", FailureClass.TOOL_FAILURE)
    try:
        failure_class = FailureClass(raw_class)
    except (TypeError, ValueError):
        failure_class = FailureClass.UNKNOWN_FAILURE
    return message, failure_class


async def _record_task_failure(runtime, ids: MissionTaskIds, exc: BaseException) -> None:
    mission, task, agent = _find_entities(runtime.store, ids)
    if mission.status in {
        MissionStatus.PAUSED,
        MissionStatus.STOPPED,
        MissionStatus.FAILED,
        MissionStatus.COMPLETED,
        MissionStatus.BLOCKED,
    } or task.status in {
        TaskStatus.STOPPED,
        TaskStatus.COMPLETED,
        TaskStatus.BLOCKED,
    } or agent.status in {
        AgentStatus.PAUSED,
        AgentStatus.STOPPED,
        AgentStatus.COMPLETED,
        AgentStatus.FAILED,
    }:
        return
    message, failure_class = _failure_details(exc)
    output = {"error": message, "failure_class": str(failure_class)}
    task.status = TaskStatus.FAILED
    task.output = output
    runtime.store.save_task(task)
    agent.output = output
    await runtime.agent_status(agent, AgentStatus.FAILED)
    await runtime.emit(
        mission.id,
        event_type_for_task(task.status),
        task.model_dump(mode="json"),
        agent.id,
    )


async def _execute_mission_agent_task(item: WorkItem, context: WorkerContext) -> dict:
    ids = parse_mission_task_item(item)
    mission, task, agent = _find_entities(context.store, ids)
    if mission.status not in {MissionStatus.RUNNING, MissionStatus.WAITING}:
        raise MissionTaskJobError("Mission is not runnable")
    if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        raise MissionTaskJobError("Mission task is not runnable")
    if agent.status not in {AgentStatus.CREATED, AgentStatus.RUNNING}:
        raise MissionTaskJobError("Mission agent is not runnable")

    # Lazy import avoids a module cycle.  This constructs provider/tool adapters
    # from the child process environment; none of that configuration is payload.
    from .runtime import PauseRequested, SwarmRuntime

    runtime = SwarmRuntime(
        context.store,
        durable_controls=True,
        durable_task_id=ids.task_id,
    )
    if not runtime._controller_configured():
        from .policy import PolicyError

        raise PolicyError(
            "No model provider is configured in the worker process",
            FailureClass.AUTHORIZATION_REQUIRED,
        )
    runtime.hydrate(mission.id)
    task = next(value for value in runtime.tasks[mission.id] if value.id == ids.task_id)
    agent = next(value for value in runtime.agents[mission.id] if value.id == ids.agent_id)
    try:
        await runtime._execute_task(mission, task, agent)
    except (asyncio.CancelledError, PauseRequested):
        raise
    except BaseException as exc:
        await _record_task_failure(runtime, ids, exc)
        raise

    _, saved_task, _ = _find_entities(context.store, ids)
    if saved_task.status not in {TaskStatus.COMPLETED, TaskStatus.BLOCKED}:
        raise MissionTaskJobError(
            "Mission agent task ended without a durable terminal task result"
        )
    return {
        "mission_id": str(ids.mission_id),
        "task_id": str(ids.task_id),
        "agent_id": str(ids.agent_id),
        "status": str(saved_task.status),
        "output": saved_task.output or {},
    }


def execute_mission_agent_task(item: WorkItem, context: WorkerContext) -> dict:
    """Spawn-safe ProcessWorkerPool entry point."""
    return asyncio.run(_execute_mission_agent_task(item, context))
