import json

import httpx
import pytest

from app.llm import (
    ANTHROPIC_API_VERSION, AnthropicModelProvider, OllamaModelProvider,
    OpenAIResponsesModelProvider, OpenRouterModelProvider, XAIModelProvider,
    build_controller, build_model_provider, build_router,
)
from app.models import FailureClass
from app.providers import FailoverModelProvider, ModelProvider, ModelRequest, ProviderError
from app.router import CapabilityRequest, ModelRouter


REQUEST = ModelRequest(
    model="claude-sonnet-4-5",
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    max_output_tokens=100,
)


def completed_messages(output=None, model="claude-sonnet-4-5", *, as_text=False):
    payload = output or {"answer": "ok"}
    if as_text:
        content = [{"type": "text", "text": json.dumps(payload)}]
        stop_reason = "end_turn"
    else:
        content = [{
            "type": "tool_use",
            "id": "toolu_contract",
            "name": "answer",
            "input": payload,
        }]
        stop_reason = "tool_use"
    return httpx.Response(200, json={
        "id": "msg_contract",
        "type": "message",
        "role": "assistant",
        "model": model,
        "stop_reason": stop_reason,
        "content": content,
        "usage": {"input_tokens": 11, "output_tokens": 7},
    })


def anthropic_transport(handler):
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


@pytest.mark.asyncio
async def test_anthropic_adapter_implements_provider_contract_and_tracks_usage(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        captured["api_key"] = request.headers["x-api-key"]
        captured["version"] = request.headers["anthropic-version"]
        captured["authorization"] = request.headers.get("Authorization")
        return completed_messages()

    provider = AnthropicModelProvider(api_key="anthropic-secret", transport=anthropic_transport(handler))
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "anthropic"
    assert models[0].model == "claude-sonnet-4-5"
    assert models[0].local is False
    assert models[0].capabilities.structured_outputs is True
    assert models[0].capabilities.tool_use is True

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "anthropic"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 0,
    }
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["method"] == "POST"
    assert captured["api_key"] == "anthropic-secret"
    assert captured["version"] == ANTHROPIC_API_VERSION
    assert captured["authorization"] is None
    assert captured["body"]["model"] == "claude-sonnet-4-5"
    assert captured["body"]["system"] == "Return JSON"
    assert captured["body"]["messages"] == [{"role": "user", "content": json.dumps({"question": "test"})}]
    assert captured["body"]["tools"][0]["name"] == "answer"
    assert captured["body"]["tool_choice"] == {"type": "tool", "name": "answer"}
    assert "anthropic-secret" not in json.dumps(response.model_dump())
    assert "anthropic-secret" not in json.dumps(captured["body"])
    assert (await provider.health()).status == "healthy"
    assert provider.estimate_cost(REQUEST).known is False


@pytest.mark.asyncio
async def test_anthropic_parses_text_json_when_no_tool_use(no_extra_providers):
    provider = AnthropicModelProvider(
        api_key="anthropic-secret",
        transport=anthropic_transport(lambda _: completed_messages(as_text=True)),
    )
    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "anthropic"


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(401, json={"error": {"message": "anthropic-secret"}}),
     "rejected the API key", FailureClass.AUTHORIZATION_REQUIRED),
    (httpx.Response(402, json={"error": {}}), "credits are exhausted", FailureClass.RESOURCE_EXHAUSTED),
    (httpx.Response(429, json={"error": {}}), "quota or rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={"error": {}}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(529, json={"error": {}}), "overloaded", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(404, json={"error": {}}), "model is unavailable", FailureClass.CAPABILITY_MISMATCH),
    (httpx.Response(200, json={"stop_reason": "max_tokens", "content": [{"type": "text", "text": "{}"}]}),
     "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": "not-json"}]}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (httpx.Response(200, json={"stop_reason": "refusal", "content": [{"type": "text", "text": "no"}]}),
     "declined", FailureClass.POLICY_REFUSAL),
])
async def test_anthropic_errors_are_classified_and_do_not_leak(
        no_extra_providers, response, expected, failure_class):
    provider = AnthropicModelProvider(api_key="anthropic-secret", transport=anthropic_transport(lambda _: response))
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST)
    assert "anthropic-secret" not in str(error.value)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_anthropic_timeout_and_outage_are_classified(no_extra_providers):
    timeout_provider = AnthropicModelProvider(
        api_key="anthropic-secret",
        transport=anthropic_transport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = AnthropicModelProvider(
        api_key="anthropic-secret",
        transport=anthropic_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach Anthropic") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_health_unconfigured_when_key_missing(no_extra_providers):
    provider = AnthropicModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_model_env_without_key_does_not_opt_in(monkeypatch, no_extra_providers):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")
    provider = AnthropicModelProvider()
    assert provider.configured() is False
    assert provider.model == "claude-opus-4-6"
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError) as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_custom_base_url_is_used(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_messages(model="claude-opus-4-6")

    provider = AnthropicModelProvider(
        model="claude-opus-4-6",
        api_key="anthropic-secret",
        base_url="https://anthropic.internal/v1",
        transport=anthropic_transport(handler),
    )
    await provider.complete(REQUEST.model_copy(update={"model": "claude-opus-4-6"}))
    assert captured["url"] == "https://anthropic.internal/v1/messages"


def test_build_model_provider_openai_only_ignores_unconfigured_anthropic(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai"]


def test_build_router_registers_anthropic_when_key_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "anthropic"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "anthropic"]


def test_build_router_cloud_plus_anthropic_and_ollama(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "ollama",
    ]
    controller = build_controller()
    assert [item.provider_id for item in controller.router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "ollama",
    ]


def test_build_model_provider_anthropic_only(monkeypatch, no_extra_providers):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    provider = build_model_provider(primary=primary)
    assert isinstance(provider, AnthropicModelProvider)
    router = build_router(model_provider=provider)
    assert [item.provider_id for item in router.providers] == ["anthropic"]


def test_openai_plus_openrouter_still_failover_when_anthropic_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "openrouter", "anthropic"]


@pytest.mark.asyncio
async def test_router_outage_walks_to_anthropic(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    def handler(_request):
        return completed_messages(output={"answer": "from anthropic"})

    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    anthropic = AnthropicModelProvider(api_key="anthropic-secret", transport=anthropic_transport(handler))
    router = ModelRouter([openai, openrouter, anthropic])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "anthropic"
    assert response.output == {"answer": "from anthropic"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_local_only_does_not_select_anthropic(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    anthropic = AnthropicModelProvider(
        api_key="anthropic-secret", transport=anthropic_transport(lambda _: completed_messages()))
    ollama = OllamaModelProvider(model="llama3.2", transport=anthropic_transport(lambda _: completed_messages()))
    router = ModelRouter([openai_like(), openrouter_like(), anthropic, ollama])
    decision = await router.select(CapabilityRequest(privacy="local_only"))
    assert decision.selected.provider_id == "ollama"
    assert all(candidate.provider_id != "anthropic" for candidate in decision.chain)


@pytest.mark.asyncio
async def test_unconfigured_anthropic_is_skipped_and_cloud_still_serves(no_extra_providers):
    from tests.test_router import openai_like

    anthropic = AnthropicModelProvider()
    openai = openai_like(output={"answer": "cloud"})
    router = ModelRouter([openai, anthropic])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert openai.calls == 1
    with pytest.raises(ProviderError, match="not configured"):
        await anthropic.complete(REQUEST)
