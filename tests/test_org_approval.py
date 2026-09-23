import asyncio

import pytest

from app.events import EventType
from app.models import AgentStatus, FailureClass, Mission, MissionAnswer, MissionStatus
from app.policy import PolicyError
from app.runtime import SwarmRuntime
from app.store import Store
from tests.test_org import OrgScriptController, seed_tree, wait_until_org_question
from tests.test_planning import COMPLEX_GOAL


def _decision(op: str, root_id: str, lead_id: str, worker_id: str) -> dict:
    spoofed = {"question_id": "spoofed-from-model"}
    if op == "reparent":
        return {"action": "reparent", "agent_id": worker_id, "parent_id": root_id, **spoofed}
    if op == "retire":
        return {"action": "retire", "agent_id": worker_id, **spoofed}
    return {
        "action": "replace",
        "agent_id": lead_id,
        "parent_id": root_id,
        "role": "research_lead",
        "purpose": "Lead a tighter research pass",
        "capabilities": ["reason"],
        **spoofed,
    }


def _topology(store: Store, mission_id) -> list[tuple]:
    """Specialist parent/status only. Controller status changes when the mission fails or stops."""
    return [
        (
            str(agent.id),
            str(agent.parent_id) if agent.parent_id else None,
            str(agent.status),
            agent.role,
        )
        for agent in store.load_agents(mission_id)
        if agent.parent_id is not None
    ]


def _assert_mutated(op: str, store: Store, mission, root, lead, worker) -> None:
    agents = {agent.id: agent for agent in store.load_agents(mission.id)}
    if op == "reparent":
        assert agents[worker.id].parent_id == root.id
        assert agents[worker.id].status != AgentStatus.STOPPED
    elif op == "retire":
        assert agents[worker.id].status == AgentStatus.STOPPED
        assert len(agents) == 3
    else:
        assert agents[lead.id].status == AgentStatus.STOPPED
        assert agents[worker.id].parent_id not in {None, lead.id}
        assert any(
            agent.role == "research_lead" and agent.id != lead.id and agent.status != AgentStatus.STOPPED
            for agent in agents.values()
        )
    assert any(
        event.event_type == EventType.ORG_CHANGED and event.payload.get("op") == op
        for event in store.events(mission.id)
    )


