import asyncio
import json

import httpx
import pytest

from app.health import twilio_health_status
from app.models import FailureClass, Mission, MissionStatus
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.tools import ToolCall, ToolError, build_tool_provider, public_tool_data
from app.twilio import SMS_SEND_TOOL, TwilioSmsProvider, TwilioSmsSettings

ACCOUNT_SID = "AC1234567890abcdef1234567890abcd"
AUTH_TOKEN = "twilio-auth-secret"
FROM_NUMBER = "+15557654321"
ALLOWED = "+15551230000"
BLOCKED = "+15559999999"


def configure_twilio(monkeypatch, allowlist: str = ALLOWED):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", ACCOUNT_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", FROM_NUMBER)
    monkeypatch.setenv("TWILIO_SMS_ALLOWLIST", allowlist)


def clear_twilio(monkeypatch):
    for name in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TWILIO_SMS_ALLOWLIST",
    ):
        monkeypatch.delenv(name, raising=False)


def settings() -> TwilioSmsSettings:
    return TwilioSmsSettings(ACCOUNT_SID, AUTH_TOKEN, FROM_NUMBER, frozenset({ALLOWED}))


def message_response(body: str = "hello") -> dict:
    return {
        "sid": "SM1234567890abcdef1234567890abcd",
        "status": "queued",
        "to": ALLOWED,
        "from": FROM_NUMBER,
        "body": body,
        "account_sid": ACCOUNT_SID,
        "auth_token": AUTH_TOKEN,
        "uri": f"/2010-04-01/Accounts/{ACCOUNT_SID}/Messages/SM1234567890abcdef1234567890abcd.json",
    }


def transport_for(handler, calls: list[httpx.Request]) -> httpx.MockTransport:
    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped)


async def wait_until_question(store: Store, mission_id, timeout: float = 2) -> Mission:
    async with asyncio.timeout(timeout):
        while True:
            saved = store.get_mission(mission_id)
            if saved and saved.status == MissionStatus.WAITING and saved.pending_question:
                return saved
            await asyncio.sleep(0.01)


def assert_no_secrets(blob: str):
    assert AUTH_TOKEN not in blob
    assert ACCOUNT_SID not in blob


@pytest.mark.asyncio
async def test_partial_twilio_env_is_unconfigured(monkeypatch):
    clear_twilio(monkeypatch)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", ACCOUNT_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", FROM_NUMBER)
    provider = TwilioSmsProvider()
    assert provider.configured() is False
    assert provider.list_tools() == []
    health = await provider.health()
    assert health.status == "unconfigured"
    assert_no_secrets(health.model_dump_json())
    status = await twilio_health_status()
    assert status["configured"] is False
    assert status["voice"] is False
    assert_no_secrets(json.dumps(status))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SMS_SEND_TOOL, arguments={"to": ALLOWED, "body": "hi"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_runtime_unconfigured_sms_is_tool_missing(tmp_path, monkeypatch):
    clear_twilio(monkeypatch)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsProvider())
    mission = Mission(goal="No Twilio")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SMS_SEND_TOOL, {"to": ALLOWED, "body": "hi"})
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert runtime.tool_calls_used(mission.id) == 0
    events = store.events(mission.id)
    assert not any(event.event_type == "tool.started" for event in events)
    assert not any(event.event_type == "mission.waiting" for event in events)
    assert_no_secrets(json.dumps([event.model_dump(mode="json") for event in events], default=str))


@pytest.mark.asyncio
async def test_destination_off_allowlist_never_calls_twilio():
    calls: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("network call")

    provider = TwilioSmsProvider(
        settings=settings(),
        transport=transport_for(handler, calls),
        base_url="https://api.twilio.test",
    )
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SMS_SEND_TOOL, arguments={"to": BLOCKED, "body": "hi"}))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert calls == []
    with pytest.raises(ToolError) as blast:
        await provider.invoke(ToolCall(
            name=SMS_SEND_TOOL,
            arguments={"to": ALLOWED, "body": "hi", "media_url": "https://example.test"},
        ))
    assert blast.value.failure_class == FailureClass.POLICY_REFUSAL
    assert calls == []


