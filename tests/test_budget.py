from uuid import uuid4

import pytest

from app.budget import (
    MissionBudget, TokenPrices, budget_status, estimate_call_cost, parse_token_prices,
    require_token_meters_from_env, usage_from_meta,
)
from app.llm import FallbackController, LLMProvider
from app.models import FailureClass, Mission
from app.policy import PolicyError
from app.providers import ModelUsage
from app.runtime import SwarmRuntime
from app.store import Store
from app.verifier import local_evidence_check


class MeteredFinishController(LLMProvider):
    mode = "test"

    def __init__(self, *, include_meters: bool = True, extra_meta: dict | None = None):
        self.include_meters = include_meters
        self.extra_meta = extra_meta or {}

    def _meta(self, input_tokens: int, output_tokens: int, reasoning_tokens: int = 0) -> dict:
        meta = {"provider": "openai", "model": "gpt-test", **self.extra_meta}
        if self.include_meters:
            meta.update({
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
            })
        return meta

    async def decide(self, state):
        return {
            "action": "finish",
            "summary": "Metered finish",
            "_meta": self._meta(10, 5, 2),
        }

    async def verify(self, state, claim):
        result = local_evidence_check(state, claim)
        result["_meta"] = self._meta(3, 1, 0)
        return result


def test_missing_metadata_is_unmetered_by_default():
    usage, metered = usage_from_meta(None)
    assert usage is None and metered is False
    usage, metered = usage_from_meta({"provider": "openai", "model": "gpt"})
    assert usage is None and metered is False


def test_zero_tokens_with_keys_is_metered():
    usage, metered = usage_from_meta({"input_tokens": 0, "output_tokens": 0})
    assert metered is True
    assert usage == ModelUsage()


def test_invalid_token_values_fail_closed():
    with pytest.raises(PolicyError) as exc:
        usage_from_meta({"input_tokens": -1, "output_tokens": 0})
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(PolicyError) as exc:
        usage_from_meta({"input_tokens": "12", "output_tokens": 0})
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT


def test_observe_only_skips_calls_without_metadata():
    budget = MissionBudget()
    mission_id = uuid4()
    assert budget.record(mission_id, "decision", None) is None
    assert budget.snapshot(mission_id) is None


def test_require_meters_fails_closed_when_missing():
    budget = MissionBudget(require_meters=True)
    with pytest.raises(PolicyError) as exc:
        budget.record(uuid4(), "decision", None)
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    with pytest.raises(PolicyError) as exc:
        budget.record(uuid4(), "decision", {"provider": "openai", "model": "gpt"})
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    assert "missing" in str(exc.value)


def test_records_tokens_and_unknown_cost_by_default():
    budget = MissionBudget()
    mission_id = uuid4()
    first = budget.record(mission_id, "decision", {
        "provider": "openai", "model": "gpt-test",
        "input_tokens": 10, "output_tokens": 5, "reasoning_tokens": 2,
    })
    second = budget.record(mission_id, "verification", {
        "provider": "openrouter", "model": "openai/gpt-4o",
        "input_tokens": 3, "output_tokens": 1,
    })
    assert first.metered and first.cost_known is False
    assert first.estimated_cost_usd is None
    assert second.provider == "openrouter"
    snap = budget.snapshot(mission_id)
    assert snap["observe_only"] is True
    assert snap["calls"] == 2
    assert snap["input_tokens"] == 13
    assert snap["output_tokens"] == 6
    assert snap["reasoning_tokens"] == 2
    assert snap["total_tokens"] == 21
    assert snap["estimated_cost_usd"] is None
    assert snap["cost_known"] is False
    assert snap["cost_complete"] is False
    assert snap["by_provider"]["openai"]["calls"] == 1
    assert snap["by_provider"]["openrouter"]["input_tokens"] == 3


def test_configured_prices_estimate_usd_without_enforcing_caps():
    prices = {"openai": TokenPrices(input_per_million=5, output_per_million=15)}
    budget = MissionBudget(prices=prices)
    mission_id = uuid4()
    call = budget.record(mission_id, "decision", {
        "provider": "openai", "model": "gpt-test",
        "input_tokens": 1_000_000, "output_tokens": 1_000_000, "reasoning_tokens": 0,
    })
    assert call.cost_known is True
    assert call.estimated_cost_usd == 20.0
    assert call.observe_only is True
    snap = budget.snapshot(mission_id)
    assert snap["estimated_cost_usd"] == 20.0
    assert snap["cost_complete"] is True


