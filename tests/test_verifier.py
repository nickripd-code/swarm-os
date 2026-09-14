import pytest

from app.llm import LLMProvider, OpenAIProvider
from app.models import FailureClass, Mission
from app.providers import ProviderError
from app.router import ModelRouter
from app.runtime import SwarmRuntime
from app.store import Store
from app.verifier import local_evidence_check, validate_verification, verification_accepted
from tests.test_router import openai_like, openrouter_like


class FinishOnlyProvider(LLMProvider):
    async def decide(self, state):
        return {"action": "finish", "summary": "The answer is 42"}


class RejectingVerifier(FinishOnlyProvider):
    def __init__(self, verdict="fail", rationale="Objective is unmet"):
        self.verdict = verdict
        self.rationale = rationale

    async def verify(self, state, claim):
        return {"verdict": self.verdict, "rationale": self.rationale, "evidence": []}


class PassingVerifier(FinishOnlyProvider):
    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


def test_validate_verification_rejects_missing_verdict():
    with pytest.raises(ProviderError) as exc:
        validate_verification({"action": "finish", "summary": "done"})
    assert exc.value.failure_class == FailureClass.VERIFICATION_FAILURE
    assert not verification_accepted({"action": "finish", "summary": "done"})


def test_local_evidence_check_fails_fabricated_and_empty_claims():
    state = {"goal": "Write a short answer", "agents": [], "tasks": []}
    empty = local_evidence_check(state, {"summary": ""})
    assert empty["verdict"] == "fail"
    fabricated = local_evidence_check(state, {"summary": "Deployed to https://example.com"})
    assert fabricated["verdict"] == "fail"
    text = local_evidence_check(state, {"summary": "Use a checklist and start with the riskiest assumption."})
    assert text["verdict"] == "pass"


def test_local_evidence_check_requires_worker_artifacts_when_specialists_exist():
    state = {
        "goal": "Research then write",
        "agents": [{"role": "mission_controller"}, {"role": "researcher"}],
        "tasks": [{"status": "completed", "output": {}}],
    }
    result = local_evidence_check(state, {"summary": "Research is done"})
    assert result["verdict"] == "fail"


@pytest.mark.asyncio
async def test_finish_without_verifier_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FinishOnlyProvider())
    mission = Mission(goal="Answer without a fake pass")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "VERIFICATION_FAILURE"
    events = store.events(mission.id)
    assert any(e.event_type == "verification.started" for e in events)
    failed = [e for e in events if e.event_type == "verification.failed"]
    assert failed and failed[-1].payload["verdict"] == "inconclusive"
    assert not any(e.event_type in {"verification.passed", "mission.completed"} for e in events)


@pytest.mark.asyncio
async def test_finish_rejected_by_verifier_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=RejectingVerifier())
    mission = Mission(goal="Do not accept an unsupported claim")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "VERIFICATION_FAILURE"
    assert "unmet" in saved.result["error"]
    events = store.events(mission.id)
    failed = [e for e in events if e.event_type == "verification.failed"]
    assert failed and failed[-1].payload["verdict"] == "fail"
    assert not any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_inconclusive_verifier_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=RejectingVerifier("inconclusive", "Not enough evidence"))
    mission = Mission(goal="Inconclusive is not success")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "VERIFICATION_FAILURE"
    events = store.events(mission.id)
    failed = [e for e in events if e.event_type == "verification.failed"]
    assert failed and failed[-1].payload["verdict"] == "inconclusive"
    assert not any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_verified_finish_emits_passed_and_completes(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingVerifier())
    mission = Mission(goal="A short text answer")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "The answer is 42"
    events = store.events(mission.id)
    assert any(e.event_type == "verification.started" for e in events)
    passed = [e for e in events if e.event_type == "verification.passed"]
    assert passed and passed[-1].payload["verdict"] == "pass"
    assert any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_openai_only_does_not_auto_pass(tmp_path):
    openai = openai_like(verify_output={
        "verdict": "inconclusive",
        "rationale": "Artifacts do not confirm the objective",
        "evidence": [],
    })
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai]))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Keep the OpenAI-only path honest")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "VERIFICATION_FAILURE"
    assert openai.calls >= 2
    events = store.events(mission.id)
    assert any(e.event_type == "verification.started" for e in events)
    assert any(e.event_type == "verification.failed" for e in events)
    assert not any(e.event_type in {"mission.completed", "controller.fallback"} for e in events)


@pytest.mark.asyncio
async def test_openai_only_router_verification_pass(tmp_path):
    openai = openai_like(output={"action": "finish", "summary": "A concise text answer"})
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai]))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Verify a text-only finish")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "A concise text answer"
    assert openai.calls >= 2
    events = store.events(mission.id)
    assert any(e.event_type == "verification.passed" for e in events)


@pytest.mark.asyncio
async def test_openai_only_invalid_verifier_output_fails_closed(tmp_path):
    openai = openai_like(
        output={"action": "finish", "summary": "Looks done"},
        verify_output={"action": "finish", "summary": "Looks done"},
    )
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai]))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Do not treat a finish blob as a pass")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "VERIFICATION_FAILURE"
    events = store.events(mission.id)
    failed = [e for e in events if e.event_type == "verification.failed"]
    assert failed and failed[-1].payload["verdict"] == "inconclusive"
    assert not any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_multi_provider_prefers_independent_verifier():
    openai = openai_like(output={"action": "finish", "summary": "Draft from OpenAI"})
    openrouter = openrouter_like()
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    result = await controller.verify(
        {"goal": "Write a short answer", "agents": [], "tasks": []},
        {"summary": "Draft from OpenAI"},
    )
    assert result["verdict"] == "pass"
    assert result["_meta"]["provider"] == "openrouter"
    assert openai.calls == 0
    assert openrouter.calls == 1


@pytest.mark.asyncio
async def test_openai_provider_local_precheck_blocks_fabricated_claim():
    openai = openai_like()
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai]))
    result = await controller.verify(
        {"goal": "Write a short answer", "agents": [], "tasks": []},
        {"summary": "Deployed to https://example.com and emailed the customer"},
    )
    assert result["verdict"] == "fail"
    assert openai.calls == 0
