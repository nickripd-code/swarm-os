import json

import httpx
import pytest

from app.llm import OpenAIResponsesModelProvider, OpenRouterModelProvider, ProviderError
from app.models import FailureClass
from app.providers import ModelProvider, ModelRequest


def completed_response():
    return httpx.Response(200, json={
        "id": "resp_contract",
        "status": "completed",
        "model": "gpt-6-astra",
        "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"answer": "ok"})},
        ]}],
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    })


def completed_chat(output=None):
    return httpx.Response(200, json={
        "id": "or_contract",
        "model": "openai/gpt-4o",
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


REQUEST = ModelRequest(
    model="gpt-6-astra",
    instructions="Return JSON",
    input={"question": "test"},
    response_format={"type": "json_schema", "name": "answer", "strict": True,
                     "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                "required": ["answer"], "additionalProperties": False}},
    reasoning_effort="high",
    max_output_tokens=100,
)


@pytest.mark.asyncio
async def test_openai_adapter_implements_provider_contract_and_tracks_usage():
    provider = OpenAIResponsesModelProvider(
        api_key="test-secret",
        transport=httpx.MockTransport(lambda _: completed_response()),
    )
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert [m.model for m in models] == ["gpt-6-astra"]
    assert models[0].provider == "openai"
    assert models[0].capabilities.structured_outputs is True
    assert models[0].context_limits.context_tokens is None

    response = await provider.complete(REQUEST)
    assert response.output == {"answer": "ok"}
    assert response.provider == "openai"
    assert response.usage.reasoning_tokens == 3
    assert provider.usage().model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 3,
    }
    assert (await provider.health()).status == "healthy"
    assert provider.estimate_cost(REQUEST).known is False


@pytest.mark.asyncio
async def test_openrouter_adapter_implements_provider_contract_and_tracks_usage():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["authorization"] = request.headers["Authorization"]
        return completed_chat()

    provider = OpenRouterModelProvider(
        api_key="or-secret",
        transport=httpx.MockTransport(handler),
    )
    assert isinstance(provider, ModelProvider)
    models = await provider.list_models()
    assert models[0].provider == "openrouter"
    assert models[0].model == "openai/gpt-4o"

    request = REQUEST.model_copy(update={"model": "openai/gpt-4o"})
    response = await provider.complete(request)
    assert response.output == {"answer": "ok"}
    assert response.provider == "openrouter"
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 3,
    }
    assert captured["url"].endswith("/chat/completions")
    assert captured["authorization"] == "Bearer or-secret"
    assert captured["body"]["model"] == "openai/gpt-4o"
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert "json_schema" in captured["body"]["response_format"]
    assert captured["body"]["provider"] == {"require_parameters": True}
    assert "or-secret" not in json.dumps(response.model_dump())
    assert (await provider.health()).status == "healthy"


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(401, json={"error": {"message": "or-secret"}}),
     "rejected the API key", FailureClass.AUTHORIZATION_REQUIRED),
    (httpx.Response(429, json={"error": {}}), "quota or rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={"error": {}}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
     "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (httpx.Response(200, json={"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}),
     "declined", FailureClass.POLICY_REFUSAL),
])
async def test_openrouter_errors_are_classified_and_do_not_leak(response, expected, failure_class):
    provider = OpenRouterModelProvider(
        api_key="or-secret",
        transport=httpx.MockTransport(lambda _: response),
    )
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.complete(REQUEST.model_copy(update={"model": "openai/gpt-4o"}))
    assert "or-secret" not in str(error.value)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_openrouter_timeout_and_outage_are_classified():
    timeout_provider = OpenRouterModelProvider(
        api_key="or-secret",
        transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.complete(REQUEST)
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = OpenRouterModelProvider(
        api_key="or-secret",
        transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach OpenRouter") as outage_error:
        await outage_provider.complete(REQUEST)
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_default_stream_fails_explicitly_instead_of_faking_streaming():
    provider = OpenAIResponsesModelProvider(api_key="test-secret")
    request = ModelRequest(model="gpt-6-astra", instructions="x", input="x")
    with pytest.raises(ProviderError) as error:
        await anext(provider.stream(request))
    assert error.value.failure_class == FailureClass.CAPABILITY_MISMATCH
