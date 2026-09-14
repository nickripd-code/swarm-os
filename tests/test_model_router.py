import pytest

from app.models import FailureClass
from app.providers import (
    ContextLimits,
    CostEstimate,
    ModelCapabilities,
    ModelDescriptor,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderError,
    ProviderHealth,
)
from app.routing import ModelRegistry, ModelRequirements, ModelRouter, NoRouteError


REQUEST = ModelRequest(model="placeholder", instructions="Return JSON", input={"goal": "test"})


class CatalogProvider(ModelProvider):
    def __init__(self, provider_id, models, *, health="healthy", costs=None,
                 health_error=None, discovery_error=None, cost_error=None):
        self.provider_id = provider_id
        self.models = models
        self.health_status = health
        self.costs = costs or {}
        self.health_error = health_error
        self.discovery_error = discovery_error
        self.cost_error = cost_error

    async def list_models(self):
        if self.discovery_error:
            raise self.discovery_error
        return self.models

    async def complete(self, request):
        return ModelResponse(provider=self.provider_id, model=request.model, output={"ok": True})

    def capabilities(self, model):
        return next(item.capabilities for item in self.models if item.model == model)

    async def health(self):
        if self.health_error:
            raise self.health_error
        return ProviderHealth(provider=self.provider_id, status=self.health_status)

    def estimate_cost(self, request):
        if self.cost_error:
            raise self.cost_error
        value = self.costs.get(request.model)
        return CostEstimate(
            provider=self.provider_id,
            model=request.model,
            estimated_cost=value,
            known=value is not None,
        )

    def usage(self):
        return ModelUsage()

    def context_limits(self, model):
        return next(item.context_limits for item in self.models if item.model == model)


def descriptor(provider, model, *, reasoning="high", coding="high", vision=False,
               tools=True, structured=True, context=200_000, local=False,
               latency=1000, reliability=.9, available=True):
    return ModelDescriptor(
        provider=provider,
        model=model,
        local=local,
        privacy="local" if local else "cloud",
        capabilities=ModelCapabilities(
            reasoning=reasoning,
            coding=coding,
            vision=vision,
            tool_use=tools,
            structured_outputs=structured,
        ),
        context_limits=ContextLimits(context_tokens=context, max_output_tokens=8192),
        latency_ms=latency,
        reliability=reliability,
        available=available,
    )


@pytest.mark.asyncio
async def test_routes_by_capabilities_and_returns_ranked_fallback_chain():
    fast = CatalogProvider("fast-cloud", [
        descriptor("fast-cloud", "fast", reasoning="medium", latency=300, reliability=.95),
    ], costs={"fast": .08})
    deep = CatalogProvider("deep-cloud", [
        descriptor("deep-cloud", "deep", reasoning="high", latency=2500, reliability=.99),
    ], costs={"deep": .20})
    router = ModelRouter([fast, deep])

    plan = await router.route(ModelRequirements(
        reasoning="medium",
        coding="medium",
        tool_use=True,
        structured_outputs=True,
        min_context_tokens=100_000,
        max_cost=.30,
        preferred_providers=["deep-cloud"],
    ), REQUEST)

    assert plan.primary.descriptor.model == "deep"
    assert [item.descriptor.model for item in plan.fallbacks] == ["fast"]
    assert "preferred provider rank 1" in plan.primary.reasons
    assert all(item.cost.known for item in plan.candidates)
    trace = plan.trace()
    assert trace["primary"]["provider"] == "deep-cloud"
    assert trace["fallbacks"][0]["provider"] == "fast-cloud"
    assert isinstance(trace["primary"]["provider"], str)


@pytest.mark.asyncio
async def test_hard_requirements_reject_unknown_or_insufficient_metadata():
    unknown = CatalogProvider("unknown", [ModelDescriptor(
        provider="unknown",
        model="mystery",
        capabilities=ModelCapabilities(),
    )])
    router = ModelRouter([unknown])

    with pytest.raises(NoRouteError) as captured:
        await router.route(ModelRequirements(
            reasoning="high",
            vision=True,
            tool_use=True,
            structured_outputs=True,
            min_context_tokens=100_000,
            max_latency_ms=30_000,
        ), REQUEST)

    assert captured.value.failure_class == FailureClass.CAPABILITY_MISMATCH
    reasons = captured.value.rejected[0].reasons
    assert any("reasoning=unknown" in reason for reason in reasons)
    assert any("vision" in reason for reason in reasons)
    assert any("context=unknown" in reason for reason in reasons)
    assert any("latency is unknown" in reason for reason in reasons)


