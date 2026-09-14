import json

import httpx
import pytest

from app.health import vertex_status
from app.llm import (
    DEFAULT_VERTEX_LOCATION, DEFAULT_VERTEX_MODEL, GeminiModelProvider, OllamaModelProvider,
    OpenAIResponsesModelProvider, VertexAIModelProvider, build_controller, build_model_provider,
    build_router, default_vertex_base_url,
)
from app.models import FailureClass
from app.providers import FailoverModelProvider, ModelProvider, ModelRequest, ProviderError
from app.router import CapabilityRequest, ModelRouter


DEFAULT_MODEL = DEFAULT_VERTEX_MODEL
VERTEX_PROJECT = "swarm-test"
VERTEX_LOCATION = DEFAULT_VERTEX_LOCATION
VERTEX_BASE_URL = default_vertex_base_url(VERTEX_LOCATION)
REQUEST = ModelRequest(
    model=DEFAULT_MODEL,
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    max_output_tokens=100,
)


def completed_generate_content(output=None, model=DEFAULT_MODEL, as_text=False, as_function=False):
    body = output if output is not None else {"answer": "ok"}
    if as_function:
        parts = [{"functionCall": {"name": "answer", "args": body}}]
    elif as_text and isinstance(output, str):
        parts = [{"text": output}]
    else:
        parts = [{"text": json.dumps(body)}]
    return httpx.Response(200, json={
        "responseId": "vertex_contract",
        "modelVersion": model,
        "candidates": [{
            "finishReason": "STOP",
            "content": {"role": "model", "parts": parts},
        }],
        "usageMetadata": {
            "promptTokenCount": 11,
            "candidatesTokenCount": 7,
            "thoughtsTokenCount": 3,
        },
    })


def vertex_transport(handler):
    return httpx.MockTransport(handler)


def vertex_provider(**kwargs):
    defaults = dict(api_key="vertex-secret", project=VERTEX_PROJECT, location=VERTEX_LOCATION,
                    model=DEFAULT_MODEL)
    defaults.update(kwargs)
    return VertexAIModelProvider(**defaults)


