import pytest

from app.llm import FallbackController, OpenAIProvider
from app.models import FailureClass, Mission
from app.policy import PolicyError
from app.providers import (
    ContextLimits, CostEstimate, ModelCapabilities, ModelDescriptor, ModelProvider,
    ModelRequest, ModelResponse, ModelUsage, ProviderHealth,
)
from app.resources import (
    ResourceScheduler, TokenCostSettings, TokenPrices, estimate_token_cost, usage_from_meta,
)
from app.router import ModelRouter
from app.runtime import SwarmRuntime
from app.store import Store


def test_estimate_math_uses_listed_prices_and_markup():
    usage = ModelUsage(input_tokens=1_000_000, output_tokens=500_000, reasoning_tokens=0)
    prices = TokenPrices(input_per_million=15, output_per_million=60, source="listed")
    estimate = estimate_token_cost(usage, prices, markup=1.0)
    assert estimate.known is True
    assert estimate.estimated_cost == 45.0
    marked = estimate_token_cost(usage, prices, markup=1.25)
    assert marked.estimated_cost == 56.25


def test_estimate_bills_reasoning_tokens_at_output_price():
    usage = ModelUsage(input_tokens=1000, output_tokens=2000, reasoning_tokens=500)
    prices = TokenPrices(input_per_million=10, output_per_million=20, source="listed")
    estimate = estimate_token_cost(usage, prices, markup=1.25)
    assert estimate.known is True
    assert estimate.estimated_cost == 0.075


def test_missing_price_metadata_does_not_invent_zero():
    usage = ModelUsage(input_tokens=11, output_tokens=7)
    estimate = estimate_token_cost(usage, None, markup=1.25)
    assert estimate.known is False
    assert estimate.estimated_cost is None
    assert estimate.reason == "missing price metadata"
    assert usage_from_meta({"provider": "openai", "model": "x"}) is None
    reported = usage_from_meta({"input_tokens": 11, "output_tokens": 7})
    assert reported == usage


def test_listed_zero_prices_are_known_free():
    usage = ModelUsage(input_tokens=40, output_tokens=10)
    prices = TokenPrices(input_per_million=0, output_per_million=0, source="listed")
    estimate = estimate_token_cost(usage, prices, markup=1.25)
    assert estimate.known is True
    assert estimate.estimated_cost == 0.0


def test_scheduler_uses_conservative_defaults_when_catalog_omits_prices():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_input_per_million=15, default_output_per_million=60, markup=1.0,
    ))
    estimate = scheduler.estimate(ModelUsage(input_tokens=1_000_000, output_tokens=0))
    assert estimate.known is True
    assert estimate.source == "default"
    assert estimate.estimated_cost == 15.0


def test_unknown_prices_fail_closed_when_tokens_were_used():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_input_per_million=None, default_output_per_million=None,
        unknown_price="fail", default_budget=3, hard_cap=10, markup=1.0,
    ))
    mission = Mission(goal="unknown prices fail")
    outcome = scheduler.consume(mission, ModelUsage(input_tokens=10, output_tokens=2))
    assert outcome.estimate.known is False
    assert outcome.estimate.estimated_cost is None
    assert mission.token_spent == 0
    assert outcome.error is not None
    assert outcome.error.failure_class == FailureClass.RESOURCE_EXHAUSTED


def test_unknown_prices_skip_estimate_honestly_when_configured():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_input_per_million=None, default_output_per_million=None,
        unknown_price="skip", default_budget=3, hard_cap=10, markup=1.0,
    ))
    mission = Mission(goal="unknown prices skip")
    outcome = scheduler.consume(mission, ModelUsage(input_tokens=10, output_tokens=2))
    assert outcome.estimate.known is False
    assert outcome.estimate.estimated_cost is None
    assert outcome.error is None
    assert mission.token_spent == 0


