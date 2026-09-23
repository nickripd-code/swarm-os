import asyncio
from uuid import uuid4

import pytest

from app.events import EventType, UnknownEventType
from app.llm import FallbackController, LLMProvider, OpenAIProvider
from app.models import (
    AgentSpec, AgentStatus, FailureClass, Mission, MissionAnswer, MissionEvent, MissionStatus,
    Task, TaskStatus,
)
from app.org import OrgChange, OrganizationDesigner, is_org_action
from app.planning import VALID_ACTIONS, validate_decision
from app.policy import ApprovalRequirement, PolicyError, approval_action_key
from app.providers import ProviderError
from app.router import ModelRouter
from app.runtime import SwarmRuntime
from app.store import Store
from tests.test_planning import COMPLEX_GOAL, ScriptedProvider, scripted_openai, scripted_openrouter


class OrgScriptController(LLMProvider):
    mode = "openai"

    def __init__(self, decisions: list[dict]):
        self.decisions = list(decisions)
        self.calls = 0

    async def decide(self, state):
        del state
        if self.calls >= len(self.decisions):
            return {"action": "finish", "summary": "Organization change applied and goal satisfied."}
        decision = self.decisions[self.calls]
        self.calls += 1
        return decision

    async def work(self, state, agent):
        del state
        return {"status": "completed", "finding": f"Simulated output for {agent['role']}", "limitations": []}

    async def verify(self, state, claim):
        del state
        return {
            "verdict": "pass",
            "rationale": "Claim matches the supplied mission artifacts.",
            "evidence": [str((claim or {}).get("summary") or "")],
        }


async def seed_tree(runtime: SwarmRuntime, mission: Mission) -> tuple[AgentSpec, AgentSpec, AgentSpec]:
    root = await runtime.spawn(
        mission, "mission_controller", "Delegate work",
        capabilities=["spawn", "coordinate", "reason"],
    )
    await runtime.agent_status(root, AgentStatus.RUNNING)
    lead = await runtime.spawn(mission, "research_lead", "Lead research", root, ["reason"])
    await runtime.agent_status(lead, AgentStatus.COMPLETED)
    worker = await runtime.spawn(mission, "researcher", "Gather sources", lead, ["reason"])
    await runtime.agent_status(worker, AgentStatus.COMPLETED)
    for agent in (lead, worker):
        task = Task(
            mission_id=mission.id, agent_id=agent.id, title=agent.role,
            description=agent.purpose, status=TaskStatus.COMPLETED,
            output={"status": "completed", "finding": f"done:{agent.role}", "limitations": []},
        )
        runtime.tasks[mission.id].append(task)
        runtime.store.save_task(task)
    return root, lead, worker


async def wait_until_org_question(store: Store, mission_id, timeout: float = 8) -> Mission:
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


def grant_org_approval(mission: Mission, op: str, agent_id: str) -> None:
    """Pre-seed a matching approve so direct apply tests exercise mutation, not the park."""
    needed = ApprovalRequirement(
        action="org_change",
        question=f"Approve organization change '{op}'?",
        reason=f"Organization {op} requires human approval",
        org_op=op,
    )
    mission.answers.append(MissionAnswer(
        question_id=f"grant-{op}-{agent_id}",
        question=needed.question,
        answer="approve",
        kind="approval",
        approval_action=approval_action_key(needed, agent_id=agent_id),
    ))


def test_org_actions_are_valid_decisions():
    assert {"replace", "reparent", "retire"} <= VALID_ACTIONS
    assert is_org_action("spawn")
    assert validate_decision({"action": "reparent", "agent_id": "abc"})["action"] == "reparent"
    with pytest.raises(ProviderError) as exc:
        validate_decision({"action": "merge"})
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT


def test_propose_maps_judged_plan_and_rejects_batches():
    designer = OrganizationDesigner()
    judged = {
        "action": "replace",
        "agent_id": "spec-1",
        "role": "analyst",
        "purpose": "Replace the stalled researcher",
        "capabilities": ["reason"],
        "parent_id": None,
    }
    change = designer.propose(judged, [])
    assert change is not None
    assert change.op == "replace"
    assert change.agent_id == "spec-1"
    assert designer.propose({"action": "finish", "summary": "done"}) is None
    with pytest.raises(PolicyError) as batch:
        designer.propose({"action": "spawn", "role": "x", "purpose": "y", "org_changes": [{"op": "spawn"}]})
    assert batch.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(PolicyError) as missing:
        designer.propose({"action": "retire"})
    assert missing.value.failure_class == FailureClass.INVALID_OUTPUT


@pytest.mark.asyncio
async def test_apply_spawn_emits_org_changed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    root = await runtime.spawn(mission, "mission_controller", "Delegate", capabilities=["spawn", "coordinate", "reason"])
    designer = OrganizationDesigner()
    child = await designer.apply(runtime, mission, root, designer.propose({
        "action": "spawn", "role": "researcher", "purpose": "Gather requirements", "capabilities": ["reason"],
    }))
    assert child is not None
    saved = store.load_agents(mission.id)
    assert any(agent.id == child.id and agent.parent_id == root.id for agent in saved)
    types = [event.event_type for event in store.events(mission.id)]
    assert EventType.AGENT_SPAWNED in types
    assert EventType.ORG_CHANGED in types
    changed = [event for event in store.events(mission.id) if event.event_type == EventType.ORG_CHANGED]
    assert changed[-1].payload["op"] == "spawn"
    assert changed[-1].payload["agent_id"] == str(child.id)


