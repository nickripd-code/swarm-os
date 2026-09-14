import pytest

from app.llm import OpenAIProvider
from app.models import FailureClass, Mission
from app.planning import (
    is_high_stakes_decide, is_trivial_goal, planner_count_from_env, should_use_multi_planner,
)
from app.providers import ModelCapabilities, ProviderError
from app.router import ModelRouter, RouteCandidate
from app.runtime import SwarmRuntime
from app.store import Store
from tests.test_router import FakeModelProvider, REQUEST, openai_like, openrouter_like

COMPLEX_GOAL = "Build and launch a landing page and verify the public result"
START_STATE = {"goal": COMPLEX_GOAL, "agents": [], "tasks": []}


class ScriptedProvider(FakeModelProvider):
    def __init__(self, *args, planner_output=None, judge_output=None, error_on=None,
                 verify_output=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner_output = planner_output or self.output
        self.judge_output = judge_output or self.output
        self.error_on = error_on
        if verify_output is not None:
            self.verify_output = verify_output
        self.kinds: list[str] = []
        self.inputs: list[object] = []

    async def complete(self, request):
        payload = request.input if isinstance(request.input, dict) else {}
        if isinstance(payload, dict) and "claim" in payload:
            kind = "verification"
        elif isinstance(payload, dict) and "proposals" in payload:
            kind = "judge"
        else:
            kind = "planner"
        self.kinds.append(kind)
        self.inputs.append(request.input)
        self.calls += 1
        self.requested_models.append(request.model)
        if self.error is not None and (self.error_on is None or self.error_on == kind):
            raise self.error
        if kind == "verification":
            output = self.verify_output or {
                "verdict": "pass",
                "rationale": "Claim matches the supplied mission artifacts.",
                "evidence": [str((payload.get("claim") or {}).get("summary") or "")],
            }
        elif kind == "judge":
            output = self.judge_output
        else:
            output = self.planner_output
        from app.providers import ModelResponse, ModelUsage
        usage = ModelUsage(input_tokens=1, output_tokens=2)
        self._usage = self._usage.plus(usage)
        return ModelResponse(provider=self.provider_id, model=request.model, output=output,
                             response_id=f"{self.provider_id}-{kind}", usage=usage)


def scripted_openai(**kwargs) -> ScriptedProvider:
    caps = kwargs.pop("capabilities", ModelCapabilities(
        reasoning="high", coding="high", tool_use=True, structured_outputs=True, vision=False,
    ))
    return ScriptedProvider("openai", "gpt-6-astra", capabilities=caps, **kwargs)


def scripted_openrouter(**kwargs) -> ScriptedProvider:
    caps = kwargs.pop("capabilities", ModelCapabilities(
        reasoning="unknown", coding="unknown", tool_use=True, structured_outputs=True, vision=False,
    ))
    return ScriptedProvider("openrouter", "openai/gpt-4o", capabilities=caps, **kwargs)


def scripted_ollama(**kwargs) -> ScriptedProvider:
    caps = kwargs.pop("capabilities", ModelCapabilities(
        reasoning="unknown", coding="unknown", tool_use=True, structured_outputs=True, vision=False,
    ))
    return ScriptedProvider("ollama", "llama3.2", local=True, capabilities=caps, **kwargs)


def test_trivial_goals_are_cost_aware():
    assert is_trivial_goal("route me")
    assert is_trivial_goal("Recover from an OpenAI outage via the router")
    assert not is_trivial_goal(COMPLEX_GOAL)


def test_high_stakes_is_start_or_finish_verification_only():
    assert is_high_stakes_decide({"agents": [], "tasks": []})
    assert is_high_stakes_decide({
        "agents": [{"role": "mission_controller"}, {"role": "researcher"}],
        "tasks": [{"status": "completed"}],
    })
    assert not is_high_stakes_decide({
        "agents": [{"role": "mission_controller"}, {"role": "researcher"}],
        "tasks": [{"status": "running"}],
    })


def test_openai_only_and_disabled_flag_skip_multi_planner(monkeypatch):
    assert not should_use_multi_planner(START_STATE, 1)
    assert should_use_multi_planner(START_STATE, 2)
    monkeypatch.setenv("SWARM_MULTI_PLANNER", "0")
    assert not should_use_multi_planner(START_STATE, 2)


def test_planner_count_env_clamps(monkeypatch):
    monkeypatch.delenv("SWARM_PLANNER_COUNT", raising=False)
    assert planner_count_from_env() == 3
    monkeypatch.setenv("SWARM_PLANNER_COUNT", "2")
    assert planner_count_from_env() == 2
    monkeypatch.setenv("SWARM_PLANNER_COUNT", "99")
    assert planner_count_from_env() == 4


@pytest.mark.asyncio
async def test_openai_only_stays_single_planner():
    openai = scripted_openai(output={"action": "finish", "summary": "solo"})
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai]))
    result = await controller.decide(START_STATE)
    assert result["action"] == "finish"
    assert result["summary"] == "solo"
    assert openai.calls == 1
    assert controller.last_planning is None
    assert "planning" not in result.get("_meta", {})


