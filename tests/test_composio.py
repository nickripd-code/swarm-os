import asyncio
import json

import httpx
import pytest

from app.composio import AUTHORIZE_TOOL, SEARCH_TOOL, ComposioToolProvider
from app.llm import LLMProvider
from app.models import FailureClass, Mission, MissionAnswer, MissionStatus
from app.runtime import SwarmRuntime
from app.store import Store
from app.tools import CompositeToolProvider, ToolCall, ToolError, build_tool_provider
from app.verifier import local_evidence_check


def composio_transport(handler):
    return httpx.MockTransport(handler)


def test_composio_unconfigured_fails_closed():
    provider = ComposioToolProvider(api_key="")
    assert provider.list_tools() == []


@pytest.mark.asyncio
async def test_composio_unconfigured_requires_authorization():
    provider = ComposioToolProvider(api_key="")
    health = await provider.health()
    assert health.status == "unconfigured"
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "read email"}))
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_search_creates_read_only_session_and_registers_concrete_tools():
    requests = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        requests.append((request, body))
        assert request.headers["x-api-key"] == "test-secret"
        if request.url.path.endswith("/tool_router/session"):
            return httpx.Response(201, json={"session_id": "trs_test"})
        assert request.url.path.endswith("/tool_router/session/trs_test/search")
        return httpx.Response(200, json={
            "results": [{"execution_guidance": "Read the latest matching messages."}],
            "tool_schemas": {
                "GMAIL_FETCH_EMAILS": {
                    "toolkit": "gmail",
                    "tool_slug": "GMAIL_FETCH_EMAILS",
                    "description": "Fetch emails",
                    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                    "output_schema": {"type": "object"},
                },
                "GITHUB_GET_REPOSITORY": {
                    "toolkit": "github",
                    "tool_slug": "GITHUB_GET_REPOSITORY",
                    "description": "Get repository metadata",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                },
            },
            "toolkit_connection_statuses": [{
                "toolkit": "gmail",
                "has_active_connection": False,
                "status_message": "Connect Gmail",
                "accounts": [{"access_token": "must-not-leak"}],
            }],
        })

    provider = ComposioToolProvider(
        api_key="test-secret",
        user_id="user-7",
        toolkits=["gmail", "github"],
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(handler),
    )
    assert [spec.name for spec in provider.list_tools()] == [SEARCH_TOOL, AUTHORIZE_TOOL]
    result = await provider.invoke(ToolCall(
        name=SEARCH_TOOL,
        arguments={"query": "read messages and repository metadata", "max_results": 2},
    ))

    assert result.ok
    assert [item["name"] for item in result.output["tools"]] == [
        "composio.GMAIL_FETCH_EMAILS",
        "composio.GITHUB_GET_REPOSITORY",
    ]
    assert result.output["requires_connection"] == [{"toolkit": "gmail", "status": "Connect Gmail"}]
    assert "must-not-leak" not in json.dumps(result.output)
    assert [spec.name for spec in provider.list_tools()][-2:] == [
        "composio.GMAIL_FETCH_EMAILS",
        "composio.GITHUB_GET_REPOSITORY",
    ]

    session_body = requests[0][1]
    assert session_body["user_id"] == "user-7"
    assert session_body["tags"] == {"enabled": ["readOnlyHint"]}
    assert session_body["toolkits"] == {"enabled": ["gmail", "github"]}
    assert session_body["execute"] == {"enable_multi_execute": False}
    assert requests[1][1] == {
        "queries": [{"use_case": "read messages and repository metadata"}],
        "search_strategy": "tool_search",
    }


