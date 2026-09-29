import asyncio
import json

import httpx
import pytest

from app.health import twilio_health_status
from app.llm import LLMProvider
from app.models import FailureClass, Mission, MissionAnswer, MissionStatus
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.tools import ToolCall, ToolError, build_tool_provider, public_tool_data
from app.twilio import SMS_SEND, TwilioSmsToolProvider
from app.verifier import local_evidence_check

SID = "AC11111111111111111111111111111111"
TOKEN = "twilio-auth-token-do-not-leak"
FROM = "+15557654321"
TO = "+15551234567"
QUIET_ENV = (
    "SWARM_LOCAL_TOOLS", "MCP_SERVER_URL", "MCP_API_KEY", "SWARM_BROWSER",
    "SWARM_SELFMOD", "SWARM_SELFMOD_WRITE", "COMPOSIO_API_KEY",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TWILIO_SMS_ALLOWLIST",
)


def _quiet(monkeypatch):
    for key in QUIET_ENV:
        monkeypatch.delenv(key, raising=False)


def _opt_in(monkeypatch, allowlist=TO):
    _quiet(monkeypatch)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", FROM)
    monkeypatch.setenv("TWILIO_SMS_ALLOWLIST", allowlist)


def _message(status="queued", **extra):
    payload = {
        "sid": "SM1234567890abcdef1234567890abcd",
        "account_sid": SID,
        "auth_token": TOKEN,
        "to": TO,
        "from": FROM,
        "status": status,
        "uri": f"/2010-04-01/Accounts/{SID}/Messages/SM1234567890abcdef1234567890abcd.json",
    }
    payload.update(extra)
    return payload


def _transport(calls, *, status_code=201, payload=None, error=None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if error is not None:
            raise error
        return httpx.Response(status_code, json=payload if payload is not None else _message())
    return httpx.MockTransport(handler)


def _assert_no_secrets(blob: str):
    assert SID not in blob
    assert TOKEN not in blob


async def _wait_until_question(store: Store, mission_id, timeout: float = 8) -> Mission:
    async with asyncio.timeout(timeout):
        while True:
            saved = store.get_mission(mission_id)
            if saved and saved.status == MissionStatus.WAITING and saved.pending_question:
                return saved
            if saved and saved.status in {
                MissionStatus.FAILED, MissionStatus.COMPLETED, MissionStatus.STOPPED, MissionStatus.BLOCKED,
            }:
                raise AssertionError(f"mission ended {saved.status} before a pending question: {saved.result}")
            await asyncio.sleep(0.01)


class SmsThenFinish(LLMProvider):
    async def decide(self, state):
        if not (state.get("tool_results") or []):
            return {"action": "use_tool", "tool": SMS_SEND, "arguments": {"to": TO, "body": "hello"}}
        return {"action": "finish", "summary": "The answer is a short text-only result."}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


@pytest.mark.asyncio
async def test_partial_env_leaves_sms_send_missing(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", FROM)
    calls = []
    provider = TwilioSmsToolProvider(transport=_transport(calls))
    assert provider.configured() is False
    assert build_tool_provider() is None
    assert provider.list_tools() == []
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SMS_SEND, arguments={"to": TO, "body": "hello"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert calls == []


@pytest.mark.asyncio
async def test_unconfigured_runtime_sms_send_is_tool_missing(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", SID)
    calls = []
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsToolProvider(transport=_transport(calls)))
    mission = Mission(goal="No partial Twilio")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SMS_SEND, {"to": TO, "body": "hello"})
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert calls == []
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(event.event_type == "tool.started" for event in store.events(mission.id))
    assert not any(event.event_type == "mission.question" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_destination_outside_allowlist_refuses_before_network(tmp_path, monkeypatch):
    _opt_in(monkeypatch)
    calls = []
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsToolProvider(transport=_transport(calls)))
    mission = Mission(goal="Blocked destination")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SMS_SEND, {"to": "+15551234568", "body": "hello"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert calls == []
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(event.event_type == "mission.waiting" for event in store.events(mission.id))
    with pytest.raises(PolicyError):
        await runtime.invoke_tool(mission, SMS_SEND, {"to": ["+15551234567"], "body": "blast"})
    assert calls == []


@pytest.mark.asyncio
async def test_local_only_refuses_twilio_before_network(tmp_path, monkeypatch):
    _opt_in(monkeypatch)
    calls = []
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsToolProvider(transport=_transport(calls)))
    mission = Mission(goal="Stay local", privacy="local_only")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SMS_SEND, {"to": TO, "body": "hello"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(exc.value)
    assert calls == []
    assert not any(event.event_type == "mission.question" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_approve_sends_once_and_prior_approve_does_not_cover_the_next(tmp_path, monkeypatch):
    _opt_in(monkeypatch)
    calls = []
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsToolProvider(transport=_transport(calls)))
    mission = Mission(
        goal="Send twice",
        answers=[MissionAnswer(
            question_id="old-approval",
            question="Approve sending this SMS? Reply approve or deny.",
            answer="approve",
            kind="approval",
            approval_action="sms.send",
        )],
    )
    store.save_mission(mission)
    first = asyncio.create_task(runtime.invoke_tool(mission, SMS_SEND, {"to": TO, "body": "one"}))
    waiting = await _wait_until_question(store, mission.id)
    assert waiting.pending_question.kind == "approval"
    assert waiting.pending_question.approval_action == "sms.send"
    assert waiting.pending_question.question_id != "old-approval"
    assert calls == []
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "approve")
    result = await asyncio.wait_for(first, 2)
    assert result["ok"] is True
    assert result["output"]["message_sid"].startswith("SM")
    assert len(calls) == 1
    assert calls[0].method == "POST"
    encoded = calls[0].content.decode()
    assert f"To={TO.replace('+', '%2B')}" in encoded or f"To={TO}" in encoded
    assert TOKEN not in encoded
    _assert_no_secrets(json.dumps(result))

    second = asyncio.create_task(runtime.invoke_tool(mission, SMS_SEND, {"to": TO, "body": "two"}))
    waiting_again = await _wait_until_question(store, mission.id)
    assert waiting_again.pending_question.question_id != waiting.pending_question.question_id
    assert waiting_again.pending_question.approval_action == "sms.send"
    assert len(calls) == 1
    await runtime.submit_answer(mission.id, waiting_again.pending_question.question_id, "approve")
    await asyncio.wait_for(second, 2)
    assert len(calls) == 2
    blob = json.dumps([event.payload for event in store.events(mission.id)], default=str)
    _assert_no_secrets(blob)
    assert runtime.tool_calls_used(mission.id) == 2


@pytest.mark.asyncio
async def test_deny_and_ambiguous_do_not_send(tmp_path, monkeypatch):
    _opt_in(monkeypatch)
    calls = []
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=TwilioSmsToolProvider(transport=_transport(calls)))
    mission = Mission(goal="Deny the SMS")
    store.save_mission(mission)
    denied = asyncio.create_task(runtime.invoke_tool(mission, SMS_SEND, {"to": TO, "body": "nope"}))
    waiting = await _wait_until_question(store, mission.id)
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "deny")
    with pytest.raises(PolicyError) as exc:
        await asyncio.wait_for(denied, 2)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert calls == []
    assert not any(event.event_type == "tool.started" for event in store.events(mission.id))

    ambiguous = asyncio.create_task(runtime.invoke_tool(mission, SMS_SEND, {"to": TO, "body": "maybe"}))
    waiting_again = await _wait_until_question(store, mission.id)
    await runtime.submit_answer(mission.id, waiting_again.pending_question.question_id, "ok")
    with pytest.raises(PolicyError) as unclear:
        await asyncio.wait_for(ambiguous, 2)
    assert unclear.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert calls == []


