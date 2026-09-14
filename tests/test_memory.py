from uuid import uuid4

import pytest
from sqlalchemy import text

from app.memory import (
    MAX_NOTE_CHARS, MAX_RECALL_CHARS, MemoryError, StoreMemoryProvider,
)
from app.models import FailureClass, Mission, MissionStatus
from app.policy import PolicyError
from app.runtime import SwarmRuntime
from app.store import Store


def _provider(tmp_path, name="memory.db", **kwargs) -> tuple[Store, StoreMemoryProvider]:
    store = Store(str(tmp_path / name))
    return store, StoreMemoryProvider(store, **kwargs)


def test_write_and_read_mission_notes(tmp_path):
    store, memory = _provider(tmp_path)
    mission = Mission(goal="remember this")
    store.save_mission(mission)
    first = memory.remember(mission.id, " Prefer sequential review. ")
    second = memory.remember(mission.id, "Do not invent evidence.")
    notes = memory.recall(mission.id)
    assert [note.body for note in notes] == ["Prefer sequential review.", "Do not invent evidence."]
    assert all(note.agent_id is None and note.scope == "mission" for note in notes)
    assert {note.id for note in notes} == {first.id, second.id}
    public = notes[0].public_dict()
    assert public["body"] == "Prefer sequential review."
    assert public["scope"] == "mission"
    assert public["agent_id"] is None


def test_scope_isolation_across_missions_and_agents(tmp_path):
    store, memory = _provider(tmp_path)
    alpha = Mission(goal="alpha")
    beta = Mission(goal="beta")
    store.save_mission(alpha)
    store.save_mission(beta)
    agent_a = uuid4()
    agent_b = uuid4()
    memory.remember(alpha.id, "mission alpha")
    memory.remember(alpha.id, "agent a note", agent_id=agent_a)
    memory.remember(alpha.id, "agent b note", agent_id=agent_b)
    memory.remember(beta.id, "mission beta")
    memory.remember(beta.id, "beta agent", agent_id=agent_a)

    mission_only = memory.recall(alpha.id)
    assert [note.body for note in mission_only] == ["mission alpha"]

    for_a = memory.recall(alpha.id, agent_id=agent_a)
    assert [note.body for note in for_a] == ["mission alpha", "agent a note"]

    for_b = memory.recall(alpha.id, agent_id=agent_b)
    assert [note.body for note in for_b] == ["mission alpha", "agent b note"]

    beta_notes = memory.recall(beta.id)
    assert [note.body for note in beta_notes] == ["mission beta"]
    assert memory.recall(uuid4()) == []


def test_empty_and_oversize_writes_fail_closed(tmp_path):
    _, memory = _provider(tmp_path)
    mission_id = uuid4()
    with pytest.raises(MemoryError) as empty:
        memory.remember(mission_id, "   ")
    assert empty.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(MemoryError) as oversize:
        memory.remember(mission_id, "x" * (MAX_NOTE_CHARS + 1))
    assert oversize.value.failure_class == FailureClass.CONTEXT_LIMIT
    assert memory.recall(mission_id) == []


def test_recall_bounds_to_newest_notes_under_cap(tmp_path):
    _, memory = _provider(tmp_path)
    mission_id = uuid4()
    memory.remember(mission_id, "aaaa")
    memory.remember(mission_id, "bbbb")
    memory.remember(mission_id, "cccc")
    bounded = memory.recall(mission_id, max_chars=8)
    assert [note.body for note in bounded] == ["bbbb", "cccc"]


def test_recall_fails_closed_when_a_note_exceeds_the_cap(tmp_path):
    _, memory = _provider(tmp_path)
    mission_id = uuid4()
    memory.remember(mission_id, "too-big-to-fit")
    with pytest.raises(MemoryError) as exc:
        memory.recall(mission_id, max_chars=4)
    assert exc.value.failure_class == FailureClass.CONTEXT_LIMIT
    with pytest.raises(MemoryError) as tokens:
        memory.recall(mission_id, max_tokens=0)
    assert tokens.value.failure_class == FailureClass.CONTEXT_LIMIT


