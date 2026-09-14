from __future__ import annotations

from enum import StrEnum

from .models import MissionStatus, TaskStatus


class UnknownEventType(ValueError):
    """New writes must use EventType. Unknown historical rows may still be read."""


class EventType(StrEnum):
    """Canonical mission event names. Values stay the dotted strings the UI already reads."""

    AGENT_SPAWNED = "agent.spawned"
    AGENT_UPDATED = "agent.updated"
    AGENT_MESSAGE = "agent.message"

    TASK_PENDING = "task.pending"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_STOPPED = "task.stopped"
    TASK_BLOCKED = "task.blocked"

    LLM_STARTED = "llm.started"
    LLM_COMPLETED = "llm.completed"
    LLM_FAILED = "llm.failed"
    LLM_RETRY = "llm.retry"
    LLM_FAILOVER = "llm.failover"

    MISSION_STARTED = "mission.started"
    MISSION_RESUMED = "mission.resumed"
    MISSION_WAITING = "mission.waiting"
    MISSION_RUNNING = "mission.running"
    MISSION_COMPLETED = "mission.completed"
    MISSION_FAILED = "mission.failed"
    MISSION_STOPPED = "mission.stopped"
    MISSION_SUSPENDED = "mission.suspended"
    MISSION_BLOCKED = "mission.blocked"
    MISSION_QUESTION = "mission.question"

    CONTROLLER_DECISION = "controller.decision"
    PLANNER_PROPOSAL = "planner.proposal"
    JUDGE_DECISION = "judge.decision"

    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"

    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"

    PAYMENT_CREATED = "payment.created"
    USER_ANSWERED = "user.answered"

    BUDGET_UPDATED = "budget.updated"
    BUDGET_WARNING = "budget.warning"

    LEASE_CLAIMED = "lease.claimed"
    LEASE_EXPIRED = "lease.expired"
    LEASE_RELEASED = "lease.released"


# controller.fallback is a test sentinel and must never be writable.
FORBIDDEN_EVENT_TYPES = frozenset({"controller.fallback"})

KNOWN_EVENT_TYPES = frozenset(member.value for member in EventType)

_TASK_STATUS_EVENTS = {
    TaskStatus.PENDING: EventType.TASK_PENDING,
    TaskStatus.RUNNING: EventType.TASK_STARTED,
    TaskStatus.COMPLETED: EventType.TASK_COMPLETED,
    TaskStatus.FAILED: EventType.TASK_FAILED,
    TaskStatus.STOPPED: EventType.TASK_STOPPED,
    TaskStatus.BLOCKED: EventType.TASK_BLOCKED,
}

_MISSION_STATUS_EVENTS = {
    MissionStatus.RUNNING: EventType.MISSION_RUNNING,
    MissionStatus.WAITING: EventType.MISSION_WAITING,
    MissionStatus.BLOCKED: EventType.MISSION_BLOCKED,
    MissionStatus.COMPLETED: EventType.MISSION_COMPLETED,
    MissionStatus.FAILED: EventType.MISSION_FAILED,
    MissionStatus.STOPPED: EventType.MISSION_STOPPED,
}


def parse_event_type(value: EventType | str) -> EventType:
    """Fail closed: only catalogued EventType values may be written."""
    if isinstance(value, EventType):
        if value.value in FORBIDDEN_EVENT_TYPES:
            raise UnknownEventType(f"Forbidden event type: {value.value}")
        return value
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise UnknownEventType("event_type must be a non-empty canonical string")
    if value in FORBIDDEN_EVENT_TYPES:
        raise UnknownEventType(f"Forbidden event type: {value}")
    try:
        return EventType(value)
    except ValueError as exc:
        raise UnknownEventType(f"Unknown event type: {value}") from exc


def coerce_event_type(value: str) -> str:
    """Read path: normalize known types; keep unknown historical strings."""
    if not isinstance(value, str) or not value:
        raise UnknownEventType("event_type is required")
    try:
        return parse_event_type(value).value
    except UnknownEventType:
        if value in FORBIDDEN_EVENT_TYPES or not value.strip():
            raise
        return value


def is_known_event_type(value: str) -> bool:
    return isinstance(value, str) and value in KNOWN_EVENT_TYPES


def is_task_event(value: str) -> bool:
    return isinstance(value, str) and value.startswith("task.")


def is_mission_event(value: str) -> bool:
    return isinstance(value, str) and value.startswith("mission.")


def event_suffix(value: str) -> str:
    return value.split(".", 1)[1] if "." in value else value


def task_status_from_event(value: str) -> str:
    suffix = event_suffix(value)
    return "running" if suffix == "started" else suffix


def event_type_for_task(status: TaskStatus | str) -> EventType:
    mapped = _TASK_STATUS_EVENTS.get(TaskStatus(status))
    if mapped is None:
        raise UnknownEventType(f"No event type for task status {status}")
    return mapped


def event_type_for_mission(status: MissionStatus | str) -> EventType:
    mapped = _MISSION_STATUS_EVENTS.get(MissionStatus(status))
    if mapped is None:
        raise UnknownEventType(f"No event type for mission status {status}")
    return mapped