@pytest.mark.asyncio
async def test_apply_reparent_persists_and_projects(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    root, lead, worker = await seed_tree(runtime, mission)
    grant_org_approval(mission, "reparent", str(worker.id))
    designer = OrganizationDesigner()
    await designer.apply(runtime, mission, root, designer.propose({
        "action": "reparent", "agent_id": str(worker.id), "parent_id": str(root.id),
    }))
    reloaded = {agent.id: agent for agent in store.load_agents(mission.id)}
    assert reloaded[worker.id].parent_id == root.id
    assert reloaded[worker.id].depth == 1
    events = store.events(mission.id)
    assert any(event.event_type == EventType.AGENT_REPARENTED for event in events)
    assert any(event.event_type == EventType.ORG_CHANGED and event.payload.get("op") == "reparent"
               for event in events)
    projected = store.project_events(mission.id)
    match = next(item for item in projected["agents"] if item["id"] == str(worker.id))
    assert match["parent_id"] == str(root.id)


@pytest.mark.asyncio
async def test_apply_retire_and_replace(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal=COMPLEX_GOAL, limits={"max_agents": 6, "max_depth": 4})
    store.save_mission(mission)
    root, lead, worker = await seed_tree(runtime, mission)
    grant_org_approval(mission, "retire", str(worker.id))
    designer = OrganizationDesigner()
    await designer.apply(runtime, mission, root, designer.propose({
        "action": "retire", "agent_id": str(worker.id),
    }))
    retired = next(agent for agent in store.load_agents(mission.id) if agent.id == worker.id)
    assert retired.status == AgentStatus.STOPPED
    assert any(event.event_type == EventType.AGENT_RETIRED for event in store.events(mission.id))
    created = await runtime._assign_unassigned_tasks(mission)
    assert created == []

    grant_org_approval(mission, "replace", str(lead.id))
    replacement = await designer.apply(runtime, mission, root, designer.propose({
        "action": "replace",
        "agent_id": str(lead.id),
        "role": "research_lead",
        "purpose": "Lead a tighter research pass",
        "capabilities": ["reason", "review"],
        "parent_id": str(root.id),
    }))
    assert replacement is not None
    agents = {agent.id: agent for agent in store.load_agents(mission.id)}
    assert agents[lead.id].status == AgentStatus.STOPPED
    assert agents[replacement.id].parent_id == root.id
    assert agents[replacement.id].role == "research_lead"
    assert agents[worker.id].parent_id == replacement.id
    changed = [event for event in store.events(mission.id) if event.event_type == EventType.ORG_CHANGED]
    assert changed[-1].payload["op"] == "replace"
    assert changed[-1].payload["replaced_id"] == str(lead.id)


@pytest.mark.asyncio
async def test_fail_closed_unknown_target_cycle_controller_inflight(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal=COMPLEX_GOAL, limits={"max_depth": 4, "max_agents": 8})
    store.save_mission(mission)
    root, lead, worker = await seed_tree(runtime, mission)
    designer = OrganizationDesigner()

    with pytest.raises(PolicyError) as unknown:
        await designer.apply(runtime, mission, root, designer.propose({
            "action": "retire", "agent_id": str(uuid4()),
        }))
    assert unknown.value.failure_class == FailureClass.INVALID_OUTPUT

    with pytest.raises(PolicyError) as controller:
        await designer.apply(runtime, mission, root, designer.propose({
            "action": "retire", "agent_id": str(root.id),
        }))
    assert controller.value.failure_class == FailureClass.POLICY_REFUSAL

    with pytest.raises(PolicyError) as cycle:
        await designer.apply(runtime, mission, root, designer.propose({
            "action": "reparent", "agent_id": str(lead.id), "parent_id": str(worker.id),
        }))
    assert cycle.value.failure_class == FailureClass.INVALID_OUTPUT

    with pytest.raises(PolicyError) as descendants:
        await designer.apply(runtime, mission, root, designer.propose({
            "action": "retire", "agent_id": str(lead.id),
        }))
    assert "live descendants" in str(descendants.value)

    pending = Task(
        mission_id=mission.id, agent_id=worker.id, title="still going",
        description="in flight", status=TaskStatus.PENDING,
    )
    runtime.tasks[mission.id].append(pending)
    with pytest.raises(PolicyError) as inflight:
        await designer.apply(runtime, mission, root, designer.propose({
            "action": "retire", "agent_id": str(worker.id),
        }))
    assert inflight.value.failure_class == FailureClass.INVALID_OUTPUT

    bogus = OrgChange.model_construct(op="merge", agent_id=str(worker.id))
    with pytest.raises(PolicyError) as unknown_op:
        await designer.apply(runtime, mission, root, bogus)
    assert unknown_op.value.failure_class == FailureClass.INVALID_OUTPUT

    before = [event.event_type for event in store.events(mission.id)]
    assert EventType.ORG_CHANGED not in before or all(
        event.payload.get("op") != "merge" for event in store.events(mission.id)
        if event.event_type == EventType.ORG_CHANGED
    )
    with pytest.raises(UnknownEventType):
        store.append(MissionEvent(mission_id=mission.id, event_type="org.invented", payload={}))


@pytest.mark.asyncio
async def test_runtime_applies_controller_reparent(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    mission = Mission(goal=COMPLEX_GOAL, status="pending")
    store.save_mission(mission)
    runtime = SwarmRuntime(store, controller=FallbackController())
    root, lead, worker = await seed_tree(runtime, mission)
    runtime.controller = OrgScriptController([
        {"action": "reparent", "agent_id": str(worker.id), "parent_id": str(root.id),
         "question_id": "spoofed-from-model"},
        {"action": "finish", "summary": "Research lead remains; worker now reports to the controller."},
    ])
    job = asyncio.create_task(runtime.run(mission))
    waiting = await wait_until_org_question(store, mission.id)
    assert waiting.pending_question.question_id != "spoofed-from-model"
    assert waiting.pending_question.approval_action == f"org_change:reparent:{worker.id}"
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "approve")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    agents = {agent.id: agent for agent in store.load_agents(mission.id)}
    assert agents[worker.id].parent_id == root.id
    assert agents[lead.id].id == lead.id
    assert any(event.event_type == EventType.ORG_CHANGED and event.payload.get("op") == "reparent"
               for event in store.events(mission.id))
    assert not any(event.event_type == "controller.fallback" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_high_stakes_judge_spawn_emits_org_changed(tmp_path):
    openai = scripted_openai(
        planner_output={"action": "spawn", "role": "researcher", "purpose": "Gather requirements",
                        "parent_id": None, "capabilities": ["reason"], "summary": None, "reason": None,
                        "agent_id": None},
        judge_output={"action": "spawn", "role": "researcher", "purpose": "Gather requirements",
                      "parent_id": None, "capabilities": ["reason"], "summary": None, "reason": None,
                      "agent_id": None},
        verify_output={
            "verdict": "pass",
            "rationale": "Claim matches the supplied mission artifacts.",
            "evidence": ["Researcher gathered requirements."],
        },
    )
    openrouter = scripted_openrouter(
        planner_output={"action": "finish", "summary": "too early", "role": None, "purpose": None,
                        "parent_id": None, "capabilities": [], "reason": None, "agent_id": None},
    )
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))

    class AfterSpawnFinish(LLMProvider):
        mode = "openai"

        def __init__(self, inner):
            self.inner = inner
            self.rounds = 0
            self.last_planning = None

        async def decide(self, state):
            if self.rounds == 0:
                self.rounds += 1
                result = await self.inner.decide(state)
                self.last_planning = getattr(self.inner, "last_planning", None)
                return result
            specialists = [agent for agent in state["agents"] if agent["role"] != "mission_controller"]
            if any(task["status"] in {"pending", "running"} for task in state["tasks"]):
                return {"action": "wait", "reason": "Allow the judged specialist to finish."}
            if specialists:
                return {"action": "finish", "summary": "Researcher gathered requirements."}
            return await self.inner.decide(state)

        async def work(self, state, agent):
            del state
            return {"status": "completed", "finding": f"done:{agent['role']}", "limitations": []}

        async def verify(self, state, claim):
            return await self.inner.verify(state, claim)

    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=AfterSpawnFinish(controller))
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    events = store.events(mission.id)
    assert any(event.event_type == "planner.proposal" for event in events)
    assert any(event.event_type == "judge.decision" for event in events)
    assert any(event.event_type == EventType.ORG_CHANGED and event.payload.get("op") == "spawn"
               for event in events)
    assert openai.kinds.count("judge") == 1
    assert not any(event.event_type == "controller.fallback" for event in events)