def test_under_budget_consume_succeeds_and_warns_once():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_budget=1.0, hard_cap=10, markup=1.0, warning_fraction=0.8,
        default_input_per_million=None, default_output_per_million=None,
    ))
    mission = Mission(goal="under", limits={"max_token_cost": 1.0})
    usage = ModelUsage(input_tokens=1_000_000, output_tokens=0)
    outcome = scheduler.consume(mission, usage, listed_input=0.9, listed_output=0)
    assert outcome.error is None
    assert outcome.estimate.known is True
    assert mission.token_spent == 0.9
    assert outcome.warning_crossed is True
    second = scheduler.consume(mission, ModelUsage(input_tokens=0, output_tokens=0),
                               listed_input=0.9, listed_output=0)
    assert second.warning_crossed is False
    assert mission.spent == 0


def test_over_budget_consume_records_spend_then_fails_closed():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_budget=1.0, hard_cap=10, markup=1.0,
        default_input_per_million=None, default_output_per_million=None,
    ))
    mission = Mission(goal="over", limits={"max_token_cost": 1.0})
    outcome = scheduler.consume(
        mission, ModelUsage(input_tokens=1_000_000, output_tokens=0),
        listed_input=1.5, listed_output=0,
    )
    assert mission.token_spent == 1.5
    assert outcome.error is not None
    assert outcome.error.failure_class == FailureClass.RESOURCE_EXHAUSTED
    assert "token budget" in str(outcome.error).lower()
    with pytest.raises(PolicyError) as exc:
        scheduler.authorize_start(mission)
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED


def test_per_agent_known_usd_matches_mission_total_and_persists(tmp_path):
    scheduler = ResourceScheduler(TokenCostSettings(
        default_budget=10, hard_cap=10, markup=1.0, warning_fraction=0.8,
        default_input_per_million=None, default_output_per_million=None,
    ))
    mission = Mission(goal="attribute", limits={"max_token_cost": 10})
    scheduler.consume(
        mission, ModelUsage(input_tokens=1_000_000, output_tokens=0),
        listed_input=1.0, listed_output=1.0, agent_id="agent-a",
    )
    second = scheduler.consume(
        mission, ModelUsage(input_tokens=0, output_tokens=500_000),
        listed_input=1.0, listed_output=2.0, agent_id="agent-b",
    )
    assert mission.token_spent == 2.0
    assert mission.agent_token_costs["agent-a"].known_usd == 1.0
    assert mission.agent_token_costs["agent-a"].input_tokens == 1_000_000
    assert mission.agent_token_costs["agent-b"].known_usd == 1.0
    assert mission.agent_token_costs["agent-b"].output_tokens == 500_000
    assert scheduler.known_agent_usd(mission) == mission.token_spent
    store = Store(str(tmp_path / "costs.db"))
    store.save_mission(mission)
    loaded = store.get_mission(mission.id)
    assert loaded is not None
    assert loaded.agent_token_costs["agent-a"].known_usd == 1.0
    assert scheduler.known_agent_usd(loaded) == loaded.token_spent
    payload = scheduler.snapshot(loaded, second.estimate)
    assert payload["token_spent"] == 2.0
    assert sum(row["known_usd"] for row in payload["by_agent"]) == payload["token_spent"]
    assert all(row["known"] is True for row in payload["by_agent"])


def test_unknown_agent_price_skips_without_inventing_zero():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_input_per_million=None, default_output_per_million=None,
        unknown_price="skip", default_budget=3, hard_cap=10, markup=1.0,
    ))
    mission = Mission(goal="skip agent")
    scheduler.consume(
        mission, ModelUsage(input_tokens=1_000_000),
        listed_input=0.4, listed_output=0, agent_id="priced",
    )
    unknown = scheduler.consume(
        mission, ModelUsage(input_tokens=10, output_tokens=2), agent_id="unpriced",
    )
    assert unknown.error is None
    assert unknown.estimate.known is False
    assert unknown.estimate.estimated_cost is None
    assert mission.token_spent == 0.4
    assert mission.agent_token_costs["priced"].known_usd == 0.4
    unpriced = mission.agent_token_costs["unpriced"]
    assert unpriced.known_usd is None
    assert unpriced.input_tokens == 10
    assert unpriced.output_tokens == 2
    assert unpriced.unknown_calls == 1
    assert scheduler.known_agent_usd(mission) == mission.token_spent
    row = next(item for item in scheduler.agent_breakdown(mission) if item["agent_id"] == "unpriced")
    assert row["known"] is False
    assert row["known_usd"] is None
    assert row["partial"] is False
    assert row["tokens"] == 12


