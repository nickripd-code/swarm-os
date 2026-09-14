import json

import httpx
import pytest

from app.llm import OpenAIResponsesModelProvider, ProviderError
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

    request = ModelRequest(
        model="gpt-6-astra",
        instructions="Return JSON",
        input={"question": "test"},
        response_format={"type": "json_schema", "name": "answer", "strict": True,
                         "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                    "required": ["answer"], "additionalProperties": False}},
        reasoning_effort="high",
        max_output_tokens=100,
    )
    response = await provider.complete(request)
    assert response.output == {"answer": "ok"}
    assert response.provider == "openai"
    assert response.usage.reasoning_tokens == 3
    assert provider.usage().model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 3,
    }
    assert (await provider.health()).status == "healthy"
    assert provider.estimate_cost(request).known is False


@pytest.mark.asyncio
async def test_default_stream_fails_explicitly_instead_of_faking_streaming():
    provider = OpenAIResponsesModelProvider(api_key="test-secret")
    request = ModelRequest(model="gpt-6-astra", instructions="x", input="x")
    with pytest.raises(ProviderError) as error:
        await anext(provider.stream(request))
    assert error.value.failure_class == FailureClass.CAPABILITY_MISMATCH
