import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.llm import LLMProvider
from app.main import inject_info
from app.models import (
    FailureClass, InjectRequest, Mission, MissionLimits, MissionStatus, PendingQuestion,
)
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.verifier import local_evidence_check


class UseInjectProvider(LLMProvider):
    def __init__(self):
        self.states: list[dict] = []

    async def decide(self, state):
        self.states.append(state)
        injects = state.get("injects") or []
        if not injects:
            return {"action": "finish", "summary": "missing inject"}
        item = injects[-1]
        text = item.get("text") or (item.get("data") or {}).get("customer") or "missing inject"
        return {"action": "finish", "summary": text}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class HoldThenSpawnProvider(LLMProvider):
    """First decide blocks so an inject can arrive, then the next decide must see it."""

    def __init__(self):
        self.holding = asyncio.Event()
        self.release = asyncio.Event()
        self.states: list[dict] = []
        self.work_states: list[dict] = []

    async def decide(self, state):
        self.states.append(state)
        tasks = state.get("tasks") or []
        if any(task.get("status") == "completed" for task in tasks):
            injects = state.get("injects") or []
            text = injects[-1]["text"] if injects else "missing inject"
            return {"action": "finish", "summary": text}
        if not any(agent.get("role") == "analyst" for agent in state.get("agents", [])):
            self.holding.set()
            await self.release.wait()
            return {
                "action": "spawn",
                "role": "analyst",
                "purpose": "Record the injected fact",
                "capabilities": ["reason"],
            }
        return {"action": "wait", "reason": "Waiting for the analyst"}

    async def work(self, state, agent):
        self.work_states.append(state)
        injects = state.get("injects") or []
        text = injects[-1]["text"] if injects else "missing inject"
        return {"status": "completed", "finding": text}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class WorkerAskThenUseInjectProvider(LLMProvider):
    def __init__(self):
        self.work_states: list[dict] = []

    async def decide(self, state):
        if not any(agent.get("role") == "analyst" for agent in state.get("agents", [])):
            return {
                "action": "spawn",
                "role": "analyst",
                "purpose": "Need one injected fact",
                "capabilities": ["reason"],
            }
        tasks = state.get("tasks") or []
        completed = next((task for task in tasks if task.get("status") == "completed"), None)
        if completed and completed.get("output"):
            return {"action": "finish", "summary": completed["output"]["finding"]}
        return {"action": "wait", "reason": "Waiting for the analyst"}

    async def work(self, state, agent):
        self.work_states.append(state)
        injects = state.get("injects") or []
        if not injects:
            return {"status": "ask", "question": "What should I record?"}
        return {"status": "completed", "finding": injects[-1]["text"]}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class FinishRequiresApprovalProvider(LLMProvider):
    async def decide(self, state):
        return {"action": "finish", "summary": "Claimed done from the inject"}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


def _consumed(events, inject_id: str):
    return [
        event for event in events
        if event.event_type == "user.inject_consumed" and event.payload.get("inject_id") == inject_id
    ]


