from uuid import uuid4

import pytest
from sqlalchemy import text

from app.events import (
    FORBIDDEN_EVENT_TYPES,
    KNOWN_EVENT_TYPES,
    EventType,
    UnknownEventType,
    coerce_event_type,
    event_type_for_mission,
    event_type_for_task,
    is_known_event_type,
    is_mission_event,
    is_task_event,
    parse_event_type,
    task_status_from_event,
)
from app.llm import FallbackController
from app.models import Mission, MissionEvent, MissionStatus, TaskStatus
from app.runtime import SwarmRuntime
from app.store import Store

# Names the vanilla JS HUD / activity / alerts already switch on. Wire values must stay identical.
UI_EVENT_TYPES = {
    "agent.spawned",
    "agent.updated",
    "agent.message",
    "task.pending",
    "task.started",
    "task.completed",
    "task.failed",
    "task.stopped",
    "task.blocked",
    "llm.started",
    "llm.completed",
    "llm.failed",
    "llm.retry",
    "llm.failover",
    "mission.started",
    "mission.resumed",
    "mission.waiting",
    "mission.running",
    "mission.completed",
    "mission.failed",
    "mission.stopped",
    "mission.suspended",
    "mission.blocked",
    "mission.question",
    "controller.decision",
    "planner.proposal",
    "judge.decision",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "verification.started",
    "verification.passed",
    "verification.failed",
    "payment.created",
    "user.answered",
    "lease.claimed",
    "lease.expired",
    "lease.released",
}


def test_event_type_values_match_historical_ui_strings():
    assert {member.value for member in EventType} == UI_EVENT_TYPES == KNOWN_EVENT_TYPES
    assert EventType.AGENT_SPAWNED == "agent.spawned"
    assert EventType.MISSION_FAILED == "mission.failed"
    assert EventType.LLM_RETRY == "llm.retry"
    assert EventType.LLM_FAILOVER == "llm.failover"
    assert EventType.VERIFICATION_STARTED == "verification.started"
    assert EventType.VERIFICATION_PASSED == "verification.passed"
    assert EventType.VERIFICATION_FAILED == "verification.failed"
    assert EventType.MISSION_QUESTION == "mission.question"
    assert EventType.USER_ANSWERED == "user.answered"
    assert EventType.TOOL_COMPLETED == "tool.completed"
    assert EventType.LEASE_CLAIMED == "lease.claimed"
    assert EventType.LEASE_EXPIRED == "lease.expired"
    assert EventType.LEASE_RELEASED == "lease.released"
    assert "controller.fallback" not in KNOWN_EVENT_TYPES
    assert FORBIDDEN_EVENT_TYPES == {"controller.fallback"}


def test_parse_event_type_accepts_enum_and_string():
    assert parse_event_type(EventType.AGENT_SPAWNED) is EventType.AGENT_SPAWNED
    assert parse_event_type("llm.retry") is EventType.LLM_RETRY
    assert parse_event_type("verification.failed") is EventType.VERIFICATION_FAILED


@pytest.mark.parametrize("value", [
    "controller.fallback",
    "not.a.type",
    "AGENT_SPAWNED",
    "agent.spawned ",
    " agent.spawned",
    "",
    "   ",
    "task.running",
    "mission.pending",
])
def test_parse_event_type_fails_closed_on_unknown(value):
    with pytest.raises(UnknownEventType):
        parse_event_type(value)


def test_coerce_preserves_unknown_historical_types():
    assert coerce_event_type("agent.spawned") == EventType.AGENT_SPAWNED
    assert coerce_event_type("legacy.custom") == "legacy.custom"
    assert not is_known_event_type("legacy.custom")
    with pytest.raises(UnknownEventType):
        coerce_event_type("controller.fallback")
    with pytest.raises(UnknownEventType):
        coerce_event_type("")


