from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.memory import (
    MAX_NOTE_CHARS, MAX_RECALL_CHARS, SUMMARY_MARKER, MemoryError, StoreMemoryProvider,
)
from app.models import FailureClass, Mission, MissionStatus
from app.policy import PolicyError
from app.runtime import SwarmRuntime
from app.store import MemoryNoteRow, Store


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
    assert "opt-in" in (health.detail or "")
    assert MAX_RECALL_CHARS >= MAX_NOTE_CHARS


def _bodies(store: Store, mission_id) -> list[str]:
    with store.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT body FROM memory_notes WHERE mission_id = :mission_id"
        ), {"mission_id": str(mission_id)}).scalars()
        return list(rows)


def _stamp(store: Store, note_id, second: int) -> None:
    with store.sessions.begin() as db:
        row = db.get(MemoryNoteRow, str(note_id))
        row.created_at = datetime(2026, 1, 1, 0, 0, second, tzinfo=timezone.utc)


def _assert_extractive(summary_body: str, source_bodies: list[str]) -> None:
    assert summary_body.startswith(SUMMARY_MARKER)
    excerpt = summary_body[len(SUMMARY_MARKER):]
    joined = "\n".join(source_bodies)
    assert joined.startswith(excerpt)
    assert excerpt.strip()
    for invented in ("completed", "success", "passed", "failed", "tool result"):
        assert invented not in summary_body.lower()


def test_summarize_is_opt_in_and_empty_store_stays_empty(tmp_path):
    _, memory = _provider(tmp_path)
    mission_id = uuid4()
    memory.remember(mission_id, "alpha fact")
    memory.remember(mission_id, "beta fact")
    with pytest.raises(MemoryError) as exc:
        memory.summarize(mission_id)
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT
    assert [note.body for note in memory.recall(mission_id)] == ["alpha fact", "beta fact"]
    assert memory.summarize(uuid4(), max_chars=64) is None
    assert memory.recall(uuid4()) == []
    under = memory.summarize(mission_id, max_chars=64)
    assert under is None
    assert [note.body for note in memory.recall(mission_id)] == ["alpha fact", "beta fact"]


def test_summarize_when_over_bound_keeps_newest_and_extracts_older_text(tmp_path):
    store, memory = _provider(tmp_path, max_recall_chars=23)
    mission_id = uuid4()
    oldest = memory.remember(mission_id, "A")
    middle = memory.remember(mission_id, "B" * 13)
    newest = memory.remember(mission_id, "C" * 10)
    _stamp(store, oldest.id, 1)
    _stamp(store, middle.id, 2)
    _stamp(store, newest.id, 3)
    summary = memory.summarize(mission_id, max_chars=23)
    assert summary is not None
    assert summary.id == oldest.id
    _assert_extractive(summary.body, ["A", "B" * 13])
    assert "B" in summary.body
    assert "C" not in summary.body
    recalled = memory.recall(mission_id)
    assert [note.body for note in recalled] == [summary.body, "C" * 10]
    assert sum(len(note.body) for note in recalled) == 23


def test_auto_summarize_trigger_and_runtime_cap_counts_summary(tmp_path):
    store, memory = _provider(tmp_path, max_recall_chars=23, summarize_over_chars=23)
    mission = Mission(goal="summarize recall")
    store.save_mission(mission)
    runtime = SwarmRuntime(store, memory=memory)
    first = runtime.remember(mission, "A")
    second = runtime.remember(mission, "B" * 13)
    _stamp(store, first.id, 1)
    _stamp(store, second.id, 2)
    kept = runtime.remember(mission, "C" * 10)
    assert kept.body == "C" * 10
    state = runtime._state(mission)
    bodies = [item["body"] for item in state["memory"]]
    assert any(body.startswith(SUMMARY_MARKER) for body in bodies)
    assert sum(len(body) for body in bodies) <= memory.max_recall_chars
    assert sum(len(body) for body in bodies) == sum(len(note.body) for note in memory.recall(mission.id))
    summary_body = next(body for body in bodies if body.startswith(SUMMARY_MARKER))
    _assert_extractive(summary_body, ["A", "B" * 13])
    assert "C" * 10 in bodies