@pytest.mark.asyncio
async def test_only_discovered_concrete_tool_can_execute_and_output_is_redacted():
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append(body)
        if request.url.path.endswith("/tool_router/session"):
            return httpx.Response(201, json={"session_id": "trs_test"})
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={
                "tool_schemas": {"one": {
                    "toolkit": "github",
                    "tool_slug": "GITHUB_GET_REPOSITORY",
                    "description": "Get repository",
                    "input_schema": {"type": "object"},
                }},
            })
        return httpx.Response(200, json={
            "data": {"name": "swarm-os", "token": "must-not-leak"},
            "log_id": "log_123",
        })

    provider = ComposioToolProvider(
        api_key="test-secret",
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(handler),
    )
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="composio.GITHUB_DELETE_REPOSITORY", arguments={}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert calls == []

    await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "read repository"}))
    result = await provider.invoke(ToolCall(
        name="composio.GITHUB_GET_REPOSITORY",
        arguments={"owner": "nick", "repo": "swarm-os"},
    ))
    assert result.output == {"data": {"name": "swarm-os"}, "log_id": "log_123"}
    assert calls[-1] == {
        "tool_slug": "GITHUB_GET_REPOSITORY",
        "arguments": {"owner": "nick", "repo": "swarm-os"},
    }


@pytest.mark.asyncio
async def test_authorize_returns_only_user_facing_link():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/tool_router/session"):
            return httpx.Response(201, json={"session_id": "trs_test"})
        assert json.loads(request.content) == {"toolkit": "gmail"}
        return httpx.Response(201, json={
            "link_token": "must-not-leak",
            "redirect_url": "https://app.composio.dev/link/example",
            "connected_account_id": "ca_example",
        })

    provider = ComposioToolProvider(
        api_key="test-secret",
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(handler),
    )
    result = await provider.invoke(ToolCall(name=AUTHORIZE_TOOL, arguments={"toolkit": "gmail"}))
    assert result.output == {
        "toolkit": "gmail",
        "redirect_url": "https://app.composio.dev/link/example",
        "connected_account_id": "ca_example",
        "status": "authorization_required",
    }
    assert "must-not-leak" not in json.dumps(result.output)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,failure", [
    (401, FailureClass.AUTHORIZATION_REQUIRED),
    (403, FailureClass.AUTHORIZATION_REQUIRED),
    (429, FailureClass.RATE_LIMIT),
    (500, FailureClass.PROVIDER_OUTAGE),
    (400, FailureClass.TOOL_FAILURE),
])
async def test_composio_http_failures_are_classified_without_body_leaks(status, failure):
    provider = ComposioToolProvider(
        api_key="test-secret",
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(lambda _: httpx.Response(status, text="server-secret")),
    )
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "read calendar"}))
    assert exc.value.failure_class == failure
    assert "server-secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_composio_timeout_is_classified():
    def timeout(_):
        raise httpx.ReadTimeout("slow and secret")

    provider = ComposioToolProvider(
        api_key="test-secret",
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(timeout),
    )
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "read calendar"}))
    assert exc.value.failure_class == FailureClass.TIMEOUT
    assert "secret" not in str(exc.value)


def _write_search_payload():
    return {
        "tool_schemas": {
            "GITHUB_GET_REPOSITORY": {
                "toolkit": "github",
                "tool_slug": "GITHUB_GET_REPOSITORY",
                "description": "Get repository metadata",
                "annotations": {"readOnlyHint": True},
                "input_schema": {"type": "object"},
            },
            "GITHUB_CREATE_ISSUE": {
                "toolkit": "github",
                "tool_slug": "GITHUB_CREATE_ISSUE",
                "description": "Create an issue",
                "annotations": {"readOnlyHint": True},
                "input_schema": {"type": "object", "properties": {"title": {"type": "string"}}},
            },
            "GITHUB_DELETE_REPOSITORY": {
                "toolkit": "github",
                "tool_slug": "GITHUB_DELETE_REPOSITORY",
                "description": "Delete a repository",
                "annotations": {"readOnlyHint": True, "destructiveHint": True},
                "input_schema": {"type": "object"},
            },
        },
    }