@pytest.mark.asyncio
async def test_controller_use_tool_parks_until_sms_approval(tmp_path, monkeypatch):
    _opt_in(monkeypatch)
    calls = []
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        controller=SmsThenFinish(),
        tools=TwilioSmsToolProvider(transport=_transport(calls)),
    )
    mission = Mission(goal="Controller sends one SMS")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await _wait_until_question(store, mission.id)
    assert calls == []
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "yes")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert len(calls) == 1
    assert any(event.event_type == "tool.completed" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_provider_strips_credentials_and_classifies_transport(monkeypatch):
    _opt_in(monkeypatch)
    calls = []
    provider = TwilioSmsToolProvider(transport=_transport(calls, payload=_message(status=f"queued {TOKEN}")))
    result = await provider.invoke(ToolCall(name=SMS_SEND, arguments={"to": TO, "body": "hello"}))
    _assert_no_secrets(json.dumps(result.model_dump(mode="json")))
    assert result.output["status"] == "queued [redacted]"
    assert "voice" not in [spec.name for spec in provider.list_tools()]
    assert [spec.name for spec in build_tool_provider().list_tools()] == [SMS_SEND]

    for status_code, failure in (
        (401, FailureClass.AUTHORIZATION_REQUIRED),
        (429, FailureClass.RATE_LIMIT),
        (503, FailureClass.PROVIDER_OUTAGE),
    ):
        classified = TwilioSmsToolProvider(transport=_transport([], status_code=status_code, payload={"message": TOKEN, "account_sid": SID}))
        with pytest.raises(ToolError) as exc:
            await classified.invoke(ToolCall(name=SMS_SEND, arguments={"to": TO, "body": "hello"}))
        assert exc.value.failure_class == failure
        _assert_no_secrets(str(exc.value))

    timed_out = TwilioSmsToolProvider(transport=_transport([], error=httpx.ReadTimeout("timed out")))
    with pytest.raises(ToolError) as timeout:
        await timed_out.invoke(ToolCall(name=SMS_SEND, arguments={"to": TO, "body": "hello"}))
    assert timeout.value.failure_class == FailureClass.TIMEOUT
    offline = TwilioSmsToolProvider(transport=_transport([], error=httpx.ConnectError("offline")))
    with pytest.raises(ToolError) as outage:
        await offline.invoke(ToolCall(name=SMS_SEND, arguments={"to": TO, "body": "hello"}))
    assert outage.value.failure_class == FailureClass.PROVIDER_OUTAGE
    _assert_no_secrets(str(timeout.value) + str(outage.value))


@pytest.mark.asyncio
async def test_health_and_public_tool_data_omit_twilio_secrets(monkeypatch):
    _quiet(monkeypatch)
    status = await twilio_health_status()
    assert status["configured"] is False
    assert status["status"] == "unconfigured"
    assert status["voice"] is False
    _opt_in(monkeypatch)
    status = await twilio_health_status()
    assert status["configured"] is True
    assert status["tools"] == [SMS_SEND]
    assert status["voice"] is False
    _assert_no_secrets(json.dumps(status))
    cleaned = public_tool_data({"account_sid": SID, "auth_token": TOKEN, "message_sid": "SM123", "ok": True})
    assert cleaned == {"message_sid": "SM123", "ok": True}