async def _wait_until_question(store: Store, mission_id, timeout: float = 8) -> Mission:
    async with asyncio.timeout(timeout):
        while True:
            saved = store.get_mission(mission_id)
            if saved and saved.status == MissionStatus.WAITING and saved.pending_question:
                return saved
            if saved and saved.status in {
                MissionStatus.FAILED, MissionStatus.COMPLETED, MissionStatus.STOPPED, MissionStatus.BLOCKED,
            }:
                raise AssertionError(f"mission ended {saved.status} before a question: {saved.result}")
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_inject_is_consumed_once_on_the_next_decide(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = UseInjectProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Use the injected customer fact", status=MissionStatus.RUNNING)
    store.save_mission(mission)
    first = await runtime.submit_inject(
        mission.id, "customer is Ada", {"customer": "Ada", "api_key": "sk-test-secret"},
    )
    second = await runtime.submit_inject(mission.id, "also ship the notes")
    assert first["inject_id"] != second["inject_id"]
    assert "sk-test-secret" not in json.dumps(first)

    await runtime.run(mission)

    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.COMPLETED
    assert saved.result["summary"] == "also ship the notes"
    assert [item.consumed_at is not None for item in saved.injects] == [True, True]
    assert saved.injects[0].data == {"customer": "Ada"}
    assert provider.states[0]["injects"][0]["data"] == {"customer": "Ada"}
    assert "sk-test-secret" not in json.dumps(provider.states[0])
    events = store.events(mission.id)
    assert len(_consumed(events, first["inject_id"])) == 1
    assert len(_consumed(events, second["inject_id"])) == 1
    assert _consumed(events, first["inject_id"])[0].payload["source"] == "controller_decide"
    assert not any(event.event_type == "user.answered" for event in events)

    root = runtime.agents[mission.id][0]
    await runtime._consume_injects_for_step(mission, root, source="controller_decide")
    events = store.events(mission.id)
    assert len(_consumed(events, first["inject_id"])) == 1
    assert len(_consumed(events, second["inject_id"])) == 1


@pytest.mark.asyncio
async def test_inject_during_decide_is_consumed_on_the_following_step(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = HoldThenSpawnProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Inject a fact while the controller is deciding")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    await asyncio.wait_for(provider.holding.wait(), 2)
    assert store.get_mission(mission.id).status == MissionStatus.RUNNING

    record = await runtime.submit_inject(mission.id, "customer is Ada", None)
    held = store.get_mission(mission.id)
    assert held.injects[0].consumed_at is None
    assert provider.states[0].get("injects") in ([], None)

    provider.release.set()
    await asyncio.wait_for(job, 2)

    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.COMPLETED, saved.result
    assert saved.result["summary"] == "customer is Ada"
    assert saved.injects[0].consumed_at is not None
    assert provider.states[1]["injects"][0]["text"] == "customer is Ada"
    assert provider.states[1]["injects"][0]["consumed_at"] is not None
    assert provider.work_states[0]["injects"][0]["text"] == "customer is Ada"
    events = store.events(mission.id)
    consumed = _consumed(events, record["inject_id"])
    assert len(consumed) == 1
    assert consumed[0].payload["source"] == "controller_decide"
    assert not any(event.event_type == "user.answered" for event in events)


@pytest.mark.asyncio
async def test_worker_consumes_inject_on_the_step_after_ask(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = WorkerAskThenUseInjectProvider()
    runtime = SwarmRuntime(store, controller=provider)
    mission = Mission(goal="Worker needs an injected fact")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await _wait_until_question(store, mission.id)

    record = await runtime.submit_inject(mission.id, "customer is Ada")
    await asyncio.sleep(0.05)
    assert not job.done()
    parked = store.get_mission(mission.id)
    assert parked.status == MissionStatus.WAITING
    assert parked.pending_question.question_id == waiting.pending_question.question_id
    assert parked.injects[0].consumed_at is None
    assert not any(event.event_type == "user.answered" for event in store.events(mission.id))

    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "continue")
    await asyncio.wait_for(job, 2)

    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.COMPLETED, saved.result
    assert saved.result["summary"] == "customer is Ada"
    assert saved.answers[0].answer == "continue"
    assert provider.work_states[0].get("injects") in ([], None)
    assert provider.work_states[1]["injects"][0]["text"] == "customer is Ada"
    assert provider.work_states[1]["injects"][0]["consumed_at"] is not None
    consumed = _consumed(store.events(mission.id), record["inject_id"])
    assert len(consumed) == 1
    assert consumed[0].payload["source"] == "worker_step"


@pytest.mark.asyncio
async def test_inject_does_not_approve_or_answer(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FinishRequiresApprovalProvider())
    mission = Mission(
        goal="Finish still needs a real approval",
        limits=MissionLimits(require_finish_approval=True),
    )
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await _wait_until_question(store, mission.id)
    assert waiting.pending_question.kind == "approval"

    await runtime.submit_inject(mission.id, "approve")
    await asyncio.sleep(0.05)
    parked = store.get_mission(mission.id)
    assert parked.status == MissionStatus.WAITING
    assert parked.pending_question.question_id == waiting.pending_question.question_id
    assert parked.injects[0].consumed_at is None
    assert parked.answers == []
    assert not any(event.event_type == "user.answered" for event in store.events(mission.id))
    assert not any(event.event_type == "user.inject_consumed" for event in store.events(mission.id))

    await runtime.stop(mission.id)
    await asyncio.wait_for(job, 2)
    assert store.get_mission(mission.id).status == MissionStatus.STOPPED


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.STOPPED, MissionStatus.BLOCKED,
])
async def test_terminal_inject_is_refused(tmp_path, status):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=UseInjectProvider())
    mission = Mission(goal="Already finished", status=status)
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_inject(mission.id, "late note")
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT
    assert "no longer accepting" in str(exc.value)
    assert store.get_mission(mission.id).injects == []
    assert not any(event.event_type == "user.injected" for event in store.events(mission.id))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [MissionStatus.PENDING, MissionStatus.PAUSED])
