from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.llm import OpenAIProvider, build_controller, build_model_provider, build_router
from app.models import FailureClass, Mission
from app.providers import (
    ContextLimits, CostEstimate, FailoverModelProvider, ModelCapabilities, ModelDescriptor,
    ModelProvider, ModelRequest, ModelResponse, ModelUsage, ProviderError, ProviderHealth,
)
from app.router import (
    CapabilityRequest, ModelRouter, NoRouteError, ProviderHistory,
    capability_request_for, parse_stored_provider_outcome, score_model,
)
from app.runtime import SwarmRuntime
from app.store import ROUTER_OUTCOME_PER_PROVIDER, Store


REQUEST = ModelRequest(model="unused-default", instructions="Return JSON", input={"goal": "test"})


class FakeModelProvider(ModelProvider):
    def __init__(self, provider_id: str, model: str, *, configured: bool = True,
                 health: str = "healthy", error: ProviderError | None = None,
                 output: dict | None = None, verify_output: dict | None = None,
                 capabilities: ModelCapabilities | None = None,
                 context_tokens: int | None = None, local: bool = False,
                 price_output_per_million: float | None = None,
                 estimated_cost: float | None = None, cost_known: bool = False,
                 list_error: ProviderError | None = None):
        self.provider_id = provider_id
        self.model = model
        self._configured = configured
        self._health = health
        self.error = error
        self.output = output or {"action": "finish", "summary": f"from {provider_id}"}
        self.verify_output = verify_output
        self._capabilities = capabilities or ModelCapabilities(structured_outputs=True, tool_use=True)
        self._context_tokens = context_tokens
        self.local = local
        self.price_output_per_million = price_output_per_million
        self._estimated_cost = estimated_cost
        self._cost_known = cost_known
        self.list_error = list_error
        self.calls = 0
        self.requested_models: list[str] = []
        self.estimated_requests: list[ModelRequest] = []
        self._usage = ModelUsage()

    def configured(self) -> bool:
        return self._configured

    async def list_models(self):
        if self.list_error:
            raise self.list_error
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
        self.estimated_requests.append(request)
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
        payload = request.input if isinstance(request.input, dict) else {}
        if isinstance(payload, dict) and "claim" in payload:
            output = self.verify_output or {
                "verdict": "pass",
                "rationale": "Claim matches the supplied mission artifacts.",
                "evidence": [str((payload.get("claim") or {}).get("summary") or "")],
            }
        else:
            output = self.output
        return ModelResponse(provider=self.provider_id, model=request.model, output=output,
                             response_id=f"{self.provider_id}-1", usage=usage)


def openai_like(**kwargs) -> FakeModelProvider:
    caps = kwargs.pop("capabilities", ModelCapabilities(
        reasoning="high", coding="high", tool_use=True, structured_outputs=True, vision=False,
    ))
    return FakeModelProvider("openai", "gpt-6-astra", capabilities=caps, **kwargs)


EQUAL_CAPS = ModelCapabilities(
    reasoning="high", coding="high", tool_use=True, structured_outputs=True, vision=False,
)


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
    verification = capability_request_for(kind="verification")
    assert verification.reasoning == "high"
    assert verification.coding == "medium"
    assert verification.tool_use == "none"


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
    assert any("lowest known cost among eligible" in reason for reason in decision.selected.reasons)
    assert any("listed output price 1/M" in reason for reason in decision.selected.reasons)
    assert any("relative cost" in reason for reason in decision.fallbacks[0].reasons)


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
async def test_complete_estimates_cost_from_the_real_request():
    openai = openai_like(estimated_cost=0.05, cost_known=True)
    router = ModelRouter([openai])
    request = ModelRequest(
        model="caller-default",
        instructions="Use the complete mission context",
        input={"goal": "a real request with payload"},
        max_output_tokens=321,
    )
    await router.complete(CapabilityRequest(reasoning="high", max_cost=0.10), request)
    assert len(openai.estimated_requests) == 1
    estimate_request = openai.estimated_requests[0]
    assert estimate_request.model == "gpt-6-astra"
    assert estimate_request.instructions == request.instructions
    assert estimate_request.input == request.input
    assert estimate_request.max_output_tokens == 321


@pytest.mark.asyncio
async def test_catalog_failure_is_rejected_while_healthy_provider_is_routed():
    broken = openai_like(list_error=ProviderError(
        "sensitive upstream detail", FailureClass.PROVIDER_OUTAGE,
    ))
    healthy = openrouter_like(capabilities=EQUAL_CAPS)
    router = ModelRouter([broken, healthy])
    decision = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert decision.selected.provider_id == "openrouter"
    assert decision.rejected[0].provider_id == "openai"
    assert decision.rejected[0].model is None
    assert decision.rejected[0].reasons == ["catalog failed: PROVIDER_OUTAGE"]
    assert "sensitive upstream detail" not in decision.model_dump_json()