@pytest.mark.asyncio
async def test_unlisted_write_and_destructive_hint_stay_unregistered():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path.endswith("/tool_router/session"):
            body = json.loads(request.content)
            assert body["tags"] == {"enabled": ["readOnlyHint"]}
            return httpx.Response(201, json={"session_id": "trs_test"})
        return httpx.Response(200, json=_write_search_payload())

    provider = ComposioToolProvider(
        api_key="test-secret",
        write_allowlist="",
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(handler),
    )
    result = await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "repository issue"}))
    names = [item["name"] for item in result.output["tools"]]
    assert names == ["composio.GITHUB_GET_REPOSITORY"]
    assert "composio.GITHUB_CREATE_ISSUE" not in [spec.name for spec in provider.list_tools()]
    assert "composio.GITHUB_DELETE_REPOSITORY" not in [spec.name for spec in provider.list_tools()]
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="composio.GITHUB_CREATE_ISSUE", arguments={"title": "seed"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert not any(path.endswith("/execute") for path in calls)


@pytest.mark.asyncio
async def test_allowlisted_write_registers_but_does_not_execute_without_approval():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path.endswith("/tool_router/session"):
            assert json.loads(request.content)["tags"] == {"enabled": ["readOnlyHint"]}
            return httpx.Response(201, json={"session_id": "trs_test"})
        return httpx.Response(200, json=_write_search_payload())

    provider = ComposioToolProvider(
        api_key="test-secret",
        write_allowlist="github:GITHUB_CREATE_ISSUE,not-a-grant",
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(handler),
    )
    result = await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "create an issue"}))
    names = [item["name"] for item in result.output["tools"]]
    assert "composio.GITHUB_GET_REPOSITORY" in names
    assert "composio.GITHUB_CREATE_ISSUE" in names
    assert "composio.GITHUB_DELETE_REPOSITORY" not in names
    spec = next(item for item in provider.list_tools() if item.name == "composio.GITHUB_CREATE_ISSUE")
    assert spec.risk_class == "external_write"
    assert "write" in spec.permissions
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(
            name="composio.GITHUB_CREATE_ISSUE",
            arguments={"title": "seed"},
        ))
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert not any(path.endswith("/execute") for path in calls)


class SearchThenWrite(LLMProvider):
    async def decide(self, state):
        results = state.get("tool_results") or []
        names = [item.get("tool") for item in results]
        if SEARCH_TOOL not in names:
            return {"action": "use_tool", "tool": SEARCH_TOOL, "arguments": {"query": "create an issue"}}
        if "composio.GITHUB_CREATE_ISSUE" not in names:
            return {
                "action": "use_tool",
                "tool": "composio.GITHUB_CREATE_ISSUE",
                "arguments": {"title": "seed"},
            }
        return {"action": "finish", "summary": "Recorded the allowlisted tool result."}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


class DirectWrite(LLMProvider):
    async def decide(self, state):
        del state
        return {
            "action": "use_tool",
            "tool": "composio.GITHUB_CREATE_ISSUE",
            "arguments": {"title": "seed"},
        }

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


def _approval_transport(calls):
    def handler(request: httpx.Request):
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/tool_router/session"):
            return httpx.Response(201, json={"session_id": "trs_test"})
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=_write_search_payload())
        return httpx.Response(200, json={
            "data": {"id": "issue-1", "token": "must-not-leak"},
            "log_id": "log_write",
        })

    return composio_transport(handler)


async def _wait_until_question(store: Store, mission_id, timeout: float = 8) -> Mission:
    async with asyncio.timeout(timeout):
        while True:
            saved = store.get_mission(mission_id)
            if saved and saved.status == MissionStatus.WAITING and saved.pending_question:
                return saved
            if saved and saved.status in {
                MissionStatus.FAILED, MissionStatus.COMPLETED, MissionStatus.STOPPED, MissionStatus.BLOCKED,
            }:
                raise AssertionError(
                    f"mission ended {saved.status} before a pending question: {saved.result}"
                )
            await asyncio.sleep(0.01)


def _execute_count(calls) -> int:
    return sum(1 for path, _body in calls if path.endswith("/execute"))


