import json

import httpx
import pytest

from app.health import bedrock_status
from app.llm import (
    BedrockModelProvider, DEFAULT_BEDROCK_MODEL,
    DEFAULT_BEDROCK_REGION, OllamaModelProvider, OpenAIResponsesModelProvider,
    build_controller, build_model_provider, build_router, default_bedrock_base_url,
)
from app.models import FailureClass
from app.providers import FailoverModelProvider, ModelProvider, ModelRequest, ProviderError
from app.router import CapabilityRequest, ModelRouter


BEDROCK_MODEL = DEFAULT_BEDROCK_MODEL
BEDROCK_REGION = DEFAULT_BEDROCK_REGION
BEDROCK_BASE_URL = default_bedrock_base_url(BEDROCK_REGION)
REQUEST = ModelRequest(
    model=BEDROCK_MODEL,
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    max_output_tokens=100,
)


def completed_converse(output=None, *, as_text=False, stop_reason="tool_use"):
    payload = output or {"answer": "ok"}
    if as_text:
        content = [{"text": json.dumps(payload)}]
        stop_reason = "end_turn"
    else:
        content = [{"toolUse": {"toolUseId": "tooluse_contract", "name": "answer", "input": payload}}]
    return httpx.Response(200, json={
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop_reason,
        "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
    })


def bedrock_transport(handler):
    return httpx.MockTransport(handler)


def bedrock_provider(**kwargs):
    defaults = dict(api_key="bedrock-secret", region=BEDROCK_REGION, model=BEDROCK_MODEL)
    defaults.update(kwargs)
    return BedrockModelProvider(**defaults)


def opt_in_bedrock(monkeypatch, **overrides):
    values = {"BEDROCK_API_KEY": "bedrock-test"}
    values.update(overrides)
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
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
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HUGGINGFACE_MODEL", raising=False)
    monkeypatch.delenv("HUGGINGFACE_BASE_URL", raising=False)


@pytest.mark.asyncio
async def test_bedrock_adapter_implements_provider_contract_and_tracks_usage(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        captured["authorization"] = request.headers.get("Authorization")
        captured["api_key"] = request.headers.get("api-key")
        return completed_converse()

    provider = bedrock_provider(transport=bedrock_transport(handler))
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "bedrock"
    assert models[0].model == BEDROCK_MODEL
    assert models[0].local is False
    assert models[0].capabilities.structured_outputs is True

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "bedrock"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 0,
    }
    assert captured["url"] == f"{BEDROCK_BASE_URL}/model/{BEDROCK_MODEL}/converse"
    assert captured["authorization"] == "Bearer bedrock-secret"
    assert captured["api_key"] is None
    assert "bedrock-secret" not in captured["url"]
    assert "model" not in captured["body"]
    assert captured["body"]["system"] == [{"text": "Return JSON"}]
    assert captured["body"]["inferenceConfig"]["maxTokens"] == 100
    assert captured["body"]["toolConfig"]["toolChoice"]["tool"]["name"] == "answer"
    assert captured["body"]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "answer"
    dumped = json.dumps(response.model_dump())
    assert "bedrock-secret" not in dumped
    assert (await provider.health()).status == "healthy"
    assert provider.estimate_cost(REQUEST).known is False