@pytest.mark.asyncio
async def test_judged_replace_is_applied_from_high_stakes_decide(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    root, lead, worker = await seed_tree(runtime, mission)
    judged = {
        "action": "replace",
        "agent_id": str(lead.id),
        "role": "research_lead",
        "purpose": "Replace the original lead after judged review",
        "parent_id": str(root.id),
        "capabilities": ["reason"],
    }
    openai = scripted_openai(planner_output=judged, judge_output=judged)
    openrouter = scripted_openrouter(planner_output={
        "action": "wait", "reason": "stalled", "role": None, "purpose": None,
        "parent_id": None, "capabilities": [], "agent_id": None,
    })
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    state = runtime._state(mission)
    decision = await controller.decide(state)
    assert decision["action"] == "replace"
    assert decision["_meta"]["planning"]["judge"]["action"] == "replace"
    change = runtime.org.propose(decision, runtime.agents[mission.id])
    grant_org_approval(mission, "replace", str(lead.id))
    replacement = await runtime.org.apply(runtime, mission, root, change)
    agents = {agent.id: agent for agent in store.load_agents(mission.id)}
    assert agents[lead.id].status == AgentStatus.STOPPED
    assert agents[replacement.id].purpose == judged["purpose"]
    assert agents[worker.id].parent_id == replacement.id
    assert any(event.event_type == EventType.ORG_CHANGED and event.payload.get("op") == "replace"
               for event in store.events(mission.id))
