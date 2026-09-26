"""Durable objective identity and explicit success criteria survive reload."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.llm import LLMProvider
from app.models import (
    AgentSpec, FailureClass, Mission, MissionStatus, Task, TaskStatus,
)
from app.objective import ObjectiveError, normalize_success_criteria
from app.policy import PolicyError
from app.runtime import SwarmRuntime
from app.store import Store


def _status_in_payload(store: Store, mission_id) -> str:
    with store.engine.connect() as conn:
        raw = conn.execute(
            text("SELECT payload FROM missions WHERE id = :id"),
            {"id": str(mission_id)},
        ).scalar_one()
    return json.loads(raw)["status"]


def test_objective_round_trips_across_store_restart(tmp_path):
    path = tmp_path / "objective.db"
    store = Store(str(path))
    mission = Mission(
        goal="Publish the notes",
        status=MissionStatus.RUNNING,
        success_criteria=["  includes a summary  ", "names the sources"],
    )
    store.save_mission(mission)
    agent_id = uuid4()
    store.save_task(Task(
        mission_id=mission.id, agent_id=agent_id, title="Draft", description="Write",
        status=TaskStatus.COMPLETED,
    ))
    store.save_task(Task(
        mission_id=mission.id, agent_id=agent_id, title="Review", description="Check",
        status=TaskStatus.PENDING,
    ))

    loaded = Store(str(path)).get_mission(mission.id)
    assert loaded is not None
    assert loaded.objective_id == mission.id
    assert loaded.goal == "Publish the notes"
    assert loaded.success_criteria == ["includes a summary", "names the sources"]
    assert loaded.status == MissionStatus.RUNNING
    assert loaded.objective["id"] == str(mission.id)
    assert loaded.objective["goal"] == "Publish the notes"
    assert loaded.objective["success_criteria"] == loaded.success_criteria
    assert loaded.objective["acceptance_markers"] == [
        {"text": "includes a summary", "accepted": False},
        {"text": "names the sources", "accepted": False},
    ]
    assert loaded.objective["progress"] == {
        "status": "running",
        "tasks_completed": 1,
        "tasks_total": 2,
        "complete": False,
    }

    loaded.success_criteria = ["only the summary"]
    Store(str(path)).save_mission(loaded)
    updated = Store(str(path)).get_mission(mission.id)
    assert updated.objective_id == mission.id
    assert updated.success_criteria == ["only the summary"]
    assert updated.status == MissionStatus.RUNNING
    assert updated.objective["progress"]["complete"] is False


def test_empty_and_legacy_criteria_stay_empty(tmp_path):
    path = tmp_path / "empty.db"
    store = Store(str(path))
    mission = Mission(goal="Finish the report and send it", status=MissionStatus.RUNNING)
    store.save_mission(mission)
    with store.engine.begin() as conn:
        payload = json.loads(conn.execute(
            text("SELECT payload FROM missions WHERE id = :id"),
            {"id": str(mission.id)},
        ).scalar_one())
        payload.pop("objective_id", None)
        payload.pop("success_criteria", None)
        payload.pop("objective", None)
        conn.execute(
            text(
                "UPDATE missions SET objective_id = NULL, success_criteria = NULL, payload = :payload "
                "WHERE id = :id"
            ),
            {"id": str(mission.id), "payload": json.dumps(payload)},
        )

    loaded = Store(str(path)).get_mission(mission.id)
    assert loaded.objective_id == mission.id
    assert loaded.success_criteria == []
    assert loaded.objective["success_criteria"] == []
    assert loaded.objective["acceptance_markers"] == []
    assert loaded.status == MissionStatus.RUNNING
    assert loaded.objective["progress"]["complete"] is False
    assert normalize_success_criteria(None) == []


def test_corrupt_or_oversize_criteria_fail_closed_without_completion(tmp_path):
    path = tmp_path / "corrupt.db"
    store = Store(str(path))
    mission = Mission(
        goal="Stay unfinished",
        status=MissionStatus.RUNNING,
        success_criteria=["a real summary"],
    )
    store.save_mission(mission)

    with store.engine.begin() as conn:
        conn.execute(
            text("UPDATE missions SET success_criteria = '{' WHERE id = :id"),
            {"id": str(mission.id)},
        )
    with pytest.raises(ObjectiveError) as corrupt:
        store.get_mission(mission.id)
    assert corrupt.value.failure_class == FailureClass.INVALID_OUTPUT
    assert _status_in_payload(store, mission.id) == "running"

    with store.engine.begin() as conn:
        conn.execute(
            text("UPDATE missions SET success_criteria = :criteria WHERE id = :id"),
            {"id": str(mission.id), "criteria": json.dumps(["x" * 401])},
        )
    with pytest.raises(ObjectiveError) as oversize:
        store.get_mission(mission.id)
    assert oversize.value.failure_class == FailureClass.CONTEXT_LIMIT
    assert _status_in_payload(store, mission.id) == "running"

    with store.engine.begin() as conn:
        conn.execute(
            text("UPDATE missions SET success_criteria = :criteria, objective_id = 'not-a-uuid' WHERE id = :id"),
            {"id": str(mission.id), "criteria": json.dumps(["a real summary"])},
        )
    with pytest.raises(ObjectiveError) as identity:
        store.get_mission(mission.id)
    assert identity.value.failure_class == FailureClass.INVALID_OUTPUT
    assert _status_in_payload(store, mission.id) == "running"

    fresh = Mission(goal="Do not store this", success_criteria=["y" * 401])
    with pytest.raises(ObjectiveError) as rejected:
        store.save_mission(fresh)
    assert rejected.value.failure_class == FailureClass.CONTEXT_LIMIT
    assert store.get_mission(fresh.id) is None
    with pytest.raises(ObjectiveError) as bad_shape:
        normalize_success_criteria("invent a criterion from this sentence")
    assert bad_shape.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(ObjectiveError) as empty_item:
        normalize_success_criteria(["ok", "  "])
    assert empty_item.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(ObjectiveError) as too_many:
        normalize_success_criteria(["marker"] * 21)
    assert too_many.value.failure_class == FailureClass.CONTEXT_LIMIT


def test_objective_identity_is_immutable(tmp_path):
    store = Store(str(tmp_path / "identity.db"))
    mission = Mission(goal="Keep the same objective", status=MissionStatus.PENDING, success_criteria=["one"])
    store.save_mission(mission)
    loaded = store.get_mission(mission.id)
    loaded.objective_id = uuid4()
    with pytest.raises(ObjectiveError) as exc:
        store.save_mission(loaded)
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT
    again = store.get_mission(mission.id)
    assert again.objective_id == mission.id
    assert again.status == MissionStatus.PENDING
    assert again.success_criteria == ["one"]
    assert again.objective["progress"]["complete"] is False


def test_completed_mission_stays_completed_without_accepting_criteria(tmp_path):
    store = Store(str(tmp_path / "done.db"))
    mission = Mission(
        goal="Already finished",
        status=MissionStatus.COMPLETED,
        success_criteria=["shipped"],
    )
    store.save_mission(mission)
    loaded = Store(str(tmp_path / "done.db")).get_mission(mission.id)
    assert loaded.status == MissionStatus.COMPLETED
    assert loaded.objective["progress"]["complete"] is True
    assert loaded.objective["acceptance_markers"] == [{"text": "shipped", "accepted": False}]


def test_runtime_state_reads_persisted_criteria_and_does_not_complete(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    mission = Mission(
        goal="Keep going",
        status=MissionStatus.RUNNING,
        success_criteria=["a real summary"],
    )
    store.save_mission(mission)
    runtime = SwarmRuntime(store, controller=LLMProvider())
    runtime.hydrate(mission.id)
    loaded = store.get_mission(mission.id)
    state = runtime._state(loaded)
    assert state["goal"] == "Keep going"
    assert state["success_criteria"] == ["a real summary"]
    assert state["objective"]["id"] == str(mission.id)
    assert state["objective"]["progress"]["complete"] is False
    assert loaded.status == MissionStatus.RUNNING


@pytest.mark.asyncio
async def test_finish_verification_reads_criteria_without_completing(tmp_path):
    store = Store(str(tmp_path / "verify.db"))
    mission = Mission(
        goal="Keep going",
        status=MissionStatus.RUNNING,
        success_criteria=["a real summary"],
    )
    store.save_mission(mission)
    root = AgentSpec(mission_id=mission.id, role="mission_controller", purpose="Coordinate")

    class Capture(LLMProvider):
        def __init__(self):
            self.seen = None

        async def verify(self, state, claim):
            self.seen = state
            return {"verdict": "pass", "rationale": "grounded in the artifact", "evidence": ["summary"]}

    capture = Capture()
    runtime = SwarmRuntime(store, controller=capture)
    await runtime._verify_finish(mission, root, {"summary": "grounded in the artifact"})
    assert capture.seen["success_criteria"] == ["a real summary"]
    assert capture.seen["objective"]["progress"]["complete"] is False
    reloaded = store.get_mission(mission.id)
    assert reloaded.status == MissionStatus.RUNNING
    assert reloaded.objective["progress"]["complete"] is False
    assert reloaded.success_criteria == ["a real summary"]


@pytest.mark.asyncio
async def test_corrupt_criteria_block_verification(tmp_path):
    store = Store(str(tmp_path / "block.db"))
    mission = Mission(goal="Keep going", status=MissionStatus.RUNNING, success_criteria=["ok"])
    store.save_mission(mission)
    mission.success_criteria = ["x" * 401]
    root = AgentSpec(mission_id=mission.id, role="mission_controller", purpose="Coordinate")
    runtime = SwarmRuntime(store, controller=LLMProvider())
    with pytest.raises(PolicyError) as exc:
        await runtime._verify_finish(mission, root, {"summary": "not saved"})
    assert exc.value.failure_class == FailureClass.CONTEXT_LIMIT
    assert store.get_mission(mission.id).status == MissionStatus.RUNNING
    assert store.get_mission(mission.id).success_criteria == ["ok"]
