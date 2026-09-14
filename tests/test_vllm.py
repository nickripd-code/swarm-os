import json

import httpx
import pytest

from app.llm import (
    OllamaModelProvider, OpenAIResponsesModelProvider, OpenRouterModelProvider,
    VllmModelProvider, build_controller, build_model_provider, build_router,
)
from app.models import FailureClass
from app.providers import FailoverModelProvider, ModelProvider, ModelRequest, ProviderError
from app.router import CapabilityRequest, ModelRouter


REQUEST = ModelRequest(
    model="meta-llama/Llama-3.1-8B-Instruct",
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    max_output_tokens=100,
)


def completed_chat(output=None, model="meta-llama/Llama-3.1-8B-Instruct"):
    return httpx.Response(200, json={
        "id": "vllm_contract",
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant",
            "content": json.dumps(output or {"answer": "ok"}),
        }}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    })


def models_list(*ids):
    return httpx.Response(200, json={"object": "list", "data": [{"id": model_id} for model_id in ids]})


def vllm_transport(handler):
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


@pytest.mark.asyncio
async def test_vllm_adapter_implements_provider_contract_and_tracks_usage(no_local_env):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        assert "Authorization" not in request.headers
        return completed_chat()

    provider = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct", transport=vllm_transport(handler),
    )
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "vllm"
    assert models[0].model == "meta-llama/Llama-3.1-8B-Instruct"
    assert models[0].local is True
    assert models[0].price_output_per_million == 0

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "vllm"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 0,
    }
    assert captured["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert captured["body"]["model"] == "meta-llama/Llama-3.1-8B-Instruct"
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
async def test_vllm_errors_are_classified_and_do_not_fake_success(no_local_env, response, expected, failure_class):
    provider = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct",
        transport=vllm_transport(lambda _: response),
    )
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_vllm_timeout_and_outage_are_classified(no_local_env):
    timeout_provider = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct",
        transport=vllm_transport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct",
        transport=vllm_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach vLLM") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_health_unconfigured_when_not_opted_in(no_local_env):
    provider = VllmModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_health_unavailable_when_daemon_down(no_local_env):
    provider = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct",
        transport=vllm_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))),
    )
    health = await provider.health()
    assert health.status == "unavailable"
    assert health.detail == "vLLM daemon is not reachable"


@pytest.mark.asyncio
async def test_health_healthy_when_models_endpoint_ok(no_local_env):
    provider = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct",
        transport=vllm_transport(lambda _: models_list("meta-llama/Llama-3.1-8B-Instruct")),
    )
    health = await provider.health()
    assert health.status == "healthy"


@pytest.mark.asyncio
async def test_custom_base_url_is_used(no_local_env):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_chat(model="Qwen/Qwen2.5-7B-Instruct")

    provider = VllmModelProvider(
        model="Qwen/Qwen2.5-7B-Instruct",
        base_url="http://vllm.internal:8001/v1",
        transport=vllm_transport(handler),
    )
    await provider.complete(REQUEST.model_copy(update={"model": "Qwen/Qwen2.5-7B-Instruct"}))
    assert captured["url"] == "http://vllm.internal:8001/v1/chat/completions"


def test_build_model_provider_openai_only_ignores_unconfigured_vllm(monkeypatch, no_local_env):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai"]


def test_build_router_registers_vllm_when_opted_in(monkeypatch, no_local_env):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "vllm"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "vllm"]


def test_build_router_cloud_plus_ollama_and_vllm(monkeypatch, no_local_env):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    monkeypatch.setenv("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "openrouter", "ollama", "vllm"]
    controller = build_controller()
    assert [item.provider_id for item in controller.router.providers] == [
        "openai", "openrouter", "ollama", "vllm",
    ]


def test_build_model_provider_vllm_only(monkeypatch, no_local_env):
    monkeypatch.setenv("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    provider = build_model_provider(primary=primary)
    assert isinstance(provider, VllmModelProvider)
    router = build_router(model_provider=provider)
    assert [item.provider_id for item in router.providers] == ["vllm"]


def test_build_router_local_only_registers_both_adapters(monkeypatch, no_local_env):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    monkeypatch.setenv("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    stacked = build_model_provider(primary=primary)
    assert isinstance(stacked, OllamaModelProvider)
    router = build_router(model_provider=stacked)
    assert [item.provider_id for item in router.providers] == ["ollama", "vllm"]


@pytest.mark.asyncio
async def test_router_outage_walks_to_vllm(no_local_env):
    from tests.test_router import openai_like, openrouter_like

    def handler(request):
        if request.method == "GET":
            return models_list("meta-llama/Llama-3.1-8B-Instruct")
        return completed_chat(output={"answer": "from vllm"})

    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    vllm = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct", transport=vllm_transport(handler),
    )
    router = ModelRouter([openai, openrouter, vllm])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "vllm"
    assert response.output == {"answer": "from vllm"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_local_only_selects_vllm(no_local_env):
    from tests.test_router import openai_like, openrouter_like

    def handler(request):
        if request.method == "GET":
            return models_list("meta-llama/Llama-3.1-8B-Instruct")
        return completed_chat()

    vllm = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct", transport=vllm_transport(handler),
    )
    router = ModelRouter([openai_like(), openrouter_like(), vllm])
    decision = await router.select(CapabilityRequest(privacy="local_only"))
    assert decision.selected.provider_id == "vllm"
    assert decision.fallbacks == []


@pytest.mark.asyncio
async def test_unavailable_vllm_is_skipped_and_cloud_still_serves(no_local_env):
    from tests.test_router import openai_like

    vllm = VllmModelProvider(
        model="meta-llama/Llama-3.1-8B-Instruct",
        transport=vllm_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))),
    )
    openai = openai_like(output={"answer": "cloud"})
    router = ModelRouter([openai, vllm])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert openai.calls == 1
    with pytest.raises(ProviderError, match="Could not reach vLLM"):
        await vllm.complete(REQUEST)
