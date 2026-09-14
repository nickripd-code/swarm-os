import asyncio

import pytest
from fastapi import HTTPException

from app.llm import LLMProvider
from app.models import Mission, MissionStatus
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.verifier import local_evidence_check


class AskThenFinishProvider(LLMProvider):
    async def decide(self, state):
        answers = state.get("answers") or []
        if answers:
            return {"action": "finish", "summary": f"User said: {answers[-1]['answer']}"}
        return {"action": "ask", "question": "What is the target name?"}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class UnconfiguredProvider(AskThenFinishProvider):
    def configured(self):
        return False


async def wait_until(store: Store, mission_id, status: MissionStatus, timeout: float = 2):
    async with asyncio.timeout(timeout):
        while True:
            mission = store.get_mission(mission_id)
            if mission and mission.status == status:
                return mission
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_pause_preserves_question_answer_stays_paused_then_resume_consumes_it(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Need one user fact")
    store.save_mission(mission)
    await runtime.start(mission)
    waiting = await wait_until(store, mission.id, MissionStatus.WAITING)
    question_id = waiting.pending_question.question_id

    paused = await runtime.pause(mission.id)
    assert paused.status == MissionStatus.PAUSED
    assert paused.paused_at is not None
    assert paused.pending_question.question_id == question_id
    assert mission.id not in runtime.runs or runtime.runs[mission.id].done()
    pause_events = [e for e in store.events(mission.id) if e.event_type == "mission.paused"]
    assert len(pause_events) == 1
    assert pause_events[0].payload["pending_question_id"] == question_id
    assert not any(e.event_type in {"mission.failed", "mission.stopped"}
                   for e in store.events(mission.id))

    record = await runtime.submit_answer(mission.id, question_id, "Ada")
    assert record["resume"] == "paused"
    answered = store.get_mission(mission.id)
    assert answered.status == MissionStatus.PAUSED
    assert answered.answers[0].consumed_at is None
    assert mission.id not in runtime.runs or runtime.runs[mission.id].done()

    await runtime.resume(mission.id)
    await asyncio.wait_for(asyncio.gather(*runtime.runs.values()), 2)
    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.COMPLETED
    assert saved.paused_at is None
    assert saved.paused_seconds >= 0
    assert saved.result["summary"] == "User said: Ada"
    assert saved.answers[0].consumed_at is not None
    events = store.events(mission.id)
    resumed = [e for e in events if e.event_type == "mission.resumed"]
    assert resumed[-1].payload["from_status"] == "paused"
    assert any(e.event_type == "user.answer_consumed" for e in events)


@pytest.mark.asyncio
async def test_pause_is_idempotent_and_resume_incomplete_skips_user_paused_mission(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Pause before launch")
    store.save_mission(mission)

    await runtime.pause(mission.id)
    await runtime.pause(mission.id)
    assert store.get_mission(mission.id).status == MissionStatus.PAUSED
    assert len([e for e in store.events(mission.id) if e.event_type == "mission.paused"]) == 1

    restored = SwarmRuntime(store, controller=AskThenFinishProvider())
    assert await restored.resume_incomplete() == []
    assert restored.runs == {}


@pytest.mark.asyncio
async def test_stop_all_includes_paused_missions_and_preserves_global_stop(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Pause then stop")
    store.save_mission(mission)
    await runtime.pause(mission.id)

    stopped = await runtime.stop_all()
    assert stopped == [mission.id]
    assert store.get_mission(mission.id).status == MissionStatus.STOPPED
    assert any(e.event_type == "mission.stopped" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_invalid_resume_and_unconfigured_resume_fail_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    running = Mission(goal="Not paused", status=MissionStatus.WAITING)
    store.save_mission(running)
    with pytest.raises(PolicyError):
        await runtime.resume(running.id)

    paused = Mission(goal="No provider", status=MissionStatus.PAUSED)
    store.save_mission(paused)
    unconfigured = SwarmRuntime(store, controller=UnconfiguredProvider())
    with pytest.raises(PolicyError) as exc:
        await unconfigured.resume(paused.id)
    assert exc.value.failure_class == "AUTHORIZATION_REQUIRED"
    assert store.get_mission(paused.id).status == MissionStatus.PAUSED
    assert not any(e.event_type == "mission.resume_requested" for e in store.events(paused.id))


@pytest.mark.asyncio
async def test_pause_and_resume_http_routes_translate_missing_and_conflict(tmp_path, monkeypatch):
    from uuid import uuid4

    from app import main

    store = Store(str(tmp_path / "api.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)

    with pytest.raises(HTTPException) as missing:
        await main.pause_mission(uuid4())
    assert missing.value.status_code == 404

    mission = Mission(goal="API pause")
    store.save_mission(mission)
    paused = await main.pause_mission(mission.id)
    assert paused["status"] == MissionStatus.PAUSED
    requested = await main.resume_mission(mission.id)
    assert requested == {"status": "resume_requested"}
    await runtime.stop(mission.id)

    with pytest.raises(HTTPException) as conflict:
        await main.resume_mission(mission.id)
    assert conflict.value.status_code == 409
