"""Durable mission objective seed.

The mission id is the objective identity when none was stored. Explicit
success criteria round-trip as written. Empty or missing criteria stay empty.
Progress is the mission status plus existing task counts. Nothing here marks
an objective complete.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from .models import FailureClass, Mission, MissionStatus, Task, TaskStatus

MAX_CRITERIA = 20
MAX_CRITERION_CHARS = 400
MAX_CRITERIA_CHARS = 4000


class ObjectiveError(Exception):
    """Fail-closed objective read or write. Does not invent criteria or completion."""

    def __init__(self, message: str, failure_class: FailureClass = FailureClass.INVALID_OUTPUT):
        super().__init__(message)
        self.failure_class = failure_class


def normalize_success_criteria(value: Any) -> list[str]:
    """Return explicit criteria. None is empty. Anything else malformed fails closed."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ObjectiveError("Success criteria must be a list", FailureClass.INVALID_OUTPUT)
    if len(value) > MAX_CRITERIA:
        raise ObjectiveError("Success criteria exceed the count cap", FailureClass.CONTEXT_LIMIT)
    criteria: list[str] = []
    total = 0
    for item in value:
        if not isinstance(item, str):
            raise ObjectiveError("Each success criterion must be text", FailureClass.INVALID_OUTPUT)
        text = item.strip()
        if not text:
            raise ObjectiveError("Success criteria must not contain an empty marker", FailureClass.INVALID_OUTPUT)
        if len(text) > MAX_CRITERION_CHARS:
            raise ObjectiveError("A success criterion exceeds the size cap", FailureClass.CONTEXT_LIMIT)
        total += len(text)
        if total > MAX_CRITERIA_CHARS:
            raise ObjectiveError("Success criteria exceed the size cap", FailureClass.CONTEXT_LIMIT)
        criteria.append(text)
    return criteria


def load_objective_id(mission_id: UUID, payload_id: UUID | None, column_id: str | None) -> UUID:
    """Column wins when present. A missing id is the mission id — never a new random id."""
    parsed: UUID | None = None
    if column_id is not None and str(column_id).strip():
        try:
            parsed = UUID(str(column_id))
        except ValueError:
            raise ObjectiveError("Durable objective identity is corrupt", FailureClass.INVALID_OUTPUT) from None
    if parsed is not None and payload_id is not None and parsed != payload_id:
        raise ObjectiveError(
            "Durable objective identity does not match the mission payload",
            FailureClass.INVALID_OUTPUT,
        )
    if parsed is not None:
        return parsed
    if payload_id is not None:
        return payload_id
    return mission_id


def load_success_criteria(payload_criteria: Any, column_text: str | None) -> list[str]:
    """SQL NULL means legacy/empty-from-payload. A stored value must parse and match."""
    payload_norm = normalize_success_criteria(payload_criteria)
    if column_text is None:
        return payload_norm
    if not isinstance(column_text, str) or not column_text.strip():
        raise ObjectiveError("Durable success criteria are corrupt", FailureClass.INVALID_OUTPUT)
    try:
        raw = json.loads(column_text)
    except json.JSONDecodeError:
        raise ObjectiveError("Durable success criteria are corrupt", FailureClass.INVALID_OUTPUT) from None
    if raw is None:
        column_norm: list[str] = []
    else:
        column_norm = normalize_success_criteria(raw)
    if column_norm != payload_norm:
        raise ObjectiveError(
            "Durable success criteria do not match the mission payload",
            FailureClass.INVALID_OUTPUT,
        )
    return column_norm


def prepare_objective(mission: Mission) -> list[str]:
    """Validate criteria and bind a missing identity to the mission id."""
    criteria = normalize_success_criteria(mission.success_criteria)
    mission.success_criteria = criteria
    if mission.objective_id is None:
        mission.objective_id = mission.id
    return criteria


def mission_payload(mission: Mission) -> str:
    """Persist mission fields without the computed objective projection."""
    return mission.model_dump_json(exclude={"objective"})


def objective_view(mission: Mission, tasks: list[Task] | None = None) -> dict[str, Any]:
    """Projection the mission API and runtime already return. Does not write completion."""
    criteria = normalize_success_criteria(mission.success_criteria)
    mission.success_criteria = criteria
    identity = mission.objective_id or mission.id
    task_list = list(tasks or [])
    tasks_completed = sum(1 for task in task_list if task.status == TaskStatus.COMPLETED)
    return {
        "id": str(identity),
        "goal": mission.goal,
        "success_criteria": list(criteria),
        "acceptance_markers": [{"text": item, "accepted": False} for item in criteria],
        "progress": {
            "status": str(mission.status),
            "tasks_completed": tasks_completed,
            "tasks_total": len(task_list),
            "complete": mission.status == MissionStatus.COMPLETED,
        },
    }