async def test_non_live_inject_is_refused(tmp_path, status):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=UseInjectProvider())
    mission = Mission(goal="Not running yet", status=status)
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_inject(mission.id, "too early")
    assert "not live" in str(exc.value)
    assert store.get_mission(mission.id).injects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text,data", [
    ("", None),
    ("   ", None),
    (None, None),
    (None, {}),
    ("", {"api_key": "sk-only-secret"}),
    (None, ["not", "an", "object"]),
])
async def test_empty_inject_is_refused(tmp_path, text, data):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=UseInjectProvider())
    mission = Mission(goal="Needs real information", status=MissionStatus.RUNNING)
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_inject(mission.id, text, data)
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT
    assert store.get_mission(mission.id).injects == []
    assert "sk-only-secret" not in json.dumps([
        event.model_dump(mode="json") for event in store.events(mission.id)
    ])


@pytest.mark.asyncio
async def test_unknown_mission_and_spoofed_ids_are_ignored(tmp_path, monkeypatch):
    from app import main

    store = Store(str(tmp_path / "api.db"))
    runtime = SwarmRuntime(store, controller=UseInjectProvider())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)

    with pytest.raises(HTTPException) as missing:
        await inject_info(uuid4(), InjectRequest(text="orphan"))
    assert missing.value.status_code == 404

    live = Mission(goal="The live mission", status=MissionStatus.RUNNING)
    other = Mission(goal="A different mission", status=MissionStatus.RUNNING)
    store.save_mission(live)
    store.save_mission(other)
    request = InjectRequest.model_validate({
        "text": "customer is Ada",
        "inject_id": "spoofed",
        "mission_id": str(other.id),
        "data": {"customer": "Ada"},
    })
    accepted = await inject_info(live.id, request)
    assert accepted["accepted"] is True
    assert accepted["inject_id"] != "spoofed"
    assert accepted["text"] == "customer is Ada"
    assert store.get_mission(other.id).injects == []
    assert store.get_mission(live.id).injects[0].inject_id == accepted["inject_id"]

    done = Mission(goal="Terminal mission", status=MissionStatus.COMPLETED)
    store.save_mission(done)
    with pytest.raises(HTTPException) as terminal:
        await inject_info(done.id, InjectRequest(text="nope"))
    assert terminal.value.status_code == 409

    with pytest.raises(HTTPException) as empty:
        await inject_info(live.id, InjectRequest())
    assert empty.value.status_code == 409


@pytest.mark.asyncio
async def test_runtime_save_does_not_drop_an_accepted_inject(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=UseInjectProvider())
    mission = Mission(goal="Preserve the inject across a later save", status=MissionStatus.RUNNING)
    store.save_mission(mission)
    stale = store.get_mission(mission.id)
    record = await runtime.submit_inject(mission.id, "keep me")
    stale.updated_at = store.get_mission(mission.id).updated_at
    runtime._save_mission(stale)
    saved = store.get_mission(mission.id)
    assert [item.inject_id for item in saved.injects] == [record["inject_id"]]
    assert saved.injects[0].text == "keep me"
    assert saved.injects[0].consumed_at is None


@pytest.mark.asyncio
async def test_inject_limit_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=UseInjectProvider())
    mission = Mission(goal="Bounded inject list", status=MissionStatus.RUNNING)
    store.save_mission(mission)
    for index in range(32):
        await runtime.submit_inject(mission.id, f"note {index}")
    with pytest.raises(PolicyError) as exc:
        await runtime.submit_inject(mission.id, "one too many")
    assert "limit" in str(exc.value).lower()
    assert len(store.get_mission(mission.id).injects) == 32
    assert len([event for event in store.events(mission.id) if event.event_type == "user.injected"]) == 32