def test_summarize_isolates_mission_and_agent_scopes(tmp_path):
    store, memory = _provider(tmp_path)
    alpha = uuid4()
    beta = uuid4()
    agent_a = uuid4()
    agent_b = uuid4()
    oldest = memory.remember(alpha, "A")
    middle = memory.remember(alpha, "B" * 13)
    newest = memory.remember(alpha, "C" * 10)
    _stamp(store, oldest.id, 1)
    _stamp(store, middle.id, 2)
    _stamp(store, newest.id, 3)
    agent_only = memory.remember(alpha, "AGENTONLY", agent_id=agent_a)
    other_agent = memory.remember(alpha, "OTHERAGENT", agent_id=agent_b)
    memory.remember(beta, "OTHERMISSION")
    summary = memory.summarize(alpha, max_chars=23)
    assert summary is not None
    for token in ("AGENTONLY", "OTHERAGENT", "OTHERMISSION"):
        assert token not in summary.body
    mission_bodies = [note.body for note in memory.recall(alpha)]
    assert mission_bodies == [summary.body, "C" * 10]
    assert memory.recall(beta)[0].body == "OTHERMISSION"
    assert [note.body for note in memory.recall(alpha, agent_id=agent_b) if note.agent_id == agent_b] == [
        "OTHERAGENT",
    ]
    assert memory.summarize(alpha, agent_id=agent_a, max_chars=23) is None
    agent_oldest = memory.remember(alpha, "A", agent_id=agent_a)
    agent_middle = memory.remember(alpha, "B" * 13, agent_id=agent_a)
    agent_newest = memory.remember(alpha, "C" * 10, agent_id=agent_a)
    _stamp(store, agent_only.id, 1)
    _stamp(store, agent_oldest.id, 2)
    _stamp(store, agent_middle.id, 3)
    _stamp(store, agent_newest.id, 4)
    agent_summary = memory.summarize(alpha, agent_id=agent_a, max_chars=23)
    assert agent_summary is not None
    assert agent_summary.agent_id == agent_a
    _assert_extractive(agent_summary.body, ["AGENTONLY", "A", "B" * 13])
    for token in ("OTHERMISSION", "OTHERAGENT", "C" * 10):
        assert token not in agent_summary.body
    assert memory.recall(beta)[0].body == "OTHERMISSION"
    assert [note.body for note in memory.recall(alpha)] == mission_bodies
    assert other_agent.body == "OTHERAGENT"


def test_summarize_corrupt_and_oversize_fail_closed_without_inventing(tmp_path):
    store, memory = _provider(tmp_path)
    mission_id = uuid4()
    memory.remember(mission_id, "good note")
    with store.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO memory_notes (id, mission_id, agent_id, body, created_at) "
            "VALUES ('not-a-uuid', :mission_id, NULL, 'corrupt', '2026-01-01T00:00:00')"
        ), {"mission_id": str(mission_id)})
    with pytest.raises(MemoryError) as corrupt:
        memory.summarize(mission_id, max_chars=64)
    assert corrupt.value.failure_class == FailureClass.INVALID_OUTPUT
    assert "good note" in _bodies(store, mission_id)
    assert "corrupt" in _bodies(store, mission_id)
    assert not any(body.startswith(SUMMARY_MARKER) for body in _bodies(store, mission_id))

    auto = StoreMemoryProvider(store, summarize_over_chars=64)
    with pytest.raises(MemoryError) as auto_corrupt:
        auto.remember(mission_id, "should roll back")
    assert auto_corrupt.value.failure_class == FailureClass.INVALID_OUTPUT
    assert "should roll back" not in _bodies(store, mission_id)
    assert not any(body.startswith(SUMMARY_MARKER) for body in _bodies(store, mission_id))

    other = uuid4()
    with store.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO memory_notes (id, mission_id, agent_id, body, created_at) "
            "VALUES (:id, :mission_id, NULL, :body, '2026-01-01T00:00:00')"
        ), {"id": str(uuid4()), "mission_id": str(other), "body": "z" * (MAX_NOTE_CHARS + 1)})
    with pytest.raises(MemoryError) as oversize:
        memory.summarize(other, max_chars=64)
    assert oversize.value.failure_class == FailureClass.CONTEXT_LIMIT
    assert _bodies(store, other) == ["z" * (MAX_NOTE_CHARS + 1)]


def test_auto_remember_refuses_a_note_that_would_be_rewritten(tmp_path):
    store, memory = _provider(tmp_path, summarize_over_chars=23)
    mission_id = uuid4()
    memory.remember(mission_id, "C" * 20)
    with pytest.raises(MemoryError) as exc:
        memory.remember(mission_id, "D" * 20)
    assert exc.value.failure_class == FailureClass.CONTEXT_LIMIT
    assert _bodies(store, mission_id) == ["C" * 20]
