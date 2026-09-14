import asyncio

import pytest
from fastapi import HTTPException

from app.llm import LLMProvider, WORK_FORMAT
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


async def wait_until_question(store: Store, mission_id, timeout: float = 8) -> Mission:
    async with asyncio.timeout(timeout):
        while True:
            saved = store.get_mission(mission_id)
            if saved and saved.status == MissionStatus.WAITING and saved.pending_question:
                return saved
            if saved and saved.status in {
                MissionStatus.FAILED, MissionStatus.COMPLETED, MissionStatus.STOPPED, MissionStatus.BLOCKED,
            }:
                raise AssertionError(
                    f"mission ended {saved.status} before a pending question: {saved.result}"
                )
            await asyncio.sleep(0.01)


def test_work_format_allows_ask():
    props = WORK_FORMAT["schema"]["properties"]
    assert "ask" in props["status"]["enum"]
    assert "question" in props


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
    assert saved.answers[0].consumed_at is not None
    assert any(state.get("answers") for state in provider.states)
    assert any(e.event_type == "user.answered" for e in store.events(mission.id))
    assert any(e.event_type == "user.answer_consumed" for e in store.events(mission.id))
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
async def test_answer_persisted_offline_requests_resume_and_is_truthfully_consumed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Need a name")
    store.save_mission(mission)
    await runtime.start(mission)
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    await asyncio.wait_for(runtime.suspend_all(), 2)

    offline = SwarmRuntime(store, controller=AskThenFinishProvider())
    record = await offline.submit_answer(mission.id, question_id, "Ada")
    assert record["resume"] == "requested"
    await asyncio.wait_for(asyncio.gather(*offline.runs.values()), 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "User said: Ada"
    assert saved.answers[0].consumed_at is not None
    events = store.events(mission.id)
    kinds = [event.event_type for event in events]
    assert kinds.index("user.answered") < kinds.index("mission.resume_requested")
    assert kinds.index("mission.resume_requested") < kinds.index("mission.resumed")
    assert kinds.index("mission.resumed") < kinds.index("user.answer_consumed")
    assert kinds.count("user.answered") == 1
    assert kinds.count("user.answer_consumed") == 1


@pytest.mark.asyncio
async def test_concurrent_answers_accept_exactly_one_while_paused(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(
        goal="Need one name",
        status=MissionStatus.PAUSED,
        pending_question=PendingQuestion(question_id="q1", question="Name?"),
    )
    store.save_mission(mission)

    results = await asyncio.gather(
        runtime.submit_answer(mission.id, "q1", "Ada"),
        runtime.submit_answer(mission.id, "q1", "Grace"),
        return_exceptions=True,
    )

    accepted = [item for item in results if isinstance(item, dict)]
    rejected = [item for item in results if isinstance(item, PolicyError)]
    assert len(accepted) == 1
    assert accepted[0]["resume"] == "paused"
    assert len(rejected) == 1
    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.PAUSED
    assert len(saved.answers) == 1
    assert len([e for e in store.events(mission.id) if e.event_type == "user.answered"]) == 1


@pytest.mark.asyncio
async def test_answer_on_second_runtime_wakes_durable_lease_owner(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    owner = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Answer can arrive on another process")
    store.save_mission(mission)
    await owner.start(mission)
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id

    submitter = SwarmRuntime(store, controller=AskThenFinishProvider())
    record = await submitter.submit_answer(mission.id, question_id, "Ada")
    assert record["resume"] == "requested"
    await asyncio.wait_for(asyncio.gather(*owner.runs.values()), 2)

    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.COMPLETED
    assert saved.result["summary"] == "User said: Ada"
    assert saved.answers[0].consumed_at is not None
    events = store.events(mission.id)
    assert len([e for e in events if e.event_type == "user.answered"]) == 1
    assert len([e for e in events if e.event_type == "user.answer_consumed"]) == 1
    assert any(e.event_type == "mission.running" for e in events)
    assert not any(e.event_type == "mission.failed" for e in events)


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


class SpawnWaitThenFinishProvider(LLMProvider):
    """Controller that spawns one analyst, waits, then finishes from worker output."""

    async def decide(self, state):
        if not any(agent.get("role") == "analyst" for agent in state.get("agents", [])):
            return {"action": "spawn", "role": "analyst", "purpose": "Collect a user fact",
                    "capabilities": ["reason"]}
        if any(task.get("status") in {"pending", "running"} for task in state.get("tasks", [])):
            return {"action": "wait", "reason": "worker running"}
        finding = next(
            ((task.get("output") or {}).get("finding") for task in state.get("tasks", [])
             if (task.get("output") or {}).get("finding")),
            None,
        )
        return {"action": "finish", "summary": finding or "Worker finished"}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class WorkerAskThenCompleteProvider(SpawnWaitThenFinishProvider):
    async def work(self, state, agent):
        del agent
        answers = state.get("answers") or []
        if answers:
            return {"status": "completed", "finding": f"User said: {answers[0]['answer']}",
                    "limitations": []}
        return {"status": "ask", "finding": "Need the name", "question": "What is the target name?",
                "question_id": "spoofed-from-model"}


class WorkerAskWithoutQuestionProvider(SpawnWaitThenFinishProvider):
    async def work(self, state, agent):
        del state, agent
        return {"status": "ask", "finding": "Need a fact"}


@pytest.mark.asyncio
async def test_worker_ask_waits_consumes_matching_answer_and_continues(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=WorkerAskThenCompleteProvider())
    mission = Mission(goal="Need one user fact from a worker")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    assert question_id != "spoofed-from-model"
    events = store.events(mission.id)
    assert any(e.event_type == "mission.question" and e.payload["question_id"] == question_id for e in events)
    assert any(e.event_type == "mission.waiting" and e.payload.get("question_id") == question_id for e in events)
    assert store.get_mission(mission.id).status == "waiting"
    assert store.get_mission(mission.id).result is None
    task = store.load_tasks(mission.id)[0]
    assert task.status == "running"

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
    assert saved.answers[0].consumed_at is not None
    assert any(e.event_type == "user.answered" for e in store.events(mission.id))
    assert any(e.event_type == "user.answer_consumed" for e in store.events(mission.id))
    assert not any(e.event_type == "mission.failed" for e in store.events(mission.id))
    completed = store.load_tasks(mission.id)[0]
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_worker_ask_without_question_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=WorkerAskWithoutQuestionProvider())
    mission = Mission(goal="Invalid worker ask")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "INVALID_OUTPUT"
    assert "without a question" in saved.result["error"]
    assert not any(e.event_type == "mission.question" for e in store.events(mission.id))
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_stop_during_human_wait_is_stopped_not_success(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    mission = Mission(goal="Stop while waiting for a human")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    await runtime.stop(mission.id)
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "stopped"
    assert saved.result == {"reason": "Execution stopped"}
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_answer(mission.id, question_id, "Ada")
    assert "no longer accepting" in str(exc.value)
    assert not any(e.event_type == "user.answered" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_stop_during_worker_ask_is_stopped_not_success(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=WorkerAskThenCompleteProvider())
    mission = Mission(goal="Stop while a worker waits for a human")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    await runtime.stop(mission.id)
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "stopped"
    assert saved.result == {"reason": "Execution stopped"}
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))
    assert not any(e.event_type == "user.answered" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_answer_for_another_mission_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AskThenFinishProvider())
    waiting_mission = Mission(goal="Need a name")
    other = Mission(goal="Unrelated mission", status=MissionStatus.RUNNING)
    store.save_mission(waiting_mission)
    store.save_mission(other)
    job = asyncio.create_task(runtime.run(waiting_mission))
    waiting = await wait_until_question(store, waiting_mission.id)
    question_id = waiting.pending_question.question_id
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_answer(other.id, question_id, "Ada")
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert store.get_mission(waiting_mission.id).pending_question is not None
    assert store.get_mission(other.id).answers == []
    assert not any(e.event_type == "user.answered" for e in store.events(waiting_mission.id))
    assert not any(e.event_type == "user.answered" for e in store.events(other.id))
    await runtime.stop(waiting_mission.id)
    await asyncio.wait_for(job, 2)
    assert store.get_mission(waiting_mission.id).status == "stopped"
