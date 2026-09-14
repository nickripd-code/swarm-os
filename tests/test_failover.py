import json

import pytest

from app.llm import OpenAIProvider, OpenRouterModelProvider, OpenAIResponsesModelProvider, build_model_provider
from app.models import FailureClass, Mission
from app.providers import (
    ContextLimits, CostEstimate, FailoverModelProvider, ModelCapabilities, ModelProvider,
    ModelRequest, ModelResponse, ModelUsage, ProviderError, ProviderHealth,
)
from app.runtime import SwarmRuntime
from app.store import Store


REQUEST = ModelRequest(model="gpt-6-astra", instructions="Return JSON", input={"goal": "test"})


class FakeModelProvider(ModelProvider):
    def __init__(self, provider_id: str, model: str, *, configured: bool = True,
                 health: str = "healthy", error: ProviderError | None = None,
                 output: dict | None = None):
        self.provider_id = provider_id
        self.model = model
        self._configured = configured
        self._health = health
        self.error = error
        self.output = output or {"action": "finish", "summary": f"from {provider_id}"}
        self.calls = 0
        self.requested_models: list[str] = []
        self._usage = ModelUsage()

    def configured(self) -> bool:
        return self._configured

    async def list_models(self):
        return []

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(structured_outputs=True)

    def context_limits(self, model: str) -> ContextLimits:
        return ContextLimits(max_output_tokens=100)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.provider_id, status=self._health)

    def estimate_cost(self, request: ModelRequest) -> CostEstimate:
        return CostEstimate(provider=self.provider_id, model=request.model, known=False)

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


@pytest.mark.asyncio
async def test_healthy_primary_does_not_call_secondary():
    primary = FakeModelProvider("openai", "gpt-6-astra", output={"answer": "primary"})
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o")
    provider = FailoverModelProvider(primary, secondary)
    response = await provider.complete(REQUEST)
    assert primary.calls == 1
    assert secondary.calls == 0
    assert response.provider == "openai"
    assert response.failover_from is None


@pytest.mark.asyncio
async def test_outage_fails_over_to_secondary_and_records_switch():
    primary = FakeModelProvider("openai", "gpt-6-astra",
                                error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o",
                                  output={"answer": "from openrouter"})
    provider = FailoverModelProvider(primary, secondary)
    response = await provider.complete(REQUEST)
    assert primary.calls == 1
    assert secondary.calls == 1
    assert secondary.requested_models == ["openai/gpt-4o"]
    assert response.provider == "openrouter"
    assert response.output == {"answer": "from openrouter"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_unconfigured_primary_uses_secondary_without_calling_primary():
    primary = FakeModelProvider("openai", "gpt-6-astra", configured=False, health="unconfigured")
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o")
    provider = FailoverModelProvider(primary, secondary)
    response = await provider.complete(REQUEST)
    assert primary.calls == 0
    assert secondary.calls == 1
    assert response.failover_from == "openai"
    assert response.failover_reason == "unconfigured"


@pytest.mark.asyncio
async def test_unavailable_primary_uses_secondary_without_calling_primary():
    primary = FakeModelProvider("openai", "gpt-6-astra", health="unavailable")
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o")
    provider = FailoverModelProvider(primary, secondary)
    response = await provider.complete(REQUEST)
    assert primary.calls == 0
    assert secondary.calls == 1
    assert response.failover_reason == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_class,message", [
    (FailureClass.AUTHORIZATION_REQUIRED, "OpenAI rejected the API key"),
    (FailureClass.POLICY_REFUSAL, "The model declined the request"),
    (FailureClass.INVALID_OUTPUT, "invalid structured"),
    (FailureClass.RATE_LIMIT, "quota or rate limit"),
    (FailureClass.TIMEOUT, "timed out"),
])
async def test_non_outage_errors_do_not_fail_over(failure_class, message):
    primary = FakeModelProvider("openai", "gpt-6-astra",
                                error=ProviderError(message, failure_class))
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o")
    provider = FailoverModelProvider(primary, secondary)
    with pytest.raises(ProviderError) as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == failure_class
    assert primary.calls == 1
    assert secondary.calls == 0


@pytest.mark.asyncio
async def test_both_providers_down_fail_closed_with_outage():
    primary = FakeModelProvider("openai", "gpt-6-astra",
                                error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o",
                                  error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE))
    provider = FailoverModelProvider(primary, secondary)
    with pytest.raises(ProviderError, match="Could not reach OpenRouter") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert primary.calls == 1
    assert secondary.calls == 1


@pytest.mark.asyncio
async def test_neither_provider_configured_fails_closed():
    primary = FakeModelProvider("openai", "gpt-6-astra", configured=False, health="unconfigured")
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o", configured=False, health="unconfigured")
    provider = FailoverModelProvider(primary, secondary)
    with pytest.raises(ProviderError, match="No model provider is configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert primary.calls == 0
    assert secondary.calls == 0


def test_build_model_provider_openai_only_skips_failover(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)


def test_build_model_provider_openrouter_only(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    # Ignore machine-local OpenAI credentials from Windows Credential Manager.
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    secondary = OpenRouterModelProvider(api_key="or-test")
    provider = build_model_provider(primary=primary, secondary=secondary)
    assert isinstance(provider, OpenRouterModelProvider)


@pytest.mark.asyncio
async def test_runtime_openai_outage_then_openrouter_success(tmp_path):
    primary = FakeModelProvider("openai", "gpt-6-astra",
                                error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o",
                                  output={"action": "finish", "summary": "Delivered via OpenRouter"})
    controller = OpenAIProvider(model_provider=FailoverModelProvider(primary, secondary))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Recover from an OpenAI outage")
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


@pytest.mark.asyncio
async def test_runtime_both_providers_down_never_uses_demo_fallback(tmp_path):
    primary = FakeModelProvider("openai", "gpt-6-astra",
                                error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    secondary = FakeModelProvider("openrouter", "openai/gpt-4o",
                                  error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE))
    controller = OpenAIProvider(model_provider=FailoverModelProvider(primary, secondary))
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Fail closed when every provider is down")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result == {"error": "Could not reach OpenRouter", "failure_class": "PROVIDER_OUTAGE"}
    events = store.events(mission.id)
    assert not any(e.event_type in {"controller.fallback", "mission.completed"} for e in events)
    assert any(e.event_type == "mission.failed" and e.payload.get("failure_class") == "PROVIDER_OUTAGE"
               for e in events)
    assert json.dumps([e.payload for e in events]).count("Demo") == 0

