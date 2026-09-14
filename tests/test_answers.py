import asyncio

import pytest
from fastapi import HTTPException

from app.llm import LLMProvider
from app.main import answer_question
from app.models import AnswerRequest, FailureClass, Mission, MissionStatus, PendingQuestion
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.verifier import local_evidence_check


class AskThenFinishProvider(LLMProvider):
    def __init__(self):
        self.states: list[dict] = []

    async def decide(self, state):
        self.states.append(state)
        answers = state.get("answers") or []
        if answers:
            return {"action": "finish", "summary": f"User said: {answers[0]['answer']}"}
        return {"action": "ask", "question": "What is the target name?", "reason": "Need the name"}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class AskOnlyProvider(LLMProvider):
    async def decide(self, state):
        return {"action": "ask", "question": "Need a fact"}


class AskWithoutQuestionProvider(LLMProvider):
    async def decide(self, state):
        return {"action": "ask", "reason": "missing question text"}


class SpawnThenAskProvider(LLMProvider):
    async def decide(self, state):
        if not any(agent.get("role") == "analyst" for agent in state.get("agents", [])):
            return {"action": "spawn", "role": "analyst", "purpose": "Analyze", "capabilities": ["reason"]}
        return {"action": "ask", "question": "Should not ask while the analyst is pending"}

    async def work(self, state, agent):
        return {"status": "completed", "finding": "should not run if ask is rejected"}