def test_corrupt_row_fails_closed_and_does_not_invent(tmp_path):
    store, memory = _provider(tmp_path)
    mission_id = uuid4()
    memory.remember(mission_id, "good note")
    with store.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO memory_notes (id, mission_id, agent_id, body, created_at) "
            "VALUES ('not-a-uuid', :mission_id, NULL, 'corrupt', '2026-01-01T00:00:00')"
        ), {"mission_id": str(mission_id)})
    with pytest.raises(MemoryError) as exc:
        memory.recall(mission_id)
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT


def test_oversize_persisted_row_fails_closed(tmp_path):
    store, memory = _provider(tmp_path)
    mission_id = uuid4()
    with store.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO memory_notes (id, mission_id, agent_id, body, created_at) "
            "VALUES (:id, :mission_id, NULL, :body, '2026-01-01T00:00:00')"
        ), {"id": str(uuid4()), "mission_id": str(mission_id), "body": "z" * (MAX_NOTE_CHARS + 1)})
    with pytest.raises(MemoryError) as exc:
        memory.recall(mission_id)
    assert exc.value.failure_class == FailureClass.CONTEXT_LIMIT


def test_notes_persist_across_store_restart(tmp_path):
    path = str(tmp_path / "persist.db")
    mission = Mission(goal="survive restart", status=MissionStatus.RUNNING)
    first = Store(path)
    memory = StoreMemoryProvider(first)
    agent_id = uuid4()
    memory.remember(mission.id, "mission fact")
    memory.remember(mission.id, "agent fact", agent_id=agent_id)
    first.engine.dispose()

    restored = StoreMemoryProvider(Store(path))
    assert [note.body for note in restored.recall(mission.id)] == ["mission fact"]
    assert [note.body for note in restored.recall(mission.id, agent_id=agent_id)] == [
        "mission fact", "agent fact",
    ]


def test_runtime_reads_bounded_memory_into_state(tmp_path):
    store, _ = _provider(tmp_path, name="runtime.db")
    runtime = SwarmRuntime(store)
    mission = Mission(goal="use memory")
    store.save_mission(mission)
    agent_id = uuid4()
    runtime.remember(mission, "shared fact")
    runtime.remember(mission, "private fact", agent_id=agent_id)
    controller_state = runtime._state(mission)
    assert controller_state["memory"][0]["body"] == "shared fact"
    assert [item["body"] for item in controller_state["memory"]] == ["shared fact"]
    worker_state = runtime._state(mission, agent_id)
    assert [item["body"] for item in worker_state["memory"]] == ["shared fact", "private fact"]
    empty = SwarmRuntime(store, memory=None)
    assert empty._state(mission)["memory"] == []


def test_runtime_remember_and_state_fail_closed_on_oversize(tmp_path):
    store = Store(str(tmp_path / "cap.db"))
    runtime = SwarmRuntime(store)
    mission = Mission(goal="cap")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as write:
        runtime.remember(mission, "n" * (MAX_NOTE_CHARS + 1))
    assert write.value.failure_class == FailureClass.CONTEXT_LIMIT
    runtime.remember(mission, "fits")
    tight = SwarmRuntime(store, memory=StoreMemoryProvider(store, max_recall_chars=2))
    with pytest.raises(PolicyError) as read:
        tight._state(mission)
    assert read.value.failure_class == FailureClass.CONTEXT_LIMIT


def test_health_is_sqlite_and_does_not_invent(tmp_path):
    _, memory = _provider(tmp_path)
    health = memory.health()
    assert health.provider == "sqlite"
    assert health.status == "healthy"
    assert health.configured is True
    assert MAX_RECALL_CHARS >= MAX_NOTE_CHARS