async def _start(tmp_path, op: str):
    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    runtime = SwarmRuntime(store, controller=OrgScriptController([]))
    root, lead, worker = await seed_tree(runtime, mission)
    decision = _decision(op, str(root.id), str(lead.id), str(worker.id))
    script = [decision]
    if op == "replace":
        script.append({"action": "wait", "reason": "replacement running"})
    script.append({"action": "finish", "summary": "Organization change applied and goal satisfied."})
    runtime.controller = OrgScriptController(script)
    before = _topology(store, mission.id)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_org_question(store, mission.id)
    return store, runtime, mission, job, waiting, before, root, lead, worker


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["replace", "reparent", "retire"])
async def test_org_op_parks_then_approve_mutates(tmp_path, op):
    store, runtime, mission, job, waiting, before, root, lead, worker = await _start(tmp_path, op)
    question_id = waiting.pending_question.question_id
    assert question_id != "spoofed-from-model"
    assert waiting.pending_question.kind == "approval"
    target = str(lead.id if op == "replace" else worker.id)
    assert waiting.pending_question.approval_action == f"org_change:{op}:{target}"
    events = store.events(mission.id)
    assert any(event.event_type == "mission.question" and event.payload.get("kind") == "approval" for event in events)
    assert any(event.event_type == "mission.waiting" and event.payload.get("question_id") == question_id for event in events)
    assert _topology(store, mission.id) == before
    record = await runtime.submit_answer(mission.id, question_id, "approve")
    assert record["kind"] == "approval"
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    _assert_mutated(op, store, mission, root, lead, worker)


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["replace", "reparent", "retire"])
async def test_org_op_deny_fails_closed(tmp_path, op):
    store, runtime, mission, job, waiting, before, root, lead, worker = await _start(tmp_path, op)
    del root, lead, worker
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "deny")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    assert "denied" in saved.result["error"].lower()
    assert _topology(store, mission.id) == before
    assert not any(event.event_type == EventType.ORG_CHANGED for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_org_op_ambiguous_answer_is_not_auto_approved(tmp_path):
    store, runtime, mission, job, waiting, before, *_rest = await _start(tmp_path, "reparent")
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "ok")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "AUTHORIZATION_REQUIRED"
    assert _topology(store, mission.id) == before
    assert not any(event.event_type == EventType.ORG_CHANGED for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_org_op_mismatch_and_empty_fail_closed(tmp_path):
    store, runtime, mission, job, waiting, before, *_rest = await _start(tmp_path, "retire")
    question_id = waiting.pending_question.question_id
    with pytest.raises(PolicyError) as mismatch:
        await runtime.submit_answer(mission.id, "spoofed-from-model", "approve")
    assert mismatch.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    with pytest.raises(PolicyError) as empty:
        await runtime.submit_answer(mission.id, question_id, "   ")
    assert empty.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(PolicyError) as blank_id:
        await runtime.submit_answer(mission.id, "  ", "approve")
    assert blank_id.value.failure_class == FailureClass.INVALID_OUTPUT
    saved = store.get_mission(mission.id)
    assert saved.status == MissionStatus.WAITING
    assert saved.pending_question.question_id == question_id
    assert _topology(store, mission.id) == before
    assert not any(event.event_type == "user.answered" for event in store.events(mission.id))
    assert not any(event.event_type == EventType.ORG_CHANGED for event in store.events(mission.id))
    await runtime.stop(mission.id)
    await asyncio.wait_for(job, 2)


@pytest.mark.asyncio
async def test_prior_yes_or_other_target_does_not_auto_approve_org_op(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(
        goal=COMPLEX_GOAL,
        answers=[MissionAnswer(question_id="old", question="Ready?", answer="yes")],
    )
    store.save_mission(mission)
    runtime = SwarmRuntime(store, controller=OrgScriptController([]))
    root, lead, worker = await seed_tree(runtime, mission)
    mission.answers.append(MissionAnswer(
        question_id="other-target",
        question="Approve organization change 'retire'?",
        answer="approve",
        kind="approval",
        approval_action=f"org_change:retire:{lead.id}",
    ))
    store.save_mission(mission)
    runtime.controller = OrgScriptController([
        {"action": "retire", "agent_id": str(worker.id), "question_id": "spoofed-from-model"},
    ])
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_org_question(store, mission.id)
    assert waiting.pending_question.approval_action == f"org_change:retire:{worker.id}"
    assert waiting.pending_question.question_id != "spoofed-from-model"
    before = _topology(store, mission.id)
    await runtime.stop(mission.id)
    await asyncio.wait_for(job, 2)
    assert _topology(store, mission.id) == before
    assert not any(event.event_type == EventType.ORG_CHANGED for event in store.events(mission.id))
    del root


@pytest.mark.asyncio
async def test_approve_replace_does_not_auto_approve_later_retire(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    runtime = SwarmRuntime(store, controller=OrgScriptController([]))
    root, lead, worker = await seed_tree(runtime, mission)
    runtime.controller = OrgScriptController([
        {
            "action": "reparent",
            "agent_id": str(worker.id),
            "parent_id": str(root.id),
            "question_id": "spoofed-from-model",
        },
        {"action": "retire", "agent_id": str(worker.id), "question_id": "spoofed-again"},
    ])
    job = asyncio.create_task(runtime.run(mission))
    first = await wait_until_org_question(store, mission.id)
    assert first.pending_question.approval_action == f"org_change:reparent:{worker.id}"
    await runtime.submit_answer(mission.id, first.pending_question.question_id, "approve")
    second = await wait_until_org_question(store, mission.id)
    assert second.pending_question.question_id != first.pending_question.question_id
    assert second.pending_question.question_id != "spoofed-again"
    assert second.pending_question.approval_action == f"org_change:retire:{worker.id}"
    agents = {agent.id: agent for agent in store.load_agents(mission.id)}
    assert agents[worker.id].parent_id == root.id
    assert agents[worker.id].status != AgentStatus.STOPPED
    await runtime.submit_answer(mission.id, second.pending_question.question_id, "deny")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    agents = {agent.id: agent for agent in store.load_agents(mission.id)}
    assert agents[worker.id].parent_id == root.id
    assert agents[worker.id].status != AgentStatus.STOPPED
    del lead


@pytest.mark.asyncio
async def test_spawn_does_not_park_for_approval(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    runtime = SwarmRuntime(store, controller=OrgScriptController([
        {"action": "spawn", "role": "researcher", "purpose": "Gather requirements",
         "capabilities": ["reason"], "question_id": "spoofed-from-model"},
        {"action": "wait", "reason": "worker running"},
        {"action": "finish", "summary": "Researcher gathered requirements."},
    ]))
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    events = store.events(mission.id)
    assert any(event.event_type == EventType.ORG_CHANGED and event.payload.get("op") == "spawn" for event in events)
    assert not any(event.event_type == "mission.question" for event in events)


@pytest.mark.asyncio
async def test_direct_apply_parks_until_approve(tmp_path):
    from app.org import OrganizationDesigner

    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    runtime = SwarmRuntime(store, controller=OrgScriptController([]))
    root, _lead, worker = await seed_tree(runtime, mission)
    designer = OrganizationDesigner()
    change = designer.propose({"action": "retire", "agent_id": str(worker.id), "question_id": "spoofed-from-model"})
    job = asyncio.create_task(designer.apply(runtime, mission, root, change))
    waiting = await wait_until_org_question(store, mission.id)
    assert waiting.pending_question.question_id != "spoofed-from-model"
    assert waiting.pending_question.approval_action == f"org_change:retire:{worker.id}"
    assert next(agent for agent in store.load_agents(mission.id) if agent.id == worker.id).status != AgentStatus.STOPPED
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "approve")
    retired = await asyncio.wait_for(job, 2)
    assert retired.id == worker.id
    assert next(agent for agent in store.load_agents(mission.id) if agent.id == worker.id).status == AgentStatus.STOPPED
