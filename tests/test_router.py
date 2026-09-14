import pytest

from app.llm import OpenAIProvider, build_controller, build_model_provider, build_router
from app.models import FailureClass, Mission
from app.providers import (
    ContextLimits, CostEstimate, FailoverModelProvider, ModelCapabilities, ModelDescriptor,
    ModelProvider, ModelRequest, ModelResponse, ModelUsage, ProviderError, ProviderHealth,
)
from app.router import (
    CapabilityRequest, ModelRouter, capability_request_for, score_model,
)
from app.runtime import SwarmRuntime
from app.store import Store


REQUEST = ModelRequest(model="unused-default", instructions="Return JSON", input={"goal": "test"})


class FakeModelProvider(ModelProvider):
    def __init__(self, provider_id: str, model: str, *, configured: bool = True,
                 health: str = "healthy", error: ProviderError | None = None,
                 output: dict | None = None, capabilities: ModelCapabilities | None = None,
                 context_tokens: int | None = None, local: bool = False,
                 price_output_per_million: float | None = None,
                 estimated_cost: float | None = None, cost_known: bool = False):
        self.provider_id = provider_id
        self.model = model
        self._configured = configured
        self._health = health
        self.error = error
        self.output = output or {"action": "finish", "summary": f"from {provider_id}"}
        self._capabilities = capabilities or ModelCapabilities(structured_outputs=True, tool_use=True)
        self._context_tokens = context_tokens
        self.local = local
        self.price_output_per_million = price_output_per_million
        self._estimated_cost = estimated_cost
        self._cost_known = cost_known
        self.calls = 0
        self.requested_models: list[str] = []
        self._usage = ModelUsage()

    def configured(self) -> bool:
        return self._configured

    async def list_models(self):
        return [ModelDescriptor(
            provider=self.provider_id,
            model=self.model,
            local=self.local,
            capabilities=self._capabilities,
            context_limits=ContextLimits(context_tokens=self._context_tokens, max_output_tokens=100),
            price_output_per_million=self.price_output_per_million,
        )]

    def capabilities(self, model: str) -> ModelCapabilities:
        del model
        return self._capabilities

    def context_limits(self, model: str) -> ContextLimits:
        del model
        return ContextLimits(context_tokens=self._context_tokens, max_output_tokens=100)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.provider_id, status=self._health)

    def estimate_cost(self, request: ModelRequest) -> CostEstimate:
        return CostEstimate(
            provider=self.provider_id, model=request.model,
            estimated_cost=self._estimated_cost, known=self._cost_known,
        )

    def usage(self) -> ModelUsage:
        return self._usage.model_copy()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        self.requested_models.append(request.model)
        if self.error:
            raise self.error
        usage = ModelUsage(input_tokens=1, output_tokens=2)
        self._usage = self._usage.plus(usage)
        return ModelResponse(provider=self.provider_id, model=request.model, output=self.output,
                             response_id=f"{self.provider_id}-1", usage=usage)


def openai_like(**kwargs) -> FakeModelProvider:
    caps = kwargs.pop("capabilities", ModelCapabilities(
        reasoning="high", coding="high", tool_use=True, structured_outputs=True, vision=False,
    ))
    return FakeModelProvider("openai", "gpt-6-astra", capabilities=caps, **kwargs)


def openrouter_like(**kwargs) -> FakeModelProvider:
    caps = kwargs.pop("capabilities", ModelCapabilities(
        reasoning="unknown", coding="unknown", tool_use=True, structured_outputs=True, vision=False,
    ))
    return FakeModelProvider("openrouter", "openai/gpt-4o", capabilities=caps, **kwargs)


def test_controller_requests_high_reasoning_not_a_model_name():
    request = capability_request_for(kind="decision")
    assert request.reasoning == "high"
    assert request.coding == "low"
    assert request.tool_use == "none"


def test_worker_capabilities_map_to_coding_and_reasoning():
    writer = capability_request_for(kind="work", agent={"capabilities": ["write"]})
    assert writer.coding == "high"
    assert writer.reasoning == "medium"
    reviewer = capability_request_for(kind="work", agent={"capabilities": ["review"]})
    assert reviewer.reasoning == "high"
    assert reviewer.coding == "medium"
    analyst = capability_request_for(kind="work", agent={"capabilities": ["reason"]})
    assert analyst.reasoning == "high"
    assert analyst.coding == "none"


