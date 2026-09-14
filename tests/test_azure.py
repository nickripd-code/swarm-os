import json

import httpx
import pytest

from app.health import azure_status
from app.llm import (
    AzureOpenAIModelProvider, OllamaModelProvider, OpenAIResponsesModelProvider,
    build_controller, build_model_provider, build_router,
)
from app.models import FailureClass
from app.providers import FailoverModelProvider, ModelProvider, ModelRequest, ProviderError
from app.router import CapabilityRequest, ModelRouter


AZURE_ENDPOINT = "https://example.openai.azure.com"
AZURE_DEPLOYMENT = "gpt-4o"
AZURE_API_VERSION = "2024-10-21"
REQUEST = ModelRequest(
    model=AZURE_DEPLOYMENT,
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    max_output_tokens=100,
)


def completed_chat(output=None, model=AZURE_DEPLOYMENT):
    return httpx.Response(200, json={
        "id": "azure_contract",
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


def azure_transport(handler):
    return httpx.MockTransport(handler)


def azure_provider(**kwargs):
    defaults = dict(
        api_key="azure-secret",
        endpoint=AZURE_ENDPOINT,
        deployment=AZURE_DEPLOYMENT,
    )
    defaults.update(kwargs)
    return AzureOpenAIModelProvider(**defaults)


def opt_in_azure(monkeypatch, **overrides):
    values = {
        "AZURE_OPENAI_API_KEY": "azure-test",
        "AZURE_OPENAI_ENDPOINT": AZURE_ENDPOINT,
        "AZURE_OPENAI_DEPLOYMENT": AZURE_DEPLOYMENT,
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


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


@pytest.mark.asyncio
async def test_azure_adapter_implements_provider_contract_and_tracks_usage(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        captured["api_key"] = request.headers.get("api-key")
        captured["authorization"] = request.headers.get("Authorization")
        return completed_chat()

    provider = azure_provider(transport=azure_transport(handler))
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "azure"
    assert models[0].model == AZURE_DEPLOYMENT
    assert models[0].local is False
    assert models[0].capabilities.structured_outputs is True

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "azure"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 3,
    }
    assert captured["url"] == (
        f"{AZURE_ENDPOINT}/openai/deployments/{AZURE_DEPLOYMENT}"
        f"/chat/completions?api-version={AZURE_API_VERSION}"
    )
    assert captured["api_key"] == "azure-secret"
    assert captured["authorization"] is None
    assert "azure-secret" not in captured["url"]
    assert captured["body"]["model"] == AZURE_DEPLOYMENT
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert "json_schema" in captured["body"]["response_format"]
    assert "provider" not in captured["body"]
    dumped = json.dumps(response.model_dump())
    assert "azure-secret" not in dumped
    assert (await provider.health()).status == "healthy"
    assert provider.estimate_cost(REQUEST).known is False


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(401, json={"error": {"message": "azure-secret"}}),
     "rejected the API key", FailureClass.AUTHORIZATION_REQUIRED),
    (httpx.Response(402, json={"error": {}}), "credits are exhausted", FailureClass.RESOURCE_EXHAUSTED),
    (httpx.Response(429, json={"error": {}}), "quota or rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={"error": {}}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(404, json={"error": {}}), "deployment is unavailable", FailureClass.CAPABILITY_MISMATCH),
    (httpx.Response(422, json={"error": {}}), "rejected the model request", FailureClass.MODEL_FAILURE),
    (httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
     "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}),
     "declined", FailureClass.POLICY_REFUSAL),
])
async def test_azure_errors_are_classified_and_do_not_leak(
        no_extra_providers, response, expected, failure_class):
    provider = azure_provider(transport=azure_transport(lambda _: response))
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST)
    assert "azure-secret" not in str(error.value)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_azure_timeout_and_outage_are_classified(no_extra_providers):
    timeout_provider = azure_provider(
        transport=azure_transport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = azure_provider(
        transport=azure_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach Azure OpenAI") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_health_unconfigured_when_key_missing(no_extra_providers):
    provider = AzureOpenAIModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [
    {"AZURE_OPENAI_API_KEY": "azure-secret"},
    {"AZURE_OPENAI_ENDPOINT": AZURE_ENDPOINT},
    {"AZURE_OPENAI_DEPLOYMENT": AZURE_DEPLOYMENT},
    {"AZURE_OPENAI_API_KEY": "azure-secret", "AZURE_OPENAI_ENDPOINT": AZURE_ENDPOINT},
    {"AZURE_OPENAI_API_KEY": "azure-secret", "AZURE_OPENAI_DEPLOYMENT": AZURE_DEPLOYMENT},
    {"AZURE_OPENAI_ENDPOINT": AZURE_ENDPOINT, "AZURE_OPENAI_DEPLOYMENT": AZURE_DEPLOYMENT},
])
async def test_partial_azure_env_does_not_opt_in(monkeypatch, no_extra_providers, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    provider = AzureOpenAIModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert "azure-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_custom_endpoint_and_api_version_are_used(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_chat(model="gpt-4o-mini")

    provider = azure_provider(
        model="gpt-4o-mini",
        endpoint="https://internal.openai.azure.com",
        deployment="gpt-4o-mini",
        api_version="2024-08-01-preview",
        transport=azure_transport(handler),
    )
    await provider.complete(REQUEST.model_copy(update={"model": "gpt-4o-mini"}))
    assert captured["url"] == (
        "https://internal.openai.azure.com/openai/deployments/gpt-4o-mini"
        "/chat/completions?api-version=2024-08-01-preview"
    )


def test_azure_health_status_is_truthful_and_does_not_expose_key(monkeypatch, no_extra_providers):
    status = azure_status()
    assert status == {
        "configured": False,
        "model": None,
        "endpoint": None,
        "deployment": None,
        "api_version": AZURE_API_VERSION,
        "provider": "azure",
        "fallback": False,
    }
    opt_in_azure(monkeypatch, AZURE_OPENAI_API_KEY="azure-secret",
                 AZURE_OPENAI_DEPLOYMENT="gpt-4o-mini")
    configured = azure_status()
    assert configured["configured"] is True
    assert configured["model"] == "gpt-4o-mini"
    assert configured["deployment"] == "gpt-4o-mini"
    assert configured["endpoint"] == AZURE_ENDPOINT
    assert configured["fallback"] is False
    dumped = json.dumps(configured)
    assert "azure-secret" not in dumped
    assert "AZURE_OPENAI_API_KEY" not in dumped


def test_build_model_provider_openai_only_ignores_unconfigured_azure(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai"]


def test_build_router_registers_azure_when_fully_configured(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    opt_in_azure(monkeypatch)
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "azure"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "azure"]


def test_build_router_cloud_plus_azure_and_ollama(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
    monkeypatch.setenv("TOGETHER_API_KEY", "together-test")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fireworks-test")
    opt_in_azure(monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "mistral", "gemini", "cohere", "deepseek",
        "together", "groq", "fireworks", "azure", "ollama",
    ]
    controller = build_controller()
    assert [item.provider_id for item in controller.router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "mistral", "gemini", "cohere", "deepseek",
        "together", "groq", "fireworks", "azure", "ollama",
    ]


def test_build_model_provider_azure_only(monkeypatch, no_extra_providers):
    opt_in_azure(monkeypatch)
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    provider = build_model_provider(primary=primary)
    assert isinstance(provider, AzureOpenAIModelProvider)
    router = build_router(model_provider=provider)
    assert [item.provider_id for item in router.providers] == ["azure"]


def test_openai_plus_openrouter_still_failover_when_azure_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    opt_in_azure(monkeypatch)
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "openrouter", "azure"]


@pytest.mark.asyncio
async def test_router_outage_walks_to_azure(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    def handler(_request):
        return completed_chat(output={"answer": "from azure"})

    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    azure = azure_provider(transport=azure_transport(handler))
    router = ModelRouter([openai, openrouter, azure])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "azure"
    assert response.output == {"answer": "from azure"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_local_only_does_not_select_azure(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    azure = azure_provider(transport=azure_transport(lambda _: completed_chat()))
    ollama = OllamaModelProvider(model="llama3.2", transport=azure_transport(lambda _: completed_chat()))
    router = ModelRouter([openai_like(), openrouter_like(), azure, ollama])
    decision = await router.select(CapabilityRequest(privacy="local_only"))
    assert decision.selected.provider_id == "ollama"
    assert all(candidate.provider_id != "azure" for candidate in decision.chain)


@pytest.mark.asyncio
async def test_unconfigured_azure_is_skipped_and_cloud_still_serves(no_extra_providers):
    from tests.test_router import openai_like

    azure = AzureOpenAIModelProvider()
    openai = openai_like(output={"answer": "cloud"})
    router = ModelRouter([openai, azure])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert openai.calls == 1
    with pytest.raises(ProviderError, match="not configured"):
        await azure.complete(REQUEST)