@pytest.mark.asyncio
async def test_local_only_excludes_cloud_and_keeps_local_candidate():
    cloud = CatalogProvider("cloud", [descriptor("cloud", "cloud-model")])
    local = CatalogProvider("self-hosted", [
        descriptor("self-hosted", "local-model", local=True, latency=4000),
    ])

    plan = await ModelRouter([cloud, local]).route(
        ModelRequirements(privacy="local_only", reasoning="medium"), REQUEST,
    )

    assert plan.primary.provider is local
    assert plan.primary.descriptor.local is True
    assert any(item.provider == "cloud" and "model is not local" in item.reasons
               for item in plan.rejected)


@pytest.mark.asyncio
async def test_budget_is_hard_and_unknown_cost_is_rejected():
    expensive = CatalogProvider("expensive", [descriptor("expensive", "large")],
                                costs={"large": .80})
    unknown = CatalogProvider("unknown-cost", [descriptor("unknown-cost", "mystery")])
    cheap = CatalogProvider("cheap", [descriptor("cheap", "small")], costs={"small": .05})

    plan = await ModelRouter([expensive, unknown, cheap]).route(
        ModelRequirements(max_cost=.10), REQUEST,
    )

    assert plan.primary.provider is cheap
    rejected = {item.provider: " ".join(item.reasons) for item in plan.rejected}
    assert "exceeds" in rejected["expensive"]
    assert "cost is unknown" in rejected["unknown-cost"]


@pytest.mark.asyncio
async def test_no_route_classifies_budget_exhaustion():
    provider = CatalogProvider("paid", [descriptor("paid", "model")], costs={"model": .50})
    with pytest.raises(NoRouteError) as captured:
        await ModelRouter([provider]).route(ModelRequirements(max_cost=.10), REQUEST)
    assert captured.value.failure_class == FailureClass.RESOURCE_EXHAUSTED


@pytest.mark.asyncio
async def test_no_route_classifies_unconfigured_and_outage():
    unconfigured = CatalogProvider("missing-key", [], health="unconfigured")
    with pytest.raises(NoRouteError) as auth:
        await ModelRouter([unconfigured]).route(ModelRequirements(), REQUEST)
    assert auth.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED

    unavailable = CatalogProvider("offline", [], health="unavailable")
    with pytest.raises(NoRouteError) as outage:
        await ModelRouter([unavailable]).route(ModelRequirements(), REQUEST)
    assert outage.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_provider_allowlist_and_model_availability_are_enforced():
    denied = CatalogProvider("denied", [descriptor("denied", "good")])
    allowed = CatalogProvider("allowed", [
        descriptor("allowed", "offline", available=False),
        descriptor("allowed", "online"),
    ])
    plan = await ModelRouter([denied, allowed]).route(
        ModelRequirements(allowed_providers={"allowed"}), REQUEST,
    )

    assert plan.primary.descriptor.model == "online"
    reasons = {(item.provider, item.model): item.reasons for item in plan.rejected}
    assert "provider is outside allowed_providers" in reasons[("denied", "good")]
    assert "model is marked unavailable" in reasons[("allowed", "offline")]


@pytest.mark.asyncio
async def test_provider_failures_are_preserved_as_explicit_rejections():
    health_failure = CatalogProvider(
        "health-failed", [],
        health_error=ProviderError("offline", FailureClass.PROVIDER_OUTAGE),
    )
    discovery_failure = CatalogProvider(
        "discovery-failed", [],
        discovery_error=ProviderError("bad catalog", FailureClass.MODEL_FAILURE),
    )
    cost_failure = CatalogProvider(
        "cost-failed", [descriptor("cost-failed", "priced")],
        cost_error=ProviderError("pricing offline", FailureClass.PROVIDER_OUTAGE),
    )
    viable = CatalogProvider("viable", [descriptor("viable", "ok")])

    plan = await ModelRouter([health_failure, discovery_failure, cost_failure, viable]).route(
        ModelRequirements(), REQUEST,
    )

    assert plan.primary.provider is viable
    reasons = {item.provider: item.reasons[0] for item in plan.rejected}
    assert reasons["health-failed"] == "health check failed: PROVIDER_OUTAGE"
    assert reasons["discovery-failed"] == "model discovery failed: MODEL_FAILURE"
    assert reasons["cost-failed"] == "cost estimation failed: PROVIDER_OUTAGE"


def test_registry_preserves_registration_order_and_ignores_same_instance():
    provider = CatalogProvider("one", [descriptor("one", "model")])
    registry = ModelRegistry([provider, provider])
    assert registry.providers == (provider,)