def test_score_prefers_known_high_reasoning_over_unknown():
    request = CapabilityRequest(reasoning="high")
    openai = ModelDescriptor(
        provider="openai", model="gpt-6-astra",
        capabilities=ModelCapabilities(reasoning="high", coding="high", structured_outputs=True),
    )
    gateway = ModelDescriptor(
        provider="openrouter", model="openai/gpt-4o",
        capabilities=ModelCapabilities(reasoning="unknown", coding="unknown", structured_outputs=True),
    )
    openai_score, _ = score_model(openai, request, index=0)
    gateway_score, _ = score_model(gateway, request, index=1)
    assert openai_score > gateway_score


def test_score_rejects_known_low_reasoning_when_high_requested():
    request = CapabilityRequest(reasoning="high")
    weak = ModelDescriptor(
        provider="local", model="tiny",
        capabilities=ModelCapabilities(reasoning="low", structured_outputs=True),
    )
    assert score_model(weak, request) is None


def test_score_rejects_cloud_model_when_local_only():
    request = CapabilityRequest(privacy="local_only")
    cloud = ModelDescriptor(
        provider="openai", model="gpt-6-astra", local=False,
        capabilities=ModelCapabilities(reasoning="high", structured_outputs=True),
    )
    assert score_model(cloud, request) is None


def test_score_rejects_unknown_cost_when_budget_is_set():
    request = CapabilityRequest(max_cost=0.1)
    descriptor = ModelDescriptor(
        provider="openai", model="gpt-6-astra",
        capabilities=ModelCapabilities(reasoning="high", structured_outputs=True),
    )
    estimate = CostEstimate(provider="openai", model="gpt-6-astra", known=False)
    assert score_model(descriptor, request, estimate=estimate) is None


@pytest.mark.asyncio
async def test_router_selects_openai_for_high_reasoning_and_keeps_openrouter_fallback():
    router = ModelRouter([openai_like(), openrouter_like()])
    decision = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert decision.selected.provider_id == "openai"
    assert decision.selected.model == "gpt-6-astra"
    assert [(c.provider_id, c.model) for c in decision.fallbacks] == [("openrouter", "openai/gpt-4o")]


@pytest.mark.asyncio
async def test_router_prefers_cheaper_model_when_cost_is_known():
    expensive = openai_like(price_output_per_million=20)
    cheap = openrouter_like(
        capabilities=ModelCapabilities(reasoning="high", coding="high", structured_outputs=True),
        price_output_per_million=1,
    )
    router = ModelRouter([expensive, cheap])
    decision = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert decision.selected.provider_id == "openrouter"
    assert decision.fallbacks[0].provider_id == "openai"


@pytest.mark.asyncio
async def test_router_excludes_models_over_max_cost():
    expensive = openai_like(estimated_cost=0.5, cost_known=True)
    cheap = openrouter_like(
        capabilities=ModelCapabilities(reasoning="high", coding="high", structured_outputs=True),
        estimated_cost=0.01, cost_known=True,
    )
    router = ModelRouter([expensive, cheap])
    decision = await router.select(CapabilityRequest(reasoning="high", max_cost=0.4))
    assert decision.selected.provider_id == "openrouter"
    assert decision.fallbacks == []


@pytest.mark.asyncio
async def test_router_complete_uses_selected_model_not_request_model():
    openai = openai_like(output={"answer": "primary"})
    router = ModelRouter([openai, openrouter_like()])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openai.requested_models == ["gpt-6-astra"]
    assert response.provider == "openai"
    assert response.failover_from is None
    assert router.last_decision is not None
    assert router.last_decision.selected.model == "gpt-6-astra"


@pytest.mark.asyncio
async def test_outage_walks_fallback_chain_like_failover_provider():
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(output={"answer": "from openrouter"})
    router = ModelRouter([openai, openrouter])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert openrouter.requested_models == ["openai/gpt-4o"]
    assert response.provider == "openrouter"
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_unavailable_primary_uses_next_candidate_without_calling_it():
    openai = openai_like(health="unavailable")
    openrouter = openrouter_like()
    router = ModelRouter([openai, openrouter])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 0
    assert openrouter.calls == 1
    assert response.failover_from == "openai"
    assert response.failover_reason == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_class,message", [
    (FailureClass.AUTHORIZATION_REQUIRED, "OpenAI rejected the API key"),
    (FailureClass.POLICY_REFUSAL, "The model declined the request"),
    (FailureClass.INVALID_OUTPUT, "invalid structured"),
    (FailureClass.RATE_LIMIT, "quota or rate limit"),
    (FailureClass.TIMEOUT, "timed out"),
])
async def test_non_outage_errors_do_not_use_fallback_chain(failure_class, message):
    openai = openai_like(error=ProviderError(message, failure_class))
    openrouter = openrouter_like()
    router = ModelRouter([openai, openrouter])
    with pytest.raises(ProviderError) as error:
        await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert error.value.failure_class == failure_class
    assert openai.calls == 1
    assert openrouter.calls == 0