@pytest.mark.asyncio
async def test_trivial_goal_skips_multi_planner_with_two_providers():
    openai = scripted_openai(output={"action": "finish", "summary": "cheap"})
    openrouter = scripted_openrouter()
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    result = await controller.decide({"goal": "route me", "agents": [], "tasks": []})
    assert result["_meta"]["provider"] == "openai"
    assert openai.calls == 1
    assert openrouter.calls == 0
    assert controller.last_planning is None


@pytest.mark.asyncio
async def test_high_stakes_start_runs_independent_planners_and_judge():
    openai = scripted_openai(
        planner_output={"action": "spawn", "role": "researcher", "purpose": "Gather requirements",
                        "parent_id": None, "capabilities": ["reason"], "summary": None, "reason": None},
        judge_output={"action": "spawn", "role": "researcher", "purpose": "Gather requirements",
                      "parent_id": None, "capabilities": ["reason"], "summary": None, "reason": None},
    )
    openrouter = scripted_openrouter(
        planner_output={"action": "finish", "summary": "too early", "role": None, "purpose": None,
                        "parent_id": None, "capabilities": [], "reason": None},
        judge_output={"action": "finish", "summary": "should not win"},
    )
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    result = await controller.decide(START_STATE)
    assert result["action"] == "spawn"
    assert result["role"] == "researcher"
    assert openai.calls == 2  # planner + judge (judge ranks openai first)
    assert openrouter.calls == 1
    assert openai.kinds.count("planner") == 1
    assert openai.kinds.count("judge") == 1
    assert openrouter.kinds == ["planner"]
    for kind, payload in zip(openai.kinds, openai.inputs):
        if kind == "planner":
            assert not (isinstance(payload, dict) and "proposals" in payload)
    planning = result["_meta"]["planning"]
    assert planning["mode"] == "multi"
    assert {item["provider"] for item in planning["proposals"]} == {"openai", "openrouter"}
    assert planning["judge"]["action"] == "spawn"
    assert planning["judge"]["successful_planners"] == 2


@pytest.mark.asyncio
async def test_finish_verification_uses_multi_planner():
    openai = scripted_openai(
        planner_output={"action": "finish", "summary": "Page is live and verified"},
        judge_output={"action": "finish", "summary": "Page is live and verified"},
    )
    openrouter = scripted_openrouter(
        planner_output={"action": "finish", "summary": "Ship it"},
    )
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    state = {
        "goal": COMPLEX_GOAL,
        "agents": [{"role": "mission_controller"}, {"role": "builder"}],
        "tasks": [{"status": "completed", "output": {"finding": "landing page html"}}],
    }
    result = await controller.decide(state)
    assert result["action"] == "finish"
    assert result["summary"] == "Page is live and verified"
    assert openai.calls + openrouter.calls == 3


@pytest.mark.asyncio
async def test_mid_flight_decide_stays_single_planner():
    openai = scripted_openai(output={"action": "wait", "reason": "worker running"})
    openrouter = scripted_openrouter()
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    result = await controller.decide({
        "goal": COMPLEX_GOAL,
        "agents": [{"role": "mission_controller"}, {"role": "builder"}],
        "tasks": [{"status": "running"}],
    })
    assert result["action"] == "wait"
    assert openai.calls == 1
    assert openrouter.calls == 0


