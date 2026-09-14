import json
import httpx
import pytest

from app.llm import OpenAIProvider, ProviderError
from app.models import FailureClass


@pytest.mark.asyncio
async def test_responses_uses_high_reasoning_and_records_real_usage():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-astra"
        assert body["reasoning"] == {"effort": "high"}
        assert body["text"]["format"]["strict"] is True
        assert body["store"] is False
        assert "Authorization" in request.headers
        return httpx.Response(200, json={"id": "resp_test", "status": "completed", "model": "gpt-6-astra",
            "output": [{"type": "reasoning", "summary": []}, {"type": "message", "content": [
                {"type": "output_text", "text": json.dumps({"status": "completed", "finding": "The answer is 42", "limitations": []})}]}],
            "usage": {"input_tokens": 100, "output_tokens": 200, "output_tokens_details": {"reasoning_tokens": 150}}})
    provider = OpenAIProvider(api_key="test-secret", transport=httpx.MockTransport(handler))
    result = await provider.work({"goal": "Analyze"}, {"role": "analyst"})
    assert result["finding"] == "The answer is 42"
    assert result["_meta"]["reasoning_tokens"] == 150
    assert "test-secret" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected,failure_class", [
    (httpx.Response(401, json={"error": {"message": "secret-should-never-be-logged"}}),
     "rejected the API key", FailureClass.AUTHORIZATION_REQUIRED),
    (httpx.Response(429, json={"error": {}}), "quota or rate limit", FailureClass.RATE_LIMIT),
    (httpx.Response(503, json={"error": {}}), "HTTP 503", FailureClass.PROVIDER_OUTAGE),
    (httpx.Response(200, json={"status": "incomplete", "output": []}),
     "incomplete", FailureClass.CONTEXT_LIMIT),
    (httpx.Response(200, json={"status": "completed", "output": []}),
     "invalid structured", FailureClass.INVALID_OUTPUT),
    (httpx.Response(200, json={"status": "completed", "output": [
        {"content": [{"type": "refusal", "refusal": "no"}]}]}),
     "declined", FailureClass.POLICY_REFUSAL),
])
async def test_provider_errors_are_explicit_and_do_not_leak(response, expected, failure_class):
    provider = OpenAIProvider(api_key="test-secret", transport=httpx.MockTransport(lambda _: response))
    with pytest.raises(ProviderError, match=expected) as error:
        await provider.decide({"goal": "test"})
    assert "secret" not in str(error.value)
    assert error.value.failure_class == failure_class


@pytest.mark.asyncio
async def test_provider_timeout_and_outage_are_classified():
    timeout_provider = OpenAIProvider(
        api_key="test-secret",
        transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))))
    with pytest.raises(ProviderError, match="timed out") as timeout_error:
        await timeout_provider.decide({"goal": "test"})
    assert timeout_error.value.failure_class == FailureClass.TIMEOUT

    outage_provider = OpenAIProvider(
        api_key="test-secret",
        transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderError, match="Could not reach OpenAI") as outage_error:
        await outage_provider.decide({"goal": "test"})
    assert outage_error.value.failure_class == FailureClass.PROVIDER_OUTAGE