def opt_in_vertex(monkeypatch, **overrides):
    values = {"VERTEX_API_KEY": "vertex-test", "VERTEX_PROJECT": VERTEX_PROJECT}
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
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HUGGINGFACE_MODEL", raising=False)
    monkeypatch.delenv("HUGGINGFACE_BASE_URL", raising=False)
    monkeypatch.delenv("VERTEX_API_KEY", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("VERTEX_LOCATION", raising=False)
    monkeypatch.delenv("VERTEX_MODEL", raising=False)
    monkeypatch.delenv("VERTEX_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("CEREBRAS_MODEL", raising=False)
    monkeypatch.delenv("CEREBRAS_BASE_URL", raising=False)
    monkeypatch.delenv("SAMBANOVA_API_KEY", raising=False)
    monkeypatch.delenv("SAMBANOVA_MODEL", raising=False)
    monkeypatch.delenv("SAMBANOVA_BASE_URL", raising=False)


@pytest.mark.asyncio
async def test_vertex_adapter_implements_provider_contract_and_tracks_usage(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        captured["authorization"] = request.headers["Authorization"]
        return completed_generate_content()

    provider = vertex_provider(transport=vertex_transport(handler))
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "vertex"
    assert models[0].model == DEFAULT_MODEL
    assert models[0].local is False
    assert models[0].capabilities.structured_outputs is True

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "vertex"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 3,
    }
    assert captured["url"] == (
        f"{VERTEX_BASE_URL}/v1/projects/{VERTEX_PROJECT}/locations/{VERTEX_LOCATION}"
        f"/publishers/google/models/{DEFAULT_MODEL}:generateContent"
    )
    assert captured["authorization"] == "Bearer vertex-secret"
    assert "vertex-secret" not in captured["url"]
    assert captured["body"]["contents"][0]["parts"][0]["text"]
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["body"]["generationConfig"]["responseSchema"]["properties"]["answer"]["type"] == "string"
    dumped = json.dumps(response.model_dump())
    assert "vertex-secret" not in dumped
    assert (await provider.health()).status == "healthy"
    assert provider.estimate_cost(REQUEST).known is False


@pytest.mark.asyncio
async def test_vertex_accepts_text_json_fallback(no_extra_providers):
    provider = vertex_provider(transport=vertex_transport(
        lambda _: completed_generate_content(as_text=True)))
    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}


@pytest.mark.asyncio
async def test_vertex_accepts_function_call_args(no_extra_providers):
    provider = vertex_provider(transport=vertex_transport(
        lambda _: completed_generate_content(output={"answer": "tool"}, as_function=True)))
    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "tool"}


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(401, json={"error": {"message": "vertex-secret"}}),
     "rejected the API key", FailureClass.AUTHORIZATION_REQUIRED),
    (httpx.Response(402, json={"error": {}}), "credits are exhausted", FailureClass.RESOURCE_EXHAUSTED),
    (httpx.Response(429, json={"error": {}}), "quota or rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={"error": {}}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(404, json={"error": {}}), "model is unavailable", FailureClass.CAPABILITY_MISMATCH),
    (httpx.Response(422, json={"error": {}}), "rejected the model request", FailureClass.MODEL_FAILURE),
    (httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS",
                                              "content": {"parts": [{"text": "{}"}]}}]}),
     "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                                              "content": {"parts": [{"text": "not-json"}]}}]}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY",
                                              "content": {"parts": []}}]}),
     "declined", FailureClass.POLICY_REFUSAL),
    (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}),
     "declined", FailureClass.POLICY_REFUSAL),
])
async def test_vertex_errors_are_classified_and_do_not_leak(
        no_extra_providers, response, expected, failure_class):
    provider = vertex_provider(transport=vertex_transport(lambda _: response))
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST)
    assert "vertex-secret" not in str(error.value)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_vertex_timeout_and_outage_are_classified(no_extra_providers):
    timeout_provider = vertex_provider(
        transport=vertex_transport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = vertex_provider(
        transport=vertex_transport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach Vertex AI") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_health_unconfigured_when_key_missing(no_extra_providers):
    provider = VertexAIModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [
    {"VERTEX_API_KEY": "vertex-secret"},
    {"VERTEX_PROJECT": VERTEX_PROJECT},
    {"VERTEX_MODEL": "gemini-2.5-flash"},
    {"VERTEX_LOCATION": "us-west1"},
    {"VERTEX_BASE_URL": "https://vertex.internal"},
    {"GOOGLE_CLOUD_PROJECT": "ambient-project"},
    {"GEMINI_API_KEY": "gemini-secret", "VERTEX_PROJECT": VERTEX_PROJECT},
    {"GOOGLE_APPLICATION_CREDENTIALS": "/tmp/fake.json",
     "GOOGLE_CLOUD_PROJECT": "ambient-project"},
])
async def test_partial_vertex_env_does_not_opt_in(monkeypatch, no_extra_providers, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    provider = VertexAIModelProvider()
    assert provider.configured() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ProviderError, match="not configured") as error:
        await provider.complete(REQUEST)
    assert error.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert "vertex-secret" not in str(error.value)
    assert "gemini-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_google_cloud_project_alias_opts_in(monkeypatch, no_extra_providers):
    monkeypatch.setenv("VERTEX_API_KEY", "vertex-alias")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "alias-project")
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        return completed_generate_content()

    provider = VertexAIModelProvider(transport=vertex_transport(handler))
    assert provider.configured() is True
    assert (await provider.health()).status == "healthy"
    await provider.complete(REQUEST)
    assert captured["authorization"] == "Bearer vertex-alias"
    assert "/projects/alias-project/" in captured["url"]
    assert "vertex-alias" not in captured["url"]


