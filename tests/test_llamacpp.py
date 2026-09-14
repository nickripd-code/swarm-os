import json

import httpx
import pytest

from app.llm import (
    LlamaCppModelProvider, OllamaModelProvider, OpenAIResponsesModelProvider,
    OpenRouterModelProvider, build_controller, build_model_provider, build_router,
)
from app.models import FailureClass
from app.providers import FailoverModelProvider, ModelProvider, ModelRequest, ProviderError
from app.router import CapabilityRequest, ModelRouter


REQUEST = ModelRequest(
    model="llama-3.2-3b-instruct",
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    max_output_tokens=100,
)


def completed_chat(output=None, model="llama-3.2-3b-instruct"):
    return httpx.Response(200, json={
        "id": "llamacpp_contract",
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant",
            "content": json.dumps(output or {"answer": "ok"}),
        }}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    })


def models_list(*ids):
    return httpx.Response(200, json={"object": "list", "data": [{"id": model_id} for model_id in ids]})


def llamacpp_transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture
def no_local_env(monkeypatch):
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


@pytest.mark.asyncio
async def test_llamacpp_adapter_implements_provider_contract_and_tracks_usage(no_local_env):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        assert "Authorization" not in request.headers
        return completed_chat()

    provider = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct", transport=llamacpp_transport(handler),
    )
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "llamacpp"
    assert models[0].model == "llama-3.2-3b-instruct"
    assert models[0].local is True
    assert models[0].price_output_per_million == 0

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "llamacpp"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 0,
    }
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert captured["body"]["model"] == "llama-3.2-3b-instruct"
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert "json_schema" in captured["body"]["response_format"]
    assert "provider" not in captured["body"]
    assert "reasoning" not in captured["body"]
    assert provider.estimate_cost(REQUEST).known is True
    assert provider.estimate_cost(REQUEST).estimated_cost == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(404, json={"error": "model not found"}),
     "model is unavailable", FailureClass.CAPABILITY_MISMATCH),
    (httpx.Response(429, json={"error": {}}), "rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={"error": {}}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
     "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}),
     "declined", FailureClass.POLICY_REFUSAL),
])
async def test_llamacpp_errors_are_classified_and_do_not_fake_success(
        no_local_env, response, expected, failure_class):
    provider = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct",
        transport=llamacpp_transport(lambda _: response),
    )
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_llamacpp_timeout_and_outage_are_classified(no_local_env):
    timeout_provider = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct",
        transport=llamacpp_transport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct",
        transport=llamacpp_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach llama.cpp") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_health_unconfigured_when_not_opted_in(no_local_env):
    provider = LlamaCppModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_health_unavailable_when_daemon_down(no_local_env):
    provider = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct",
        transport=llamacpp_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))),
    )
    health = await provider.health()
    assert health.status == "unavailable"
    assert health.detail == "llama.cpp daemon is not reachable"


@pytest.mark.asyncio
async def test_health_healthy_when_models_endpoint_ok(no_local_env):
    provider = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct",
        transport=llamacpp_transport(lambda _: models_list("llama-3.2-3b-instruct")),
    )
    health = await provider.health()
    assert health.status == "healthy"


@pytest.mark.asyncio
async def test_custom_base_url_is_used(no_local_env):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_chat(model="qwen2.5-3b")

    provider = LlamaCppModelProvider(
        model="qwen2.5-3b",
        base_url="http://llamacpp.internal:8081/v1",
        transport=llamacpp_transport(handler),
    )
    await provider.complete(REQUEST.model_copy(update={"model": "qwen2.5-3b"}))
    assert captured["url"] == "http://llamacpp.internal:8081/v1/chat/completions"


def test_build_model_provider_openai_only_ignores_unconfigured_llamacpp(monkeypatch, no_local_env):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai"]


def test_build_router_registers_llamacpp_when_opted_in(monkeypatch, no_local_env):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLAMACPP_MODEL", "llama-3.2-3b-instruct")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "llamacpp"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "llamacpp"]


def test_build_router_cloud_plus_ollama_and_llamacpp(monkeypatch, no_local_env):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    monkeypatch.setenv("LLAMACPP_MODEL", "llama-3.2-3b-instruct")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "openrouter", "ollama", "llamacpp"]
    controller = build_controller()
    assert [item.provider_id for item in controller.router.providers] == [
        "openai", "openrouter", "ollama", "llamacpp",
    ]


def test_build_model_provider_llamacpp_only(monkeypatch, no_local_env):
    monkeypatch.setenv("LLAMACPP_MODEL", "llama-3.2-3b-instruct")
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    provider = build_model_provider(primary=primary)
    assert isinstance(provider, LlamaCppModelProvider)
    router = build_router(model_provider=provider)
    assert [item.provider_id for item in router.providers] == ["llamacpp"]


def test_build_router_local_only_registers_both_adapters(monkeypatch, no_local_env):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    monkeypatch.setenv("LLAMACPP_MODEL", "llama-3.2-3b-instruct")
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    stacked = build_model_provider(primary=primary)
    assert isinstance(stacked, OllamaModelProvider)
    router = build_router(model_provider=stacked)
    assert [item.provider_id for item in router.providers] == ["ollama", "llamacpp"]


@pytest.mark.asyncio
async def test_router_outage_walks_to_llamacpp(no_local_env):
    from tests.test_router import openai_like, openrouter_like

    def handler(request):
        if request.method == "GET":
            return models_list("llama-3.2-3b-instruct")
        return completed_chat(output={"answer": "from llamacpp"})

    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    llamacpp = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct", transport=llamacpp_transport(handler),
    )
    router = ModelRouter([openai, openrouter, llamacpp])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "llamacpp"
    assert response.output == {"answer": "from llamacpp"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_local_only_selects_llamacpp(no_local_env):
    from tests.test_router import openai_like, openrouter_like

    def handler(request):
        if request.method == "GET":
            return models_list("llama-3.2-3b-instruct")
        return completed_chat()

    llamacpp = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct", transport=llamacpp_transport(handler),
    )
    router = ModelRouter([openai_like(), openrouter_like(), llamacpp])
    decision = await router.select(CapabilityRequest(privacy="local_only"))
    assert decision.selected.provider_id == "llamacpp"
    assert decision.fallbacks == []


@pytest.mark.asyncio
async def test_unavailable_llamacpp_is_skipped_and_cloud_still_serves(no_local_env):
    from tests.test_router import openai_like

    llamacpp = LlamaCppModelProvider(
        model="llama-3.2-3b-instruct",
        transport=llamacpp_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))),
    )
    openai = openai_like(output={"answer": "cloud"})
    router = ModelRouter([openai, llamacpp])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert openai.calls == 1
    with pytest.raises(ProviderError, match="Could not reach llama.cpp"):
        await llamacpp.complete(REQUEST)
