import json

import httpx
import pytest

from app.composio import AUTHORIZE_TOOL, SEARCH_TOOL, ComposioToolProvider, github_slug_is_mutating
from app.models import FailureClass
from app.tools import CompositeToolProvider, ToolCall, ToolError, build_tool_provider


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


def test_github_read_slugs_stay_distinct_from_writes():
    assert github_slug_is_mutating("GITHUB_GET_REPOSITORY", "github") is False
    assert github_slug_is_mutating("GITHUB_GET_A_COMMIT", "github") is False
    assert github_slug_is_mutating("GITHUB_LIST_COMMITS", "github") is False
    assert github_slug_is_mutating("GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS", "github") is True
    assert github_slug_is_mutating("GITHUB_CREATE_A_PULL_REQUEST", "github") is True
    assert github_slug_is_mutating("GMAIL_FETCH_EMAILS", "gmail") is False


@pytest.mark.asyncio
async def test_github_write_schema_is_not_registered_or_executed():
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("/tool_router/session"):
            return httpx.Response(201, json={"session_id": "trs_test"})
        return httpx.Response(200, json={
            "tool_schemas": {
                "write": {
                    "toolkit": "github",
                    "tool_slug": "GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS",
                    "description": "Write a file",
                    "tags": ["readOnlyHint"],
                },
                "read": {
                    "toolkit": "github",
                    "tool_slug": "GITHUB_GET_A_COMMIT",
                    "description": "Read a commit",
                },
                "marked": {
                    "toolkit": "gmail",
                    "tool_slug": "GMAIL_SEND_EMAIL",
                    "description": "Send mail",
                    "annotations": {"destructiveHint": True},
                },
            },
        })

    provider = ComposioToolProvider(
        api_key="test-secret",
        base_url="https://composio.test/api/v3.1",
        transport=composio_transport(handler),
    )
    result = await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "read a commit"}))
    assert [item["name"] for item in result.output["tools"]] == ["composio.GITHUB_GET_A_COMMIT"]
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(
            name="composio.GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS",
            arguments={"path": "app/main.py", "content": "x"},
        ))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert all(not path.endswith("/execute") for path, _body in calls)


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