@pytest.mark.asyncio
async def test_custom_location_and_base_url_are_used(no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_generate_content()

    provider = vertex_provider(
        location="europe-west1",
        base_url="https://vpce.vertex.internal",
        transport=vertex_transport(handler),
    )
    await provider.complete(REQUEST)
    assert captured["url"] == (
        "https://vpce.vertex.internal/v1/projects/swarm-test/locations/europe-west1"
        f"/publishers/google/models/{DEFAULT_MODEL}:generateContent"
    )


@pytest.mark.asyncio
async def test_location_selects_regional_host(monkeypatch, no_extra_providers):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return completed_generate_content()

    monkeypatch.setenv("VERTEX_API_KEY", "vertex-secret")
    monkeypatch.setenv("VERTEX_PROJECT", VERTEX_PROJECT)
    monkeypatch.setenv("VERTEX_LOCATION", "us-west1")
    provider = VertexAIModelProvider(transport=vertex_transport(handler))
    await provider.complete(REQUEST)
    assert captured["url"].startswith("https://us-west1-aiplatform.googleapis.com/")
    assert "/locations/us-west1/" in captured["url"]


def test_vertex_health_status_is_truthful_and_does_not_expose_key(monkeypatch, no_extra_providers):
    status = vertex_status()
    assert status == {
        "configured": False,
        "model": DEFAULT_MODEL,
        "project": None,
        "location": VERTEX_LOCATION,
        "base_url": VERTEX_BASE_URL,
        "provider": "vertex",
        "fallback": False,
    }
    opt_in_vertex(monkeypatch, VERTEX_API_KEY="vertex-secret",
                  VERTEX_MODEL="gemini-2.5-flash", VERTEX_LOCATION="us-west1")
    configured = vertex_status()
    assert configured["configured"] is True
    assert configured["model"] == "gemini-2.5-flash"
    assert configured["project"] == VERTEX_PROJECT
    assert configured["location"] == "us-west1"
    assert configured["base_url"] == default_vertex_base_url("us-west1")
    assert configured["fallback"] is False
    dumped = json.dumps(configured)
    assert "vertex-secret" not in dumped


def test_build_model_provider_openai_only_ignores_unconfigured_vertex(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = build_model_provider()
    assert isinstance(provider, OpenAIResponsesModelProvider)
    assert not isinstance(provider, FailoverModelProvider)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai"]


def test_build_router_registers_vertex_when_configured(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    opt_in_vertex(monkeypatch)
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "vertex"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "vertex"]


def test_build_router_cloud_plus_vertex_and_ollama(monkeypatch, no_extra_providers):
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
    monkeypatch.setenv("BEDROCK_API_KEY", "bedrock-test")
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "huggingface-test")
    monkeypatch.setenv("CEREBRAS_API_KEY", "cerebras-test")
    monkeypatch.setenv("SAMBANOVA_API_KEY", "sambanova-test")
    opt_in_vertex(monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "mistral", "gemini", "cohere", "deepseek",
        "together", "groq", "fireworks", "azure", "perplexity", "bedrock", "huggingface",
        "cerebras", "sambanova", "vertex", "ollama",
    ]
    controller = build_controller()
    assert [item.provider_id for item in controller.router.providers] == [
        "openai", "openrouter", "xai", "anthropic", "mistral", "gemini", "cohere", "deepseek",
        "together", "groq", "fireworks", "azure", "perplexity", "bedrock", "huggingface",
        "cerebras", "sambanova", "vertex", "ollama",
    ]


def test_build_model_provider_vertex_only(monkeypatch, no_extra_providers):
    opt_in_vertex(monkeypatch)
    monkeypatch.setattr("app.llm.get_api_key", lambda: None)
    primary = OpenAIResponsesModelProvider(api_key="unused")
    monkeypatch.setattr(primary, "configured", lambda: False)
    provider = build_model_provider(primary=primary)
    assert isinstance(provider, VertexAIModelProvider)
    router = build_router(model_provider=provider)
    assert [item.provider_id for item in router.providers] == ["vertex"]


def test_openai_plus_openrouter_still_failover_when_vertex_set(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    opt_in_vertex(monkeypatch)
    stacked = build_model_provider()
    assert isinstance(stacked, FailoverModelProvider)
    assert stacked.primary.provider_id == "openai"
    assert stacked.secondary.provider_id == "openrouter"
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "openrouter", "vertex"]


def test_gemini_and_vertex_are_distinct_catalog_entries(monkeypatch, no_extra_providers):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    opt_in_vertex(monkeypatch)
    router = build_router()
    assert [item.provider_id for item in router.providers] == ["openai", "gemini", "vertex"]
    gemini = next(item for item in router.providers if item.provider_id == "gemini")
    vertex = next(item for item in router.providers if item.provider_id == "vertex")
    assert isinstance(gemini, GeminiModelProvider)
    assert isinstance(vertex, VertexAIModelProvider)


@pytest.mark.asyncio
async def test_router_outage_walks_to_vertex(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    def handler(_request):
        return completed_generate_content(output={"answer": "from vertex"})

    openai = openai_like(error=ProviderError("Could not reach OpenAI", FailureClass.PROVIDER_OUTAGE))
    openrouter = openrouter_like(
        error=ProviderError("Could not reach OpenRouter", FailureClass.PROVIDER_OUTAGE),
    )
    vertex = vertex_provider(transport=vertex_transport(handler))
    router = ModelRouter([openai, openrouter, vertex])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert openai.calls == 1
    assert openrouter.calls == 1
    assert response.provider == "vertex"
    assert response.output == {"answer": "from vertex"}
    assert response.failover_from == "openai"
    assert response.failover_reason == "PROVIDER_OUTAGE"


@pytest.mark.asyncio
async def test_local_only_does_not_select_vertex(no_extra_providers):
    from tests.test_router import openai_like, openrouter_like

    vertex = vertex_provider(transport=vertex_transport(lambda _: completed_generate_content()))
    ollama = OllamaModelProvider(model="llama3.2", transport=vertex_transport(
        lambda _: completed_generate_content()))
    router = ModelRouter([openai_like(), openrouter_like(), vertex, ollama])
    decision = await router.select(CapabilityRequest(privacy="local_only"))
    assert decision.selected.provider_id == "ollama"
    assert all(candidate.provider_id != "vertex" for candidate in decision.chain)


@pytest.mark.asyncio
async def test_unconfigured_vertex_is_skipped_and_cloud_still_serves(no_extra_providers):
    from tests.test_router import openai_like

    vertex = VertexAIModelProvider()
    openai = openai_like(output={"answer": "cloud"})
    router = ModelRouter([openai, vertex])
    response = await router.complete(CapabilityRequest(reasoning="high"), REQUEST)
    assert response.provider == "openai"
    assert openai.calls == 1
    with pytest.raises(ProviderError, match="not configured"):
        await vertex.complete(REQUEST)