@pytest.mark.asyncio
async def test_planner_count_env_limits_to_two_of_three(monkeypatch):
    monkeypatch.setenv("SWARM_PLANNER_COUNT", "2")
    openai = scripted_openai(
        planner_output={"action": "finish", "summary": "a"},
        judge_output={"action": "finish", "summary": "judged"},
    )
    openrouter = scripted_openrouter(planner_output={"action": "finish", "summary": "b"})
    ollama = scripted_ollama(planner_output={"action": "finish", "summary": "c"})
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter, ollama]))
    result = await controller.decide(START_STATE)
    assert result["summary"] == "judged"
    assert openai.calls + openrouter.calls + ollama.calls == 3
    assert ollama.calls == 0


@pytest.mark.asyncio
async def test_one_planner_failure_still_judges():
    openai = scripted_openai(
        error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE),
        error_on="planner",
        judge_output={"action": "finish", "summary": "from remaining planner"},
    )
    openrouter = scripted_openrouter(planner_output={"action": "finish", "summary": "or plan"})
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    result = await controller.decide(START_STATE)
    assert result["action"] == "finish"
    assert result["summary"] == "from remaining planner"
    failed = [item for item in result["_meta"]["planning"]["proposals"] if item["status"] == "failed"]
    assert failed and failed[0]["provider"] == "openai"
    assert result["_meta"]["planning"]["judge"]["successful_planners"] == 1


@pytest.mark.asyncio
async def test_all_planners_fail_closed_no_demo_success(tmp_path):
    openai = scripted_openai(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = scripted_openrouter(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "PROVIDER_OUTAGE"
    events = store.events(mission.id)
    proposals = [e for e in events if e.event_type == "planner.proposal"]
    assert len(proposals) == 2
    assert all(e.payload["status"] == "failed" for e in proposals)
    assert not any(e.event_type == "judge.decision" for e in events)
    assert not any(e.event_type in {"controller.fallback", "mission.completed"} for e in events)


@pytest.mark.asyncio
async def test_judge_failure_fails_closed(tmp_path):
    openai = scripted_openai(
        planner_output={"action": "finish", "summary": "a"},
        error=ProviderError("OpenAI quota or rate limit reached", FailureClass.RATE_LIMIT),
        error_on="judge",
    )
    openrouter = scripted_openrouter(planner_output={"action": "finish", "summary": "b"})
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller, max_retries=0)
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result == {
        "error": "OpenAI quota or rate limit reached",
        "failure_class": "RATE_LIMIT",
    }
    events = store.events(mission.id)
    assert len([e for e in events if e.event_type == "planner.proposal"]) == 2
    assert not any(e.event_type == "judge.decision" for e in events)
    assert not any(e.event_type in {"controller.fallback", "mission.completed"} for e in events)


@pytest.mark.asyncio
async def test_runtime_emits_real_planner_and_judge_events(tmp_path):
    openai = scripted_openai(
        planner_output={"action": "finish", "summary": "draft a"},
        judge_output={"action": "finish", "summary": "synthesized answer"},
    )
    openrouter = scripted_openrouter(planner_output={"action": "finish", "summary": "draft b"})
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal=COMPLEX_GOAL)
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "synthesized answer"
    events = store.events(mission.id)
    proposals = [e for e in events if e.event_type == "planner.proposal"]
    assert len(proposals) == 2
    assert {e.payload["provider"] for e in proposals} == {"openai", "openrouter"}
    assert all(e.payload["status"] == "completed" for e in proposals)
    judges = [e for e in events if e.event_type == "judge.decision"]
    assert len(judges) == 1
    assert judges[0].payload["action"] == "finish"
    assert judges[0].payload["planner_count"] == 2
    assert not any(e.event_type == "controller.fallback" for e in events)


@pytest.mark.asyncio
async def test_complete_on_does_not_failover():
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(output={"action": "finish", "summary": "should not run"})
    router = ModelRouter([openai, openrouter])
    candidate = RouteCandidate(provider_id="openai", model="gpt-6-astra", score=1, reasons=[])
    with pytest.raises(ProviderError) as exc:
        await router.complete_on(candidate, REQUEST)
    assert exc.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert openrouter.calls == 0


@pytest.mark.asyncio
async def test_durable_recovery_apis_unchanged(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=OpenAIProvider(
        model_provider=openai_like(), router=ModelRouter([openai_like()]),
    ))
    assert runtime.hydrate.__name__ == "hydrate"
    assert runtime.resume_incomplete.__name__ == "resume_incomplete"
    assert runtime.suspend_all.__name__ == "suspend_all"
    assert await runtime.resume_incomplete() == []
    assert await runtime.suspend_all() == []