@pytest.mark.asyncio
async def test_both_providers_down_fail_closed():
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    router = ModelRouter([openai, openrouter])
    with pytest.raises(ProviderError, match="Could not reach OpenRouter") as error:
        await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert error.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert openai.calls == 1
    assert openrouter.calls == 1


@pytest.mark.asyncio
async def test_unconfigured_router_fails_closed():
    router = ModelRouter([openai_like(configured=False, health="unconfigured")])
    with pytest.raises(ProviderError, match="No model provider is configured") as error:
        await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_local_only_with_cloud_catalog_is_capability_mismatch():
    router = ModelRouter([openai_like(), openrouter_like()])
    with pytest.raises(ProviderError, match="No registered model satisfies") as error:
        await router.select(CapabilityRequest(privacy="local_only"))
    assert error.value.failure_class == FailureClass.CAPABILITY_MISMATCH


@pytest.mark.asyncio
async def test_openai_only_outage_fails_closed_without_inventing_a_secondary():
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    router = ModelRouter([openai])
    with pytest.raises(ProviderError, match="Could not reach OpenAI") as error:
        await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert error.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert openai.calls == 1


@pytest.mark.asyncio
async def test_openai_only_router_has_a_single_candidate():
    router = ModelRouter([openai_like()])
    decision = await router.select(CapabilityRequest(reasoning="high"))
    assert decision.selected.provider_id == "openai"
    assert decision.fallbacks == []
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert response.failover_from is None


def test_build_router_openai_only_does_not_register_openrouter(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    router = build_router()
    assert [provider.provider_id for provider in router.providers] == ["openai"]
    stacked = build_model_provider()
    assert not isinstance(stacked, FailoverModelProvider)


def test_build_router_both_keys_unwraps_failover(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    router = build_router()
    assert [provider.provider_id for provider in router.providers] == ["openai", "openrouter"]
    controller = build_controller()
    assert isinstance(controller.router, ModelRouter)
    assert controller.router.providers[0].provider_id == "openai"


@pytest.mark.asyncio
async def test_controller_with_router_records_route_metadata():
    openai = openai_like(output={"action": "finish", "summary": "ok"})
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter_like()]))
    result = await controller.decide({"goal": "route me"})
    assert result["_meta"]["provider"] == "openai"
    assert result["_meta"]["model"] == "gpt-6-astra"
    assert result["_meta"]["route"]["provider"] == "openai"
    assert result["_meta"]["route"]["fallbacks"] == [{"provider": "openrouter", "model": "openai/gpt-4o"}]
    assert openai.requested_models == ["gpt-6-astra"]


@pytest.mark.asyncio
async def test_runtime_router_outage_then_openrouter_success(tmp_path):
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(output={"action": "finish", "summary": "Delivered via OpenRouter"})
    controller = OpenAIProvider(
        model_provider=openai,
        router=ModelRouter([openai, openrouter]),
    )
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Recover from an OpenAI outage via the router")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.result["summary"] == "Delivered via OpenRouter"
    events = store.events(mission.id)
    failovers = [e for e in events if e.event_type == "llm.failover"]
    assert failovers
    assert failovers[0].payload["from_provider"] == "openai"
    assert failovers[0].payload["to_provider"] == "openrouter"
    assert failovers[0].payload["reason"] == "PROVIDER_OUTAGE"
    assert not any(e.event_type in {"controller.fallback", "mission.failed"} for e in events)
    completed = [e for e in events if e.event_type == "llm.completed"]
    assert completed and completed[0].payload["provider"] == "openrouter"
    assert completed[0].payload["route"]["fallbacks"][0]["provider"] == "openrouter"


@pytest.mark.asyncio
async def test_runtime_router_both_down_never_uses_demo_fallback(tmp_path):
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    controller = OpenAIProvider(model_provider=openai, router=ModelRouter([openai, openrouter]))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Fail closed when every routed provider is down")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result == {"error": "Could not reach OpenRouter", "failure_class": "PROVIDER_OUTAGE"}
    events = store.events(mission.id)
    assert not any(e.event_type in {"controller.fallback", "mission.completed"} for e in events)
    assert any(e.event_type == "mission.failed" and e.payload.get("failure_class") == "PROVIDER_OUTAGE"
               for e in events)
