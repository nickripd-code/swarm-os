import json

import httpx
import pytest

from app.llm import (
    OllamaModelProvider, OpenAIResponsesModelProvider, OpenRouterModelProvider,
    XAIModelProvider, build_controller, build_model_provider, build_router,
)
from app.models import FailureClass
from app.providers import FailoverModelProvider, ModelProvider, ModelRequest, ProviderError
from app.router import CapabilityRequest, ModelRouter


REQUEST = ModelRequest(
    model="grok-3",
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    max_output_tokens=100,
)


def completed_chat(output=None, model="grok-3"):
    return httpx.Response(200, json={
        "id": "xai_contract",
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant",
            "content": json.dumps(output or {"answer": "ok"}),
        }}],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    })


def xai_transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture
def no_extra_providers(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLAMACPP_MODEL", raising=False)
    monkeypatch.delenv("LLAMACPP_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
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


@pytest.mark.asyncio
async def test_xai_adapter_implements_provider_contract_and_tracks_usage(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        captured["authorization"] = request.headers["Authorization"]
        return completed_chat()

    provider = XAIModelProvider(api_key="xai-secret", transport=xai_transport(handler))
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "xai"
    assert models[0].model == "grok-3"
    assert models[0].local is False
    assert models[0].capabilities.structured_outputs is True

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "xai"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 3,
    }
    assert captured["url"] == "https://api.x.ai/v1/chat/completions"
    assert captured["authorization"] == "Bearer xai-secret"
    assert captured["body"]["model"] == "grok-3"
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert "json_schema" in captured["body"]["response_format"]
    assert "provider" not in captured["body"]
    assert "xai-secret" not in json.dumps(response.model_dump())
    assert (await provider.health()).status == "healthy"
    assert provider.estimate_cost(REQUEST).known is False


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(401, json={"error": {"message": "xai-secret"}}),
     "rejected the API key", FailureClass.AUTHORIZATION_REQUIRED),
    (httpx.Response(402, json={"error": {}}), "credits are exhausted", FailureClass.RESOURCE_EXHAUSTED),
    (httpx.Response(429, json={"error": {}}), "quota or rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={"error": {}}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(404, json={"error": {}}), "model is unavailable", FailureClass.CAPABILITY_MISMATCH),
    (httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
     "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}),
     "declined", FailureClass.POLICY_REFUSAL),
])
async def test_xai_errors_are_classified_and_do_not_leak(
        no_extra_providers, response, expected, failure_class):
    provider = XAIModelProvider(api_key="xai-secret", transport=xai_transport(lambda _: response))
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST)
    assert "xai-secret" not in str(error.value)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_xai_timeout_and_outage_are_classified(no_extra_providers):
    timeout_provider = XAIModelProvider(
        api_key="xai-secret",
        transport=xai_transport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = XAIModelProvider(
        api_key="xai-secret",
        transport=xai_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach xAI") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_health_unconfigured_when_key_missing(no_extra_providers):
    provider = XAIModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_custom_base_url_is_used(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_chat(model="grok-4")

    provider = XAIModelProvider(
        model="grok-4",
        api_key="xai-secret",
        base_url="https://xai.internal/v1",
        transport=xai_transport(handler),
    )
    await provider.complete(REQUEST.model_copy(update={"model": "grok-4"}))
    assert captured["url"] == "https://xai.internal/v1/chat/completions"


def test_build_model_provider_openai_only_ignores_unconfigured_xai(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai"]


def test_build_router_registers_xai_when_key_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "xai"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "xai"]


def test_build_router_cloud_plus_xai_and_ollama(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == [
        "openai", "openrouter", "xai", "ollama",
    ]
    controller = build_controller()
    assert [item.provider_id for item in controller.router.providers] == [
        "openai", "openrouter", "xai", "ollama",
    ]


def test_build_model_provider_xai_only(monkeypatch, no_extra_providers):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    provider = build_model_provider(primary=primary)
    assert isinstance(provider, XAIModelProvider)
    router = build_router(model_provider=provider)
    assert [item.provider_id for item in router.providers] == ["xai"]


def test_openai_plus_openrouter_still_failover_when_xai_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "openrouter", "xai"]


@pytest.mark.asyncio
async def test_router_outage_walks_to_xai(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    def handler(_request):
        return completed_chat(output={"answer": "from xai"})

    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    xai = XAIModelProvider(api_key="xai-secret", transport=xai_transport(handler))
    router = ModelRouter([openai, openrouter, xai])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "xai"
    assert response.output == {"answer": "from xai"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_local_only_does_not_select_xai(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    xai = XAIModelProvider(api_key="xai-secret", transport=xai_transport(lambda _: completed_chat()))
    ollama = OllamaModelProvider(model="llama3.2", transport=xai_transport(lambda _: completed_chat()))
    router = ModelRouter([openai_like(), openrouter_like(), xai, ollama])
    decision = await router.select(CapabilityRequest(privacy="local_only"))
    assert decision.selected.provider_id == "ollama"
    assert all(candidate.provider_id != "xai" for candidate in decision.chain)


@pytest.mark.asyncio
async def test_unconfigured_xai_is_skipped_and_cloud_still_serves(no_extra_providers):
    from tests.test_router import openai_like

    xai = XAIModelProvider()
    openai = openai_like(output={"answer": "cloud"})
    router = ModelRouter([openai, xai])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert openai.calls == 1
    with pytest.raises(ProviderError, match="not configured"):
        await xai.complete(REQUEST)