async def wait_until_question(store: Store, mission_id, timeout: float = 2) -> Mission:
    async with asyncio.timeout(timeout):
        while True:
            saved = store.get_mission(mission_id)
            if saved and saved.status == MissionStatus.WAITING and saved.pending_question:
                return saved
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_ask_waits_consumes_matching_answer_and_continues(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = AskThenFinishProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Need one user fact")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    events = store.events(mission.id)
    assert any(e.event_type == "mission.question" and e.payload["question_id"] == question_id for e in events)
    assert any(e.event_type == "mission.waiting" and e.payload.get("question_id") == question_id for e in events)
    assert store.get_mission(mission.id).status == "waiting"
    assert store.get_mission(mission.id).result is None

    with pytest.raises(PolicyError) as mismatch:
        await runtime.submit_answer(mission.id, "not-the-question", "Ada")
    assert mismatch.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert store.get_mission(mission.id).pending_question is not None
    assert not any(e.event_type == "user.answered" for e in store.events(mission.id))

    record = await runtime.submit_answer(mission.id, question_id, "Ada")
    assert record["answer"] == "Ada"
    await asyncio.wait_for(job, 2)

    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "User said: Ada"
    assert saved.pending_question is None
    assert saved.answers[0].answer == "Ada"
    assert any(state.get("answers") for state in provider.states)
    assert any(e.event_type == "user.answered" for e in store.events(mission.id))
    assert any(e.event_type == "mission.running" for e in store.events(mission.id))
    assert not any(e.event_type == "mission.failed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_answer_without_open_question_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskOnlyProvider())
    mission = Mission(goal="No question yet")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_answer(mission.id, "q1", "Ada")
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert not any(e.event_type == "user.answered" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_answer_unknown_or_terminal_mission_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskOnlyProvider())
    missing = Mission(goal="never saved")
    with pytest.raises(PolicyError) as missing_exc:
        await runtime.submit_answer(missing.id, "q1", "Ada")
    assert "not found" in str(missing_exc.value)

    done = Mission(goal="already finished", status=MissionStatus.COMPLETED)
    store.save_mission(done)
    with pytest.raises(PolicyError) as terminal:
        await runtime.submit_answer(done.id, "q1", "Ada")
    assert "no longer accepting" in str(terminal.value)
    assert not any(e.event_type == "user.answered" for e in store.events(done.id))


@pytest.mark.asyncio
async def test_empty_answer_is_rejected(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Need a name")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "   ")
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT
    assert store.get_mission(mission.id).pending_question is not None
    await runtime.stop(mission.id)
    await asyncio.wait_for(job, 2)
    assert store.get_mission(mission.id).status == "stopped"


@pytest.mark.asyncio
async def test_duplicate_answer_is_rejected(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Need a name")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    await runtime.submit_answer(mission.id, question_id, "Ada")
    await asyncio.wait_for(job, 2)
    with pytest.raises(PolicyError):
        await runtime.submit_answer(mission.id, question_id, "Grace")
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert [item.answer for item in saved.answers] == ["Ada"]


@pytest.mark.asyncio
async def test_ask_without_question_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskWithoutQuestionProvider())
    mission = Mission(goal="Invalid ask")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "INVALID_OUTPUT"
    assert "without a question" in saved.result["error"]
    assert not any(e.event_type == "mission.question" for e in store.events(mission.id))
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_ask_while_tasks_active_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=SpawnThenAskProvider())
    mission = Mission(goal="Cannot ask mid-flight")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "INVALID_OUTPUT"
    assert "tasks are active" in saved.result["error"]
    assert not any(e.event_type == "mission.question" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_resume_while_waiting_for_answer_does_not_fabricate_one(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Need a name")
    store.save_mission(mission)
    await runtime.start(mission)
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    await asyncio.wait_for(runtime.suspend_all(), 2)
    suspended = store.get_mission(mission.id)
    assert suspended.status == MissionStatus.WAITING
    assert suspended.pending_question.question_id == question_id
    assert suspended.answers == []
    assert any(e.event_type == "mission.suspended" for e in store.events(mission.id))
    assert not any(e.event_type == "user.answered" for e in store.events(mission.id))

    restored = SwarmRuntime(store, controller=AskThenFinishProvider())
    resumed = await restored.resume_incomplete()
    assert resumed == [mission.id]
    waiting_again = await wait_until_question(store, mission.id)
    assert waiting_again.pending_question.question_id == question_id
    assert waiting_again.answers == []
    record = await restored.submit_answer(mission.id, question_id, "Ada")
    assert record["answer"] == "Ada"
    await asyncio.wait_for(asyncio.gather(*restored.runs.values()), 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "User said: Ada"


@pytest.mark.asyncio
async def test_answer_persisted_offline_is_consumed_on_resume(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Need a name")
    store.save_mission(mission)
    await runtime.start(mission)
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    await asyncio.wait_for(runtime.suspend_all(), 2)

    offline = SwarmRuntime(store, controller=AskThenFinishProvider())
    await offline.submit_answer(mission.id, question_id, "Ada")
    parked = store.get_mission(mission.id)
    assert parked.pending_question is None
    assert parked.answers[0].answer == "Ada"
    assert parked.status == MissionStatus.WAITING

    restored = SwarmRuntime(store, controller=AskThenFinishProvider())
    await restored.resume_incomplete()
    await asyncio.wait_for(asyncio.gather(*restored.runs.values()), 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "User said: Ada"


@pytest.mark.asyncio
async def test_http_answer_unknown_mission_is_404(tmp_path, monkeypatch):
    from uuid import uuid4

    from app import main

    store = Store(str(tmp_path / "api.db"))
    runtime = SwarmRuntime(store, controller=AskOnlyProvider())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)
    with pytest.raises(HTTPException) as exc:
        await answer_question(uuid4(), "q1", AnswerRequest(answer="Ada"))
    assert exc.value.status_code == 404
    assert not store.list_missions()


@pytest.mark.asyncio
async def test_http_answer_mismatch_is_409(tmp_path, monkeypatch):
    from app import main

    store = Store(str(tmp_path / "api.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)
    mission = Mission(
        goal="Need a name",
        status=MissionStatus.WAITING,
        pending_question=PendingQuestion(question_id="q-open", question="Name?"),
    )
    store.save_mission(mission)
    with pytest.raises(HTTPException) as exc:
        await answer_question(mission.id, "q-other", AnswerRequest(answer="Ada"))
    assert exc.value.status_code == 409
    assert store.get_mission(mission.id).pending_question is not None
    assert not any(e.event_type == "user.answered" for e in store.events(mission.id))