@pytest.mark.asyncio
async def test_all_catalog_failures_are_provider_outage_with_structured_diagnostics():
    openai = openai_like(list_error=ProviderError("first secret", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(list_error=ProviderError(
        "second secret", FailureClass.PROVIDER_OUTAGE,
    ))
    router = ModelRouter([openai, openrouter])
    with pytest.raises(NoRouteError) as caught:
        await router.select(CapabilityRequest(reasoning="high"))
    assert caught.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert [item.provider_id for item in caught.value.rejections] == ["openai", "openrouter"]
    assert "first secret" not in str(caught.value)
    assert "second secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_capability_mismatch_has_explicit_rejection_reasons():
    router = ModelRouter([openai_like()])
    with pytest.raises(NoRouteError) as caught:
        await router.select(CapabilityRequest(
            privacy="local_only",
            min_context_tokens=1_000_000,
        ))
    assert caught.value.failure_class == FailureClass.CAPABILITY_MISMATCH
    [rejection] = caught.value.rejections
    assert rejection.provider_id == "openai"
    assert rejection.model == "gpt-6-astra"
    assert rejection.reasons == [
        "privacy requires a local model",
        "context window is unknown or below the request",
    ]


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
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLAMACPP_MODEL", raising=False)
    monkeypatch.delenv("LLAMACPP_BASE_URL", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_MODEL", raising=False)
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)
    monkeypatch.delenv("MISTRAL_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_MODEL", raising=False)
    monkeypatch.delenv("COHERE_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.delenv("TOGETHER_MODEL", raising=False)
    monkeypatch.delenv("TOGETHER_BASE_URL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.delenv("FIREWORKS_MODEL", raising=False)
    monkeypatch.delenv("FIREWORKS_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_MODEL", raising=False)
    monkeypatch.delenv("PERPLEXITY_BASE_URL", raising=False)
    monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL", raising=False)
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_BASE_URL", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HUGGINGFACE_MODEL", raising=False)
    monkeypatch.delenv("HUGGINGFACE_BASE_URL", raising=False)
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("CEREBRAS_MODEL", raising=False)
    monkeypatch.delenv("CEREBRAS_BASE_URL", raising=False)
    monkeypatch.delenv("SAMBANOVA_API_KEY", raising=False)
    monkeypatch.delenv("SAMBANOVA_MODEL", raising=False)
    monkeypatch.delenv("SAMBANOVA_BASE_URL", raising=False)
    monkeypatch.delenv("VERTEX_API_KEY", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("VERTEX_LOCATION", raising=False)
    monkeypatch.delenv("VERTEX_MODEL", raising=False)
    monkeypatch.delenv("VERTEX_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    router = build_router()
    assert [provider.provider_id for provider in router.providers] == ["openai"]
    stacked = build_model_provider()
    assert not isinstance(stacked, FailoverModelProvider)


def test_build_router_both_keys_unwraps_failover(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLAMACPP_MODEL", raising=False)
    monkeypatch.delenv("LLAMACPP_BASE_URL", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_MODEL", raising=False)
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)
    monkeypatch.delenv("MISTRAL_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_MODEL", raising=False)
    monkeypatch.delenv("COHERE_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.delenv("TOGETHER_MODEL", raising=False)
    monkeypatch.delenv("TOGETHER_BASE_URL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.delenv("FIREWORKS_MODEL", raising=False)
    monkeypatch.delenv("FIREWORKS_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_MODEL", raising=False)
    monkeypatch.delenv("PERPLEXITY_BASE_URL", raising=False)
    monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL", raising=False)
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_BASE_URL", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HUGGINGFACE_MODEL", raising=False)
    monkeypatch.delenv("HUGGINGFACE_BASE_URL", raising=False)
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("CEREBRAS_MODEL", raising=False)
    monkeypatch.delenv("CEREBRAS_BASE_URL", raising=False)
    monkeypatch.delenv("SAMBANOVA_API_KEY", raising=False)
    monkeypatch.delenv("SAMBANOVA_MODEL", raising=False)
    monkeypatch.delenv("SAMBANOVA_BASE_URL", raising=False)
    monkeypatch.delenv("VERTEX_API_KEY", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("VERTEX_LOCATION", raising=False)
    monkeypatch.delenv("VERTEX_MODEL", raising=False)
    monkeypatch.delenv("VERTEX_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
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
    assert "selected openai/gpt-6-astra" in result["_meta"]["route"]["rationale"]
    assert "no recent outcomes" in result["_meta"]["route"]["rationale"]
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


def test_empty_history_is_unknown_not_success():
    history = ProviderHistory()
    request = CapabilityRequest(reasoning="high")
    descriptor = ModelDescriptor(
        provider="openai", model="gpt-6-astra",
        capabilities=ModelCapabilities(reasoning="high", structured_outputs=True),
    )
    score, reasons = score_model(descriptor, request, history=history)
    bare, _ = score_model(descriptor, request)
    assert score == bare
    assert history.score_delta() == 0.0
    assert "no recent outcomes" in reasons
    assert not any(reason.startswith("recent success") for reason in reasons)


def test_recent_failures_rank_below_recent_successes():
    request = CapabilityRequest(reasoning="high")
    descriptor = ModelDescriptor(
        provider="openai", model="gpt-6-astra",
        capabilities=ModelCapabilities(reasoning="high", structured_outputs=True),
    )
    failing = ProviderHistory()
    succeeding = ProviderHistory()
    for _ in range(3):
        failing.record(False)
        succeeding.record(True)
    fail_score, fail_reasons = score_model(descriptor, request, history=failing)
    win_score, win_reasons = score_model(descriptor, request, history=succeeding)
    assert win_score > fail_score
    assert "recent success 0/3" in fail_reasons
    assert "recent success 3/3" in win_reasons


def test_history_does_not_override_hard_capability_reject():
    request = CapabilityRequest(reasoning="high")
    weak = ModelDescriptor(
        provider="local", model="tiny",
        capabilities=ModelCapabilities(reasoning="low", structured_outputs=True),
    )
    history = ProviderHistory()
    for _ in range(8):
        history.record(True)
    assert score_model(weak, request, history=history) is None


def test_history_window_keeps_only_recent_outcomes():
    history = ProviderHistory(window=8)
    for _ in range(8):
        history.record(False)
    history.record(True)
    assert history.samples == 8
    assert history.successes == 1
    assert history.failures == 7


@pytest.mark.asyncio
async def test_router_reranks_after_recorded_provider_failure():
    openai = openai_like(error=ProviderError("invalid structured", FailureClass.INVALID_OUTPUT))
    openrouter = openrouter_like(capabilities=EQUAL_CAPS)
    router = ModelRouter([openai, openrouter])
    first = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert first.selected.provider_id == "openai"
    assert "no recent outcomes" in first.selected.reasons
    with pytest.raises(ProviderError) as error:
        await router.complete(CapabilityRequest(reasoning="high", coding="high"), REQUEST)
    assert error.value.failure_class == FailureClass.INVALID_OUTPUT
    assert openrouter.calls == 0
    second = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert second.selected.provider_id == "openrouter"
    assert "no recent outcomes" in second.selected.reasons
    openai_candidate = next(item for item in second.chain if item.provider_id == "openai")
    assert "recent success 0/1" in openai_candidate.reasons
    assert "selected openrouter/openai/gpt-4o" in second.rationale


@pytest.mark.asyncio
async def test_history_does_not_drop_the_only_provider():
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    router = ModelRouter([openai])
    with pytest.raises(ProviderError):
        await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    decision = await router.select(CapabilityRequest(reasoning="high"))
    assert decision.selected.provider_id == "openai"
    assert "recent success 0/1" in decision.selected.reasons
    assert decision.fallbacks == []


@pytest.mark.asyncio
async def test_same_complete_walk_does_not_skip_chain_because_of_history():
    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(output={"answer": "from openrouter"}, capabilities=EQUAL_CAPS)
    router = ModelRouter([openai, openrouter])
    response = await router.complete(CapabilityRequest(reasoning="high", coding="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "openrouter"
    assert router.history_for("openai").failures == 1
    assert router.history_for("openrouter").successes == 1


@pytest.mark.asyncio
async def test_recent_success_beats_cheaper_failing_model():
    expensive = openai_like(price_output_per_million=20)
    cheap = openrouter_like(capabilities=EQUAL_CAPS, price_output_per_million=1)
    router = ModelRouter([expensive, cheap])
    before = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert before.selected.provider_id == "openrouter"
    for _ in range(3):
        router.record_outcome("openai", True)
        router.record_outcome("openrouter", False)
    after = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert after.selected.provider_id == "openai"
    assert "recent success 3/3" in after.selected.reasons
    assert any("recent success 0/3" in reason for reason in after.fallbacks[0].reasons)


@pytest.mark.asyncio
async def test_unknown_cost_is_not_treated_as_cheapest():
    priced = openai_like(price_output_per_million=20)
    unknown = openrouter_like(capabilities=EQUAL_CAPS)
    router = ModelRouter([priced, unknown])
    decision = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    combined = [reason for item in decision.chain for reason in item.reasons]
    assert "lowest known cost among eligible" not in combined
    assert not any(reason.startswith("relative cost") for reason in combined)


@pytest.mark.asyncio
async def test_complete_on_records_failure_without_failover():
    openai = openai_like(error=ProviderError("invalid structured", FailureClass.INVALID_OUTPUT))
    openrouter = openrouter_like(capabilities=EQUAL_CAPS)
    router = ModelRouter([openai, openrouter])
    candidate = (await router.select(CapabilityRequest(reasoning="high", coding="high"))).selected
    assert candidate.provider_id == "openai"
    with pytest.raises(ProviderError) as error:
        await router.complete_on(candidate, REQUEST)
    assert error.value.failure_class == FailureClass.INVALID_OUTPUT
    assert openrouter.calls == 0
    decision = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert decision.selected.provider_id == "openrouter"
    assert router.history_for("openai").failures == 1


def test_parse_stored_provider_outcome_skips_corrupt_rows():
    now = datetime.now(timezone.utc)
    valid = {
        "provider_id": "openai", "outcome": "success", "failure_class": None,
        "ts": now, "mission_id": None,
    }
    assert parse_stored_provider_outcome(valid) == ("openai", True)
    assert parse_stored_provider_outcome({**valid, "outcome": "yes"}) is None
    assert parse_stored_provider_outcome({**valid, "failure_class": "PROVIDER_OUTAGE"}) is None
    assert parse_stored_provider_outcome({**valid, "provider_id": ""}) is None
    assert parse_stored_provider_outcome({**valid, "ts": "now"}) is None
    assert parse_stored_provider_outcome({**valid, "mission_id": "not-a-uuid"}) is None


@pytest.mark.asyncio
async def test_empty_durable_history_is_unknown(tmp_path):
    store = Store(str(tmp_path / "empty.db"))
    router = ModelRouter(
        [openai_like(), openrouter_like(capabilities=EQUAL_CAPS)], outcome_store=store,
    )
    assert router.history_for("openai").samples == 0
    assert router.history_for("openai").score_delta() == 0.0
    decision = await router.select(CapabilityRequest(reasoning="high", coding="high"))
    assert decision.selected.provider_id == "openai"
    assert "no recent outcomes" in decision.selected.reasons
    assert store.recent_provider_outcomes() == []


@pytest.mark.asyncio
async def test_durable_failures_shift_ranking_across_a_fresh_store(tmp_path):
    path = tmp_path / "router.db"
    store = Store(str(path))
    mission_id = str(Mission(goal="route").id)
    writer = ModelRouter(
        [openai_like(), openrouter_like(capabilities=EQUAL_CAPS)], outcome_store=store,
    )
    writer.note_mission(mission_id)
    first = await writer.select(CapabilityRequest(reasoning="high", coding="high"))
    assert first.selected.provider_id == "openai"
    assert "no recent outcomes" in first.selected.reasons
    for _ in range(3):
        writer.record_outcome("openai", False, failure_class=FailureClass.PROVIDER_OUTAGE)
    fresh = Store(str(path))
    reader = ModelRouter(
        [openai_like(), openrouter_like(capabilities=EQUAL_CAPS)], outcome_store=fresh,
    )
    assert reader.history_for("openai").failures == 3
    assert reader.history_for("openai").successes == 0
    assert reader.history_for("openrouter").samples == 0
    second = await reader.select(CapabilityRequest(reasoning="high", coding="high"))
    assert second.selected.provider_id == "openrouter"
    openai_candidate = next(item for item in second.chain if item.provider_id == "openai")
    assert "recent success 0/3" in openai_candidate.reasons
    rows = fresh.recent_provider_outcomes()
    assert len(rows) == 3
    assert {row["outcome"] for row in rows} == {"failure"}
    assert {row["failure_class"] for row in rows} == {"PROVIDER_OUTAGE"}
    assert {row["mission_id"] for row in rows} == {mission_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_class", [
    FailureClass.AUTHORIZATION_REQUIRED,
    FailureClass.POLICY_REFUSAL,
    FailureClass.INVALID_OUTPUT,
    FailureClass.RATE_LIMIT,
    FailureClass.TIMEOUT,
])
async def test_durable_memory_does_not_invent_a_secondary(tmp_path, failure_class):
    store = Store(str(tmp_path / "nofailover.db"))
    openai = openai_like(error=ProviderError("denied", failure_class))
    openrouter = openrouter_like(capabilities=EQUAL_CAPS)
    router = ModelRouter([openai, openrouter], outcome_store=store)
    with pytest.raises(ProviderError) as error:
        await router.complete(CapabilityRequest(reasoning="high", coding="high"), REQUEST)
    assert error.value.failure_class == failure_class
    assert openai.calls == 1
    assert openrouter.calls == 0
    rows = store.recent_provider_outcomes()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "failure"
    assert rows[0]["failure_class"] == failure_class.value


@pytest.mark.asyncio
async def test_durable_memory_keeps_provider_outage_failover(tmp_path):
    store = Store(str(tmp_path / "outage.db"))
    openai = openai_like(error=ProviderError("down", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(output={"answer": "ok"}, capabilities=EQUAL_CAPS)
    router = ModelRouter([openai, openrouter], outcome_store=store)
    response = await router.complete(CapabilityRequest(reasoning="high", coding="high"), REQUEST)
    assert response.provider == "openrouter"
    assert response.failover_from == "openai"
    assert openrouter.calls == 1
    rows = store.recent_provider_outcomes()
    assert [row["outcome"] for row in rows] == ["failure", "success"]
    assert rows[0]["failure_class"] == "PROVIDER_OUTAGE"
    assert rows[1]["failure_class"] is None


def test_corrupt_and_expired_rows_do_not_invent_success(tmp_path):
    path = tmp_path / "corrupt.db"
    store = Store(str(path))
    store.append_provider_outcome("openai", success=False, failure_class="PROVIDER_OUTAGE")
    now = datetime.now(timezone.utc)
    expired = now - timedelta(days=2)
    with store.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO provider_outcomes (provider_id, outcome, failure_class, ts, mission_id) "
            "VALUES (:provider_id, :outcome, :failure_class, :ts, :mission_id)"
        ), [
            {"provider_id": "openai", "outcome": "yes", "failure_class": None,
             "ts": now, "mission_id": None},
            {"provider_id": "openai", "outcome": "success", "failure_class": "PROVIDER_OUTAGE",
             "ts": now, "mission_id": None},
            {"provider_id": "openai", "outcome": "success", "failure_class": None,
             "ts": now, "mission_id": "not-a-uuid"},
            {"provider_id": "openai", "outcome": "success", "failure_class": None,
             "ts": expired, "mission_id": None},
        ])
    fresh = Store(str(path))
    router = ModelRouter([openai_like()], outcome_store=fresh)
    history = router.history_for("openai")
    assert history.failures == 1
    assert history.successes == 0
    assert history.score_delta() < 0
    assert all(row["outcome"] == "failure" for row in fresh.recent_provider_outcomes())


def test_provider_outcome_retention_keeps_latest_per_provider(tmp_path):
    path = tmp_path / "retain.db"
    store = Store(str(path))
    for _ in range(ROUTER_OUTCOME_PER_PROVIDER):
        store.append_provider_outcome("openai", success=False, failure_class="TIMEOUT")
    store.append_provider_outcome("openai", success=True)
    rows = store.recent_provider_outcomes()
    assert len(rows) == ROUTER_OUTCOME_PER_PROVIDER
    assert sum(row["outcome"] == "success" for row in rows) == 1
    assert sum(row["outcome"] == "failure" for row in rows) == ROUTER_OUTCOME_PER_PROVIDER - 1
    router = ModelRouter([openai_like()], outcome_store=Store(str(path)))
    assert router.history_for("openai").successes == 1
    assert router.history_for("openai").failures == ROUTER_OUTCOME_PER_PROVIDER - 1


def test_expired_success_is_not_scored(tmp_path):
    store = Store(str(tmp_path / "ttl.db"))
    store.append_provider_outcome(
        "openai", success=True, ts=datetime.now(timezone.utc) - timedelta(days=2),
    )
    assert store.recent_provider_outcomes() == []
    router = ModelRouter([openai_like()], outcome_store=store)
    assert router.history_for("openai").samples == 0
    assert router.history_for("openai").score_delta() == 0.0


def test_build_router_persists_outcomes_on_the_store(tmp_path):
    path = tmp_path / "built.db"
    store = Store(str(path))
    router = build_router(model_provider=openai_like(), outcome_store=store)
    router.record_outcome("openai", False, failure_class=FailureClass.TIMEOUT)
    fresh = Store(str(path))
    rows = fresh.recent_provider_outcomes()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "failure"
    assert rows[0]["failure_class"] == "TIMEOUT"

