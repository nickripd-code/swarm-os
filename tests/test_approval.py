import asyncio

import pytest

from app.llm import LLMProvider
from app.models import FailureClass, Mission, MissionAnswer, MissionStatus
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.verifier import local_evidence_check


class PassingFinishProvider(LLMProvider):
    async def decide(self, state):
        del state
        return {"action": "finish", "summary": "The answer is a short text-only result."}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


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


@pytest.mark.asyncio
async def test_finish_without_approval_flag_still_completes(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingFinishProvider())
    mission = Mission(goal="Plain text answer")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.limits.require_finish_approval is False
    assert not any(e.event_type == "mission.question" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_finish_approval_approve_continues(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingFinishProvider())
    mission = Mission(goal="Needs a human yes", limits={"require_finish_approval": True})
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    assert waiting.pending_question.kind == "approval"
    assert waiting.pending_question.approval_action == "finish"
    events = store.events(mission.id)
    assert any(e.event_type == "mission.question" and e.payload.get("kind") == "approval" for e in events)
    assert any(e.event_type == "mission.waiting" and e.payload.get("question_id") == question_id for e in events)
    record = await runtime.submit_answer(mission.id, question_id, "approve")
    assert record["kind"] == "approval"
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "The answer is a short text-only result."
    assert not any(e.event_type == "mission.failed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_finish_approval_deny_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingFinishProvider())
    mission = Mission(goal="Needs a human no", limits={"require_finish_approval": True})
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "deny")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    assert "denied" in saved.result["error"].lower()
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_finish_approval_ambiguous_answer_is_not_auto_approved(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingFinishProvider())
    mission = Mission(goal="Needs an explicit approve", limits={"require_finish_approval": True})
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "ok")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "AUTHORIZATION_REQUIRED"
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_prior_non_approval_yes_does_not_auto_approve_finish(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingFinishProvider())
    mission = Mission(
        goal="Old yes is not finish approval",
        limits={"require_finish_approval": True},
        answers=[MissionAnswer(question_id="old", question="Ready?", answer="yes")],
    )
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_question(store, mission.id)
    assert waiting.pending_question.kind == "approval"
    assert waiting.status == MissionStatus.WAITING
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "deny")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_resume_while_waiting_for_finish_approval_does_not_fabricate_one(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingFinishProvider())
    mission = Mission(goal="Approve after restart", limits={"require_finish_approval": True})
    store.save_mission(mission)
    await runtime.start(mission)
    waiting = await wait_until_question(store, mission.id)
    question_id = waiting.pending_question.question_id
    await asyncio.wait_for(runtime.suspend_all(), 2)
    suspended = store.get_mission(mission.id)
    assert suspended.status == MissionStatus.WAITING
    assert suspended.pending_question.question_id == question_id
    assert not any(item.kind == "approval" and parse_is_approve(item.answer) for item in suspended.answers)

    restored = SwarmRuntime(store, controller=PassingFinishProvider())
    resumed = await restored.resume_incomplete()
    assert resumed == [mission.id]
    waiting_again = await wait_until_question(store, mission.id)
    assert waiting_again.pending_question.question_id == question_id
    assert waiting_again.status == MissionStatus.WAITING
    record = await restored.submit_answer(mission.id, question_id, "approve")
    assert record["answer"] == "approve"
    await asyncio.wait_for(asyncio.gather(*restored.runs.values()), 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"


def parse_is_approve(text: str) -> bool:
    from app.policy import parse_approval_answer
    return parse_approval_answer(text) == "approve"


@pytest.mark.asyncio
async def test_live_payment_without_approval_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = Mission(goal="pay", budget=10, live_payments=True, limits={"max_payment_amount": 5})
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.create_payment(mission, "0xabc", 2, "live attempt", idempotency_key="live-gate")
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert "human approval" in str(exc.value).lower()
    saved = store.get_mission(mission.id)
    assert saved.spent == 0
    assert not any(e.event_type == "payment.created" for e in store.events(mission.id))