def test_task_and_mission_status_mapping_is_fail_closed():
    assert event_type_for_task(TaskStatus.PENDING) is EventType.TASK_PENDING
    assert event_type_for_task(TaskStatus.RUNNING) is EventType.TASK_STARTED
    assert event_type_for_task("completed") is EventType.TASK_COMPLETED
    assert event_type_for_task(TaskStatus.BLOCKED) is EventType.TASK_BLOCKED
    assert event_type_for_mission(MissionStatus.FAILED) is EventType.MISSION_FAILED
    assert event_type_for_mission(MissionStatus.BLOCKED) is EventType.MISSION_BLOCKED
    assert event_type_for_mission("completed") is EventType.MISSION_COMPLETED
    with pytest.raises(UnknownEventType):
        event_type_for_mission(MissionStatus.PENDING)
    assert is_task_event("task.started")
    assert is_mission_event(EventType.MISSION_FAILED)
    assert task_status_from_event("task.started") == "running"
    assert task_status_from_event(EventType.MISSION_FAILED) == "failed"


def test_store_append_rejects_unknown_and_writes_canonical_string(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission_id = uuid4()
    with pytest.raises(UnknownEventType):
        store.append(MissionEvent(mission_id=mission_id, event_type="controller.fallback", payload={}))
    with pytest.raises(UnknownEventType):
        store.append(MissionEvent(mission_id=mission_id, event_type="org.changed", payload={}))
    assert store.events(mission_id) == []

    written = store.append(MissionEvent(
        mission_id=mission_id, event_type=EventType.MISSION_FAILED,
        payload={"error": "no", "failure_class": "PROVIDER_OUTAGE"},
    ))
    assert written.event_type == "mission.failed"
    assert isinstance(written.event_type, str)
    dumped = written.model_dump(mode="json")
    assert dumped["event_type"] == "mission.failed"
    assert dumped["payload"] == {"error": "no", "failure_class": "PROVIDER_OUTAGE"}
    assert "schema_version" not in dumped


@pytest.mark.asyncio
async def test_runtime_emit_unknown_type_writes_nothing(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Keep the event log honest")
    store.save_mission(mission)
    with pytest.raises(UnknownEventType):
        await runtime.emit(mission.id, "controller.fallback", {"reason": "should not persist"})
    assert store.events(mission.id) == []


def test_store_reads_unknown_historical_event_without_rewriting(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(goal="Legacy row must still replay")
    store.save_mission(mission)
    with store.sessions.begin() as db:
        db.execute(text(
            "INSERT INTO mission_events (mission_id, event_type, actor_id, payload, created_at) "
            "VALUES (:mission_id, :event_type, NULL, :payload, :created_at)"
        ), {
            "mission_id": str(mission.id),
            "event_type": "legacy.custom",
            "payload": '{"note": "pre-schema"}',
            "created_at": mission.created_at,
        })
    events = store.events(mission.id)
    assert len(events) == 1
    assert events[0].event_type == "legacy.custom"
    assert events[0].payload == {"note": "pre-schema"}
    projected = store.project_events(mission.id)
    assert projected["agents"] == []
    assert projected["tasks"] == []


def test_project_events_still_understands_historical_strings(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(goal="Backfill from typed historical names")
    store.save_mission(mission)
    agent_id = str(uuid4())
    task_id = str(uuid4())
    store.append(MissionEvent(
        mission_id=mission.id, event_type="agent.spawned",
        payload={"id": agent_id, "role": "researcher", "status": "created",
                 "mission_id": str(mission.id), "purpose": "look", "capabilities": [], "depth": 1},
    ))
    store.append(MissionEvent(
        mission_id=mission.id, event_type="task.started",
        payload={"id": task_id, "agent_id": agent_id, "title": "Look",
                 "description": "look", "mission_id": str(mission.id)},
    ))
    store.append(MissionEvent(
        mission_id=mission.id, event_type="mission.failed",
        payload={"error": "stopped mid-flight", "failure_class": "TIMEOUT"},
    ))
    projected = store.project_events(mission.id)
    assert projected["agents"][0]["id"] == agent_id
    assert projected["agents"][0]["status"] == "failed"
    assert projected["tasks"][0]["id"] == task_id
    assert projected["tasks"][0]["status"] == "running"


@pytest.mark.asyncio
async def test_completed_mission_emits_only_known_ui_strings(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await runtime.run(mission)
    events = store.events(mission.id)
    types = [event.event_type for event in events]
    assert types
    assert all(is_known_event_type(event_type) for event_type in types)
    assert "controller.fallback" not in types
    assert "mission.completed" in types
    assert "agent.spawned" in types
    assert "verification.started" in types
    dumped = events[0].model_dump(mode="json")
    assert dumped["event_type"] in KNOWN_EVENT_TYPES
    assert isinstance(dumped["event_type"], str)