@pytest.mark.asyncio
async def test_bedrock_accepts_text_json_fallback(no_extra_providers):
    provider = bedrock_provider(transport=bedrock_transport(lambda _: completed_converse(as_text=True)))
    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(401, json={"message": "bedrock-secret"}),
     "rejected the API key", FailureClass.AUTHORIZATION_REQUIRED),
    (httpx.Response(402, json={}), "credits are exhausted", FailureClass.RESOURCE_EXHAUSTED),
    (httpx.Response(429, json={}), "quota or rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(404, json={}), "model is unavailable", FailureClass.CAPABILITY_MISMATCH),
    (httpx.Response(422, json={}), "rejected the model request", FailureClass.MODEL_FAILURE),
    (httpx.Response(424, json={}), "rejected the model request", FailureClass.MODEL_FAILURE),
    (completed_converse(stop_reason="max_tokens"), "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"output": {"message": {"content": [{"text": "not-json"}]}},
                               "stopReason": "end_turn"}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (completed_converse(stop_reason="guardrail_intervened"), "declined", FailureClass.POLICY_REFUSAL),
    (completed_converse(stop_reason="content_filtered"), "declined", FailureClass.POLICY_REFUSAL),
])
async def test_bedrock_errors_are_classified_and_do_not_leak(
        no_extra_providers, response, expected, failure_class):
    provider = bedrock_provider(transport=bedrock_transport(lambda _: response))
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST)
    assert "bedrock-secret" not in str(error.value)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_bedrock_timeout_and_outage_are_classified(no_extra_providers):
    timeout_provider = bedrock_provider(
        transport=bedrock_transport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = bedrock_provider(
        transport=bedrock_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach Bedrock") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_health_unconfigured_when_key_missing(no_extra_providers):
    provider = BedrockModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [
    {"BEDROCK_MODEL": "amazon.nova-pro-v1:0"},
    {"BEDROCK_REGION": "us-west-2"},
    {"BEDROCK_BASE_URL": "https://bedrock.internal"},
    {"AWS_ACCESS_KEY_ID": "AKIAEXAMPLE", "AWS_SECRET_ACCESS_KEY": "aws-secret",
     "AWS_REGION": "us-east-1"},
])
async def test_partial_bedrock_env_does_not_opt_in(monkeypatch, no_extra_providers, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    provider = BedrockModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert "aws-secret" not in str(error.value)
    assert "AKIAEXAMPLE" not in str(error.value)


@pytest.mark.asyncio
async def test_aws_bearer_token_alias_opts_in(monkeypatch, no_extra_providers):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-alias")
    captured = {}

    def handler(request):
        captured["authorization"] = request.headers.get("Authorization")
        return completed_converse()

    provider = BedrockModelProvider(transport=bedrock_transport(handler))
    assert provider.configured() is True
    assert (await provider.health()).status == "healthy"
    await provider.complete(REQUEST)
    assert captured["authorization"] == "Bearer bedrock-alias"


@pytest.mark.asyncio
async def test_custom_region_and_base_url_are_used(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_converse()

    provider = bedrock_provider(
        model="anthropic.claude-sonnet-4-5-20250929-v1:0",
        region="eu-west-1",
        base_url="https://vpce.bedrock-runtime.eu-west-1.vpce.amazonaws.com",
        transport=bedrock_transport(handler),
    )
    await provider.complete(REQUEST.model_copy(
        update={"model": "anthropic.claude-sonnet-4-5-20250929-v1:0"}))
    assert captured["url"] == (
        "https://vpce.bedrock-runtime.eu-west-1.vpce.amazonaws.com"
        "/model/anthropic.claude-sonnet-4-5-20250929-v1:0/converse"
    )


def test_bedrock_health_status_is_truthful_and_does_not_expose_key(monkeypatch, no_extra_providers):
    status = bedrock_status()
    assert status == {
        "configured": False,
        "model": BEDROCK_MODEL,
        "region": BEDROCK_REGION,
        "base_url": BEDROCK_BASE_URL,
        "provider": "bedrock",
        "fallback": False,
    }
    opt_in_bedrock(monkeypatch, BEDROCK_API_KEY="bedrock-secret",
                   BEDROCK_MODEL="amazon.nova-pro-v1:0", BEDROCK_REGION="us-west-2")
    configured = bedrock_status()
    assert configured["configured"] is True
    assert configured["model"] == "amazon.nova-pro-v1:0"
    assert configured["region"] == "us-west-2"
    assert configured["base_url"] == default_bedrock_base_url("us-west-2")
    assert configured["fallback"] is False
    dumped = json.dumps(configured)
    assert "bedrock-secret" not in dumped
    assert "BEDROCK_API_KEY" not in dumped
    assert "AWS_BEARER_TOKEN_BEDROCK" not in dumped


def test_build_model_provider_openai_only_ignores_unconfigured_bedrock(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai"]


def test_build_router_registers_bedrock_when_key_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    opt_in_bedrock(monkeypatch)
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "bedrock"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "bedrock"]


def test_build_router_cloud_plus_bedrock_and_ollama(monkeypatch, no_extra_providers):
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
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-test")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "perplexity-test")
    opt_in_bedrock(monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "mistral", "gemini", "cohere", "deepseek",
        "together", "groq", "fireworks", "azure", "perplexity", "bedrock", "ollama",
    ]
    controller = build_controller()
    assert [item.provider_id for item in controller.router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "mistral", "gemini", "cohere", "deepseek",
        "together", "groq", "fireworks", "azure", "perplexity", "bedrock", "ollama",
    ]


def test_build_model_provider_bedrock_only(monkeypatch, no_extra_providers):
    opt_in_bedrock(monkeypatch)
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    provider = build_model_provider(primary=primary)
    assert isinstance(provider, BedrockModelProvider)
    router = build_router(model_provider=provider)
    assert [item.provider_id for item in router.providers] == ["bedrock"]


def test_openai_plus_openrouter_still_failover_when_bedrock_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    opt_in_bedrock(monkeypatch)
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "openrouter", "bedrock"]


@pytest.mark.asyncio
async def test_router_outage_walks_to_bedrock(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    def handler(_request):
        return completed_converse(output={"answer": "from bedrock"})

    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    bedrock = bedrock_provider(transport=bedrock_transport(handler))
    router = ModelRouter([openai, openrouter, bedrock])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "bedrock"
    assert response.output == {"answer": "from bedrock"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_local_only_does_not_select_bedrock(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    bedrock = bedrock_provider(transport=bedrock_transport(lambda _: completed_converse()))
    ollama = OllamaModelProvider(model="llama3.2", transport=bedrock_transport(lambda _: completed_converse()))
    router = ModelRouter([openai_like(), openrouter_like(), bedrock, ollama])
    decision = await router.select(CapabilityRequest(privacy="local_only"))
    assert decision.selected.provider_id == "ollama"
    assert all(candidate.provider_id != "bedrock" for candidate in decision.chain)


@pytest.mark.asyncio
async def test_unconfigured_bedrock_is_skipped_and_cloud_still_serves(no_extra_providers):
    from tests.test_router import openai_like

    bedrock = BedrockModelProvider()
    openai = openai_like(output={"answer": "cloud"})
    router = ModelRouter([openai, bedrock])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert openai.calls == 1
    with pytest.raises(ProviderError, match="not configured"):
        await bedrock.complete(REQUEST)