@pytest.mark.asyncio
async def test_write_without_allowlist_is_policy_refusal_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-secret")
    monkeypatch.delenv("COMPOSIO_WRITE_ALLOWLIST", raising=False)
    calls = []
    provider = ComposioToolProvider(
        api_key="test-secret",
        write_allowlist="",
        base_url="https://composio.test/api/v3.1",
        transport=_approval_transport(calls),
    )
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=DirectWrite(), tools=provider)
    mission = Mission(goal="Do not create an issue")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    assert "not allowlisted" in saved.result["error"]
    assert calls == []
    assert not any(event.event_type == "tool.completed" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_allowlisted_write_parks_for_approval_then_executes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-secret")
    monkeypatch.setenv("COMPOSIO_WRITE_ALLOWLIST", "github:GITHUB_CREATE_ISSUE")
    calls = []
    provider = ComposioToolProvider(
        api_key="test-secret",
        write_allowlist="github:GITHUB_CREATE_ISSUE",
        base_url="https://composio.test/api/v3.1",
        transport=_approval_transport(calls),
    )
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=SearchThenWrite(), tools=provider)
    mission = Mission(
        goal="Create one issue after approval",
        answers=[MissionAnswer(question_id="old", question="Ready?", answer="yes")],
    )
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await _wait_until_question(store, mission.id)
    assert waiting.pending_question.kind == "approval"
    assert waiting.pending_question.approval_action == "composio_write:composio.github_create_issue"
    assert _execute_count(calls) == 0
    events = store.events(mission.id)
    assert any(event.event_type == "mission.question" and event.payload.get("kind") == "approval" for event in events)
    assert any(event.event_type == "mission.waiting" and event.payload.get("kind") == "approval" for event in events)
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "approve")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert _execute_count(calls) == 1
    body = next(payload for path, payload in calls if path.endswith("/execute"))
    assert body["tool_slug"] == "GITHUB_CREATE_ISSUE"
    assert body["arguments"] == {"title": "seed"}
    rendered = json.dumps(runtime.tool_results(mission.id))
    assert "must-not-leak" not in rendered
    assert runtime.tool_results(mission.id)[-1]["output"]["data"]["id"] == "issue-1"


@pytest.mark.asyncio
async def test_allowlisted_write_deny_fails_closed_without_execute(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-secret")
    monkeypatch.setenv("COMPOSIO_WRITE_ALLOWLIST", "github:GITHUB_CREATE_ISSUE")
    calls = []
    provider = ComposioToolProvider(
        api_key="test-secret",
        write_allowlist="github:GITHUB_CREATE_ISSUE",
        base_url="https://composio.test/api/v3.1",
        transport=_approval_transport(calls),
    )
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=SearchThenWrite(), tools=provider)
    mission = Mission(goal="Deny the write")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await _wait_until_question(store, mission.id)
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "deny")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "POLICY_REFUSAL"
    assert "denied" in saved.result["error"].lower()
    assert _execute_count(calls) == 0
    completed = [
        event for event in store.events(mission.id)
        if event.event_type == "tool.completed" and event.payload.get("tool") == "composio.GITHUB_CREATE_ISSUE"
    ]
    assert completed == []
    assert not any(event.event_type == "mission.completed" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_allowlisted_write_ambiguous_answer_does_not_execute(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-secret")
    monkeypatch.setenv("COMPOSIO_WRITE_ALLOWLIST", "github:GITHUB_CREATE_ISSUE")
    calls = []
    provider = ComposioToolProvider(
        api_key="test-secret",
        write_allowlist="github:GITHUB_CREATE_ISSUE",
        base_url="https://composio.test/api/v3.1",
        transport=_approval_transport(calls),
    )
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=SearchThenWrite(), tools=provider)
    mission = Mission(goal="Ambiguous answer is not approval")
    store.save_mission(mission)
    job = asyncio.create_task(runtime.run(mission))
    waiting = await _wait_until_question(store, mission.id)
    await runtime.submit_answer(mission.id, waiting.pending_question.question_id, "ok")
    await asyncio.wait_for(job, 2)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "AUTHORIZATION_REQUIRED"
    assert _execute_count(calls) == 0


def test_build_tool_provider_registers_composio_without_exposing_secret(monkeypatch):
    monkeypatch.delenv("SWARM_LOCAL_TOOLS", raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("SWARM_BROWSER", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.setenv("COMPOSIO_API_KEY", "configured-secret")
    provider = build_tool_provider()
    assert isinstance(provider, CompositeToolProvider) is False
    assert provider.provider_id == "composio"
    rendered = json.dumps([spec.model_dump(mode="json") for spec in provider.list_tools()])
    assert SEARCH_TOOL in rendered
    assert "configured-secret" not in rendered