def test_local_provider_cost_is_known_zero():
    cost, known, reason = estimate_call_cost("ollama", ModelUsage(input_tokens=9, output_tokens=4), None)
    assert cost == 0.0 and known is True
    assert "Local" in reason
    budget = MissionBudget()
    call = budget.record(uuid4(), "work", {
        "provider": "vllm", "model": "local", "input_tokens": 9, "output_tokens": 4,
    })
    assert call.cost_known is True
    assert call.estimated_cost_usd == 0.0


def test_unmetered_metadata_is_recorded_when_observe_only():
    budget = MissionBudget()
    mission_id = uuid4()
    call = budget.record(mission_id, "decision", {"provider": "openai", "model": "gpt-test"})
    assert call is not None
    assert call.metered is False
    snap = budget.snapshot(mission_id)
    assert snap["calls"] == 1
    assert snap["unmetered_calls"] == 1
    assert snap["total_tokens"] == 0
    assert snap["cost_complete"] is False


def test_parse_token_prices_fail_closed_on_invalid_config():
    assert parse_token_prices(None) == {}
    assert parse_token_prices("  ") == {}
    parsed = parse_token_prices('{"openai:gpt-test":{"input":1.5,"output":2}}')
    assert parsed["openai:gpt-test"].input_per_million == 1.5
    with pytest.raises(PolicyError) as exc:
        parse_token_prices("{")
    assert exc.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(PolicyError):
        parse_token_prices('{"openai":{"input":-1,"output":1}}')


def test_require_token_meters_env_defaults_off(monkeypatch):
    monkeypatch.delenv("SWARM_REQUIRE_TOKEN_METERS", raising=False)
    assert require_token_meters_from_env() is False
    monkeypatch.setenv("SWARM_REQUIRE_TOKEN_METERS", "1")
    assert require_token_meters_from_env() is True
    monkeypatch.setenv("SWARM_REQUIRE_TOKEN_METERS", "no")
    assert require_token_meters_from_env() is False
    status = budget_status(require_meters=False)
    assert status == {
        "observe_only": True,
        "require_token_meters": False,
        "resource_scheduler": False,
    }


@pytest.mark.asyncio
async def test_runtime_surfaces_token_budget_on_result_and_events(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    prices = {"openai": TokenPrices(input_per_million=1, output_per_million=2)}
    runtime = SwarmRuntime(
        store,
        controller=MeteredFinishController(),
        budget=MissionBudget(prices=prices),
    )
    mission = Mission(goal="Account for tokens")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "Metered finish"
    budget = saved.result["token_budget"]
    assert budget["observe_only"] is True
    assert budget["calls"] == 2
    assert budget["input_tokens"] == 13
    assert budget["output_tokens"] == 6
    assert budget["reasoning_tokens"] == 2
    assert budget["total_tokens"] == 21
    assert budget["cost_known"] is True
    assert budget["estimated_cost_usd"] == pytest.approx(0.000029)
    assert saved.spent == 0
    events = store.events(mission.id)
    recorded = [e for e in events if e.event_type == "budget.recorded"]
    assert len(recorded) == 2
    assert recorded[0].payload["kind"] == "decision"
    assert recorded[0].payload["totals"]["calls"] == 1
    assert recorded[1].payload["totals"]["calls"] == 2
    summaries = [e for e in events if e.event_type == "budget.summary"]
    assert len(summaries) == 1
    assert summaries[0].payload["total_tokens"] == 21
    completed = [e for e in events if e.event_type == "mission.completed"]
    assert completed[-1].payload["token_budget"]["total_tokens"] == 21
    llm = [e for e in events if e.event_type == "llm.completed"]
    assert llm[0].payload["cost_known"] is True


@pytest.mark.asyncio
async def test_demo_controller_stays_observe_only_without_budget_events(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert "token_budget" not in (saved.result or {})
    types = {e.event_type for e in store.events(mission.id)}
    assert "budget.recorded" not in types
    assert "budget.summary" not in types


@pytest.mark.asyncio
async def test_require_meters_fails_unmetered_runtime_call(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=MeteredFinishController(include_meters=False),
        budget=MissionBudget(require_meters=True),
    )
    mission = Mission(goal="Refuse missing meters")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "RESOURCE_EXHAUSTED"
    assert "missing" in saved.result["error"]
    assert "token_budget" not in saved.result
    types = {e.event_type for e in store.events(mission.id)}
    assert "budget.recorded" not in types
    assert "mission.completed" not in types


@pytest.mark.asyncio
async def test_observe_only_unmetered_call_does_not_fail_mission(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=MeteredFinishController(include_meters=False),
        budget=MissionBudget(require_meters=False),
    )
    mission = Mission(goal="Allow missing meters")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["token_budget"]["unmetered_calls"] == 2
    assert saved.result["token_budget"]["total_tokens"] == 0
    assert saved.result["token_budget"]["cost_complete"] is False