def test_unknown_agent_price_fail_closed_does_not_invent_spend():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_input_per_million=None, default_output_per_million=None,
        unknown_price="fail", markup=1.0, default_budget=3, hard_cap=10,
    ))
    mission = Mission(goal="fail agent")
    outcome = scheduler.consume(
        mission, ModelUsage(input_tokens=9, output_tokens=1), agent_id="agent-a",
    )
    assert outcome.error is not None
    assert outcome.error.failure_class == FailureClass.RESOURCE_EXHAUSTED
    assert mission.token_spent == 0
    tally = mission.agent_token_costs["agent-a"]
    assert tally.known_usd is None
    assert tally.input_tokens == 9
    assert tally.output_tokens == 1


def test_missing_agent_id_does_not_invent_an_agent_bucket():
    scheduler = ResourceScheduler(TokenCostSettings(
        default_input_per_million=None, default_output_per_million=None,
        markup=1.0, default_budget=3, hard_cap=10,
    ))
    mission = Mission(goal="no agent")
    scheduler.consume(
        mission, ModelUsage(input_tokens=1_000_000), listed_input=1, listed_output=1,
    )
    assert mission.token_spent == 1.0
    assert mission.agent_token_costs == {}
    assert scheduler.known_agent_usd(mission) == 0.0
    assert scheduler.agent_breakdown(mission) == []


def test_hard_cap_clamps_mission_limit():
    scheduler = ResourceScheduler(TokenCostSettings(default_budget=3, hard_cap=10, markup=1.0))
    mission = Mission(goal="cap", limits={"max_token_cost": 50})
    assert scheduler.budget_for(mission) == 10.0


class PricedFinishProvider(ModelProvider):
    def __init__(self, *, price_input=1.0, price_output=2.0, usage=None, output=None):
        self.provider_id = "priced"
        self.model = "priced-1"
        self.price_input = price_input
        self.price_output = price_output
        self._usage = usage or ModelUsage(input_tokens=1_000_000, output_tokens=0)
        self.output = output or {"action": "finish", "summary": "Priced finish"}
        self._total = ModelUsage()

    def configured(self) -> bool:
        return True

    async def list_models(self):
        return [ModelDescriptor(
            provider=self.provider_id, model=self.model,
            capabilities=ModelCapabilities(reasoning="high", structured_outputs=True),
            context_limits=ContextLimits(max_output_tokens=100),
            price_input_per_million=self.price_input,
            price_output_per_million=self.price_output,
        )]

    def capabilities(self, model: str):
        del model
        return ModelCapabilities(reasoning="high", structured_outputs=True)

    def context_limits(self, model: str):
        del model
        return ContextLimits(max_output_tokens=100)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.provider_id, status="healthy")

    def estimate_cost(self, request: ModelRequest) -> CostEstimate:
        return CostEstimate(provider=self.provider_id, model=request.model, known=True, estimated_cost=0.01)

    def usage(self) -> ModelUsage:
        return self._total.model_copy()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self._total = self._total.plus(self._usage)
        payload = request.input if isinstance(request.input, dict) else {}
        if isinstance(payload, dict) and "claim" in payload:
            output = {
                "verdict": "pass",
                "rationale": "Claim matches the supplied mission artifacts.",
                "evidence": [str((payload.get("claim") or {}).get("summary") or "")],
            }
        else:
            output = self.output
        return ModelResponse(provider=self.provider_id, model=request.model, output=output,
                             response_id="priced-1", usage=self._usage)


class UnpricedFinishProvider(PricedFinishProvider):
    def __init__(self):
        super().__init__(price_input=None, price_output=None,
                         usage=ModelUsage(input_tokens=11, output_tokens=7))

    async def list_models(self):
        return [ModelDescriptor(
            provider=self.provider_id, model=self.model,
            capabilities=ModelCapabilities(reasoning="high", structured_outputs=True),
            context_limits=ContextLimits(max_output_tokens=100),
        )]


def _controller(provider: ModelProvider) -> OpenAIProvider:
    return OpenAIProvider(model_provider=provider, router=ModelRouter([provider]))


