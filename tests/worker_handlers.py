from __future__ import annotations

import os
import time
from uuid import UUID

from app.models import AgentStatus, FailureClass, TaskStatus
from app.queue import WorkItem
from app.workers import WorkerContext


def echo(item: WorkItem) -> dict:
    return {
        "text": item.payload.get("text"),
        "pid": os.getpid(),
        "attempt": item.attempt,
    }


def slow_echo(item: WorkItem) -> dict:
    time.sleep(float(item.payload.get("sleep_seconds", 0.5)))
    return echo(item)


def fail(item: WorkItem) -> dict:
    raise RuntimeError(str(item.payload.get("error") or "handler failed"))


def context_echo(item: WorkItem, context: WorkerContext) -> dict:
    return {
        "database_path": context.database_path,
        "owner_id": context.owner_id,
        "pid": os.getpid(),
    }


def authorization_failure(item: WorkItem, context: WorkerContext) -> dict:
    _ = item, context
    error = RuntimeError("worker provider is unconfigured")
    error.failure_class = FailureClass.AUTHORIZATION_REQUIRED
    raise error


def complete_mission_task(item: WorkItem, context: WorkerContext) -> dict:
    mission_id = UUID(str(item.payload["mission_id"]))
    task_id = UUID(str(item.payload["task_id"]))
    agent_id = UUID(str(item.payload["agent_id"]))
    task = next(value for value in context.store.load_tasks(mission_id) if value.id == task_id)
    agent = next(value for value in context.store.load_agents(mission_id) if value.id == agent_id)
    output = {"status": "completed", "finding": "completed in process worker"}
    task.status = TaskStatus.COMPLETED
    task.output = output
    agent.status = AgentStatus.COMPLETED
    agent.output = output
    context.store.save_task(task)
    context.store.save_agent(agent)
    return {
        "mission_id": str(mission_id),
        "task_id": str(task_id),
        "agent_id": str(agent_id),
        "status": str(task.status),
        "output": output,
    }