@pytest.mark.asyncio
async def test_runtime_blocks_not_allowlisted_before_approval(tmp_path, monkeypatch):
    configure_twilio(monkeypatch)
    calls: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("network call")

    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsProvider(transport=transport_for(handler, calls)))
    mission = Mission(goal="Text a stranger")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SMS_SEND_TOOL, {"to": BLOCKED, "body": "hi"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "not allowlisted" in str(exc.value)
    assert calls == []
    assert runtime.tool_calls_used(mission.id) == 0
    events = store.events(mission.id)
    assert not any(event.event_type == "tool.started" for event in events)
    assert not any(event.event_type == "mission.waiting" for event in events)


@pytest.mark.asyncio
async def test_approve_sends_once_and_deny_does_not_send(tmp_path, monkeypatch):
    configure_twilio(monkeypatch)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.twilio.com"
        assert request.url.path == f"/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json"
        assert "Calls" not in request.url.path
        sent = request.content.decode()
        assert f"To={ALLOWED.replace('+', '%2B')}" in sent or f"To={ALLOWED}" in sent
        assert "media" not in sent.lower()
        return httpx.Response(201, json=message_response("hello once"))

    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsProvider(transport=transport_for(handler, calls)))
    mission = Mission(goal="Text an allowlisted number")
    store.save_mission(mission)
    arguments = {"to": ALLOWED, "body": "hello once"}
    job = asyncio.create_task(runtime.invoke_tool(
        mission, SMS_SEND_TOOL, arguments, idempotency_key="sms-1",
    ))
    waiting = await wait_until_question(store, mission.id)
    assert waiting.pending_question.kind == "approval"
    assert waiting.pending_question.approval_action == "sms.send"
    assert calls == []
    assert runtime.tool_calls_used(mission.id) == 0
    events = store.events(mission.id)
    assert any(event.event_type == "mission.waiting" and event.payload.get("kind") == "approval"
               for event in events)
    assert not any(event.event_type == "tool.started" for event in events)

    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "approve")
    result = await asyncio.wait_for(job, 2)
    assert len(calls) == 1
    assert result["ok"] is True
    assert result["output"]["message_sid"].startswith("SM")
    assert result["used"] == 1
    assert "account_sid" not in result["output"]
    assert "auth_token" not in result["output"]
    assert_no_secrets(json.dumps(result))
    replay = await runtime.invoke_tool(
        mission, SMS_SEND_TOOL, arguments, idempotency_key="sms-1",
    )
    assert replay["output"]["message_sid"] == result["output"]["message_sid"]
    assert len(calls) == 1

    second = asyncio.create_task(runtime.invoke_tool(
        mission, SMS_SEND_TOOL, {"to": ALLOWED, "body": "second"}, idempotency_key="sms-2",
    ))
    waiting_again = await wait_until_question(store, mission.id)
    assert len(calls) == 1
    await runtime.submit_answer(mission.id, waiting_again.pending_question.question_id, "deny")
    with pytest.raises(PolicyError) as exc:
        await asyncio.wait_for(second, 2)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert len(calls) == 1
    assert runtime.tool_calls_used(mission.id) == 1
    finished = store.events(mission.id)
    assert_no_secrets(json.dumps([event.model_dump(mode="json") for event in finished], default=str))
    started = [event for event in finished if event.event_type == "tool.started"]
    assert len(started) == 1


@pytest.mark.asyncio
async def test_local_only_refuses_configured_sms(tmp_path, monkeypatch):
    configure_twilio(monkeypatch)
    calls: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("network call")

    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsProvider(transport=transport_for(handler, calls)))
    mission = Mission(goal="Stay local", privacy="local_only")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SMS_SEND_TOOL, {"to": ALLOWED, "body": "hi"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(exc.value)
    assert calls == []
    assert runtime.tool_calls_used(mission.id) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "failure", "body"),
    [
        (401, FailureClass.AUTHORIZATION_REQUIRED, {"message": "bad twilio-auth-secret"}),
        (429, FailureClass.RATE_LIMIT, {"message": "slow down AC1234567890abcdef1234567890abcd"}),
        (503, FailureClass.PROVIDER_OUTAGE, {"message": "down"}),
    ],
)
async def test_twilio_http_failures_are_classified(status, failure, body):
    calls: list[httpx.Request] = []
    provider = TwilioSmsProvider(
        settings=settings(),
        transport=transport_for(lambda _request: httpx.Response(status, json=body), calls),
        base_url="https://api.twilio.test",
    )
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SMS_SEND_TOOL, arguments={"to": ALLOWED, "body": "hi"}))
    assert exc.value.failure_class == failure
    assert_no_secrets(str(exc.value))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_twilio_timeout_and_outage_are_classified():
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out with twilio-auth-secret")

    provider = TwilioSmsProvider(
        settings=settings(),
        transport=httpx.MockTransport(timeout),
        base_url="https://api.twilio.test",
    )
    with pytest.raises(ToolError) as timed:
        await provider.invoke(ToolCall(name=SMS_SEND_TOOL, arguments={"to": ALLOWED, "body": "hi"}))
    assert timed.value.failure_class == FailureClass.TIMEOUT
    assert_no_secrets(str(timed.value))

    def offline(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline AC1234567890abcdef1234567890abcd")

    down = TwilioSmsProvider(
        settings=settings(),
        transport=httpx.MockTransport(offline),
        base_url="https://api.twilio.test",
    )
    with pytest.raises(ToolError) as outage:
        await down.invoke(ToolCall(name=SMS_SEND_TOOL, arguments={"to": ALLOWED, "body": "hi"}))
    assert outage.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert_no_secrets(str(outage.value))


def test_build_tool_provider_registers_sms_without_secrets(monkeypatch):
    clear_twilio(monkeypatch)
    monkeypatch.delenv("SWARM_LOCAL_TOOLS", raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("SWARM_BROWSER", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    configure_twilio(monkeypatch, allowlist="+1 (555) 123-0000")
    provider = build_tool_provider()
    assert provider is not None
    assert provider.provider_id == "twilio"
    rendered = json.dumps([spec.model_dump(mode="json") for spec in provider.list_tools()])
    assert SMS_SEND_TOOL in rendered
    assert_no_secrets(rendered)
    cleaned = public_tool_data({"account_sid": ACCOUNT_SID, "auth_token": AUTH_TOKEN, "status": "queued"})
    assert cleaned == {"status": "queued"}


@pytest.mark.asyncio
async def test_configured_health_hides_credentials(monkeypatch):
    configure_twilio(monkeypatch)
    status = await twilio_health_status()
    assert status["configured"] is True
    assert status["status"] == "healthy"
    assert status["tools"] == [SMS_SEND_TOOL]
    assert status["voice"] is False
    assert_no_secrets(json.dumps(status))
    assert ALLOWED not in json.dumps(status)
    assert FROM_NUMBER not in json.dumps(status)