@pytest.mark.asyncio
async def test_runtime_under_budget_emits_spend_and_completes(tmp_path):
    provider = PricedFinishProvider()
    scheduler = ResourceScheduler(TokenCostSettings(
        default_budget=3, hard_cap=10, markup=1.0, warning_fraction=0.8,
        default_input_per_million=None, default_output_per_million=None,
    ))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=_controller(provider), resources=scheduler)
    mission = Mission(goal="Stay under the token budget", limits={"max_token_cost": 2})
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.token_spent == 2.0  # decide 1.0 + verify 1.0
    assert saved.spent == 0
    events = store.events(mission.id)
    updates = [e for e in events if e.event_type == "budget.updated"]
    assert len(updates) == 2
    assert updates[-1].payload["known"] is True
    assert updates[-1].payload["token_spent"] == 2.0
    assert updates[-1].payload["source"] == "listed"
    assert scheduler.known_agent_usd(saved) == saved.token_spent
    completed = [e for e in events if e.event_type == "llm.completed"]
    assert completed
    assert all(e.payload.get("agent_id") for e in completed)
    assert all(str(e.actor_id) == e.payload["agent_id"] for e in completed)
    by_agent = updates[-1].payload["by_agent"]
    assert by_agent
    assert sum(row["known_usd"] for row in by_agent) == updates[-1].payload["token_spent"]
    assert any(e.event_type == "budget.warning" for e in events)
    assert any(e.event_type == "llm.completed" for e in events)


@pytest.mark.asyncio
async def test_runtime_over_budget_fails_closed(tmp_path):
    provider = PricedFinishProvider()
    scheduler = ResourceScheduler(TokenCostSettings(
        default_budget=3, hard_cap=10, markup=1.0,
        default_input_per_million=None, default_output_per_million=None,
    ))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=_controller(provider), resources=scheduler)
    mission = Mission(goal="Exceed the token budget", limits={"max_token_cost": 0.5})
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "RESOURCE_EXHAUSTED"
    assert saved.token_spent == 1.0
    assert scheduler.known_agent_usd(saved) == saved.token_spent
    events = store.events(mission.id)
    assert any(e.event_type == "budget.updated" for e in events)
    assert any(e.event_type == "llm.completed" for e in events)
    assert not any(e.event_type == "mission.completed" for e in events)


@pytest.mark.asyncio
async def test_runtime_missing_prices_fail_closed(tmp_path):
    provider = UnpricedFinishProvider()
    scheduler = ResourceScheduler(TokenCostSettings(
        default_budget=3, hard_cap=10, markup=1.0, unknown_price="fail",
        default_input_per_million=None, default_output_per_million=None,
    ))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=_controller(provider), resources=scheduler)
    mission = Mission(goal="Refuse unknown token prices")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "RESOURCE_EXHAUSTED"
    assert saved.token_spent == 0
    updates = [e for e in store.events(mission.id) if e.event_type == "budget.updated"]
    assert updates and updates[0].payload["known"] is False
    assert updates[0].payload["estimated_cost"] is None


@pytest.mark.asyncio
async def test_runtime_missing_prices_skip_estimate_honestly(tmp_path):
    provider = UnpricedFinishProvider()
    scheduler = ResourceScheduler(TokenCostSettings(
        default_budget=3, hard_cap=10, markup=1.0, unknown_price="skip",
        default_input_per_million=None, default_output_per_million=None,
    ))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=_controller(provider), resources=scheduler)
    mission = Mission(goal="Skip unknown token prices")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.token_spent == 0
    updates = [e for e in store.events(mission.id) if e.event_type == "budget.updated"]
    assert updates
    assert all(item.payload["known"] is False for item in updates)
    assert all(item.payload["estimated_cost"] is None for item in updates)
    assert saved.agent_token_costs
    assert all(item.known_usd is None for item in saved.agent_token_costs.values())
    assert scheduler.known_agent_usd(saved) == 0.0
    rows = updates[-1].payload["by_agent"]
    assert rows
    assert all(row["known"] is False and row["known_usd"] is None for row in rows)


@pytest.mark.asyncio
async def test_fallback_controller_skips_accounting_without_usage_metadata(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.token_spent == 0
    assert not any(e.event_type.startswith("budget.") for e in store.events(mission.id))
