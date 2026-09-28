import json

import httpx
import pytest

from app.exa import CONTENTS_TOOL, SEARCH_TOOL, ExaToolProvider
from app.health import exa_health_status
from app.models import FailureClass, Mission
from app.policy import PolicyError, PolicyGate, PolicyRequest, tool_is_dangerous, tool_is_opted_in_exa
from app.runtime import SwarmRuntime
from app.store import Store
from app.tools import ToolCall, ToolError, build_tool_provider


def exa_transport(handler):
    return httpx.MockTransport(handler)


def _clear_tool_env(monkeypatch):
    for name in (
        "SWARM_LOCAL_TOOLS", "MCP_SERVER_URL", "MCP_API_KEY", "SWARM_BROWSER",
        "SWARM_SELFMOD", "SWARM_SELFMOD_WRITE", "COMPOSIO_API_KEY", "EXA_API_KEY",
        "EXA_BASE_URL", "EXA_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_base_url_alone_does_not_opt_in(monkeypatch):
    _clear_tool_env(monkeypatch)
    monkeypatch.setenv("EXA_BASE_URL", "https://exa.example")
    monkeypatch.setenv("EXA_MODEL", "exa-research")
    provider = ExaToolProvider()
    assert provider.configured() is False
    assert provider.list_tools() == []
    assert not tool_is_opted_in_exa(SEARCH_TOOL)
    assert build_tool_provider() is None


@pytest.mark.asyncio
async def test_unconfigured_exa_is_missing(monkeypatch):
    _clear_tool_env(monkeypatch)
    provider = ExaToolProvider(api_key="")
    health = await provider.health()
    assert health.status == "unconfigured"
    assert health.tools == []
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "swarm os"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    status = await exa_health_status()
    assert status["configured"] is False
    assert status["status"] == "unconfigured"
    assert status["fallback"] is False
    assert "EXA_API_KEY" in status["detail"]


@pytest.mark.asyncio
async def test_search_keeps_source_urls_and_strips_secrets():
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["key"] = request.headers["x-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "requestId": "req-1",
            "api_key": "must-not-leak",
            "results": [
                {
                    "url": "https://user:secret@docs.example/guide",
                    "title": "Guide",
                    "text": "provider text",
                    "publishedDate": "2026-01-02",
                    "author": "Ada",
                    "score": 0.5,
                    "token": "must-not-leak",
                },
                {"url": "https://notes.example/only-url", "title": "URL only"},
                {"title": "No source", "text": "invented page"},
                "not-a-result",
            ],
        })

    provider = ExaToolProvider(
        api_key="exa-secret",
        base_url="https://exa.test",
        transport=exa_transport(handler),
    )
    assert [spec.name for spec in provider.list_tools()] == [SEARCH_TOOL, CONTENTS_TOOL]
    assert "execute" not in json.dumps([spec.name for spec in provider.list_tools()])
    result = await provider.invoke(ToolCall(
        name=SEARCH_TOOL,
        arguments={"query": "swarm policy", "num_results": 3},
    ))

    assert seen["path"] == "/search"
    assert seen["key"] == "exa-secret"
    assert seen["body"]["query"] == "swarm policy"
    assert seen["body"]["numResults"] == 3
    assert result.ok
    assert result.output["results"] == [{
        "url": "https://docs.example/guide",
        "title": "Guide",
        "text": "provider text",
        "published_date": "2026-01-02",
        "author": "Ada",
        "score": 0.5,
    }, {
        "url": "https://notes.example/only-url",
        "title": "URL only",
    }]
    rendered = json.dumps(result.output)
    assert "must-not-leak" not in rendered
    assert "secret" not in rendered
    assert "invented page" not in rendered
    assert "https://example.com" not in rendered


@pytest.mark.asyncio
async def test_search_without_source_urls_fails_closed():
    def handler(_):
        return httpx.Response(200, json={"results": [{"title": "Untitled", "text": "no url"}]})

    provider = ExaToolProvider(api_key="exa-secret", base_url="https://exa.test", transport=exa_transport(handler))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "sources"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert "no url" not in str(exc.value)


@pytest.mark.asyncio
async def test_contents_returns_only_provider_text_for_requested_urls():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert body["urls"] == ["https://docs.example/guide"]
        return httpx.Response(200, json={"results": [{
            "url": "https://docs.example/guide",
            "text": "extracted by driver",
            "password": "must-not-leak",
        }]})

    provider = ExaToolProvider(api_key="exa-secret", base_url="https://exa.test", transport=exa_transport(handler))
    result = await provider.invoke(ToolCall(
        name=CONTENTS_TOOL,
        arguments={"urls": ["https://docs.example/guide"]},
    ))
    assert result.output["results"] == [{
        "url": "https://docs.example/guide",
        "text": "extracted by driver",
    }]
    assert "must-not-leak" not in json.dumps(result.output)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=CONTENTS_TOOL, arguments={"urls": ["file:///etc/passwd"]}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE


@pytest.mark.asyncio
async def test_unknown_exa_name_is_missing():
    provider = ExaToolProvider(api_key="exa-secret", base_url="https://exa.test", transport=exa_transport(lambda _: None))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="exa.execute", arguments={"query": "nope"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
@pytest.mark.parametrize("status,failure", [
    (401, FailureClass.AUTHORIZATION_REQUIRED),
    (403, FailureClass.AUTHORIZATION_REQUIRED),
    (429, FailureClass.RATE_LIMIT),
    (500, FailureClass.PROVIDER_OUTAGE),
    (400, FailureClass.TOOL_FAILURE),
])
async def test_exa_http_failures_are_classified_without_body_leaks(status, failure):
    provider = ExaToolProvider(
        api_key="exa-secret",
        base_url="https://exa.test",
        transport=exa_transport(lambda _: httpx.Response(status, text="server-secret")),
    )
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "status"}))
    assert exc.value.failure_class == failure
    assert "server-secret" not in str(exc.value)
    assert "exa-secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_exa_timeout_and_outage_are_classified():
    def timeout(_):
        raise httpx.ReadTimeout("slow secret")

    def outage(_):
        raise httpx.ConnectError("down secret")

    timeout_provider = ExaToolProvider(
        api_key="exa-secret",
        base_url="https://exa.test",
        transport=exa_transport(timeout),
    )
    with pytest.raises(ToolError) as exc:
        await timeout_provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "slow"}))
    assert exc.value.failure_class == FailureClass.TIMEOUT
    assert "secret" not in str(exc.value)

    outage_provider = ExaToolProvider(
        api_key="exa-secret",
        base_url="https://exa.test",
        transport=exa_transport(outage),
    )
    with pytest.raises(ToolError) as down:
        await outage_provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "down"}))
    assert down.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert "secret" not in str(down.value)


def test_policy_requires_key_and_local_only_refuses(monkeypatch):
    _clear_tool_env(monkeypatch)
    gate = PolicyGate()
    cloud = Mission(goal="cloud")
    local = Mission(goal="private", privacy="local_only")
    assert tool_is_dangerous(SEARCH_TOOL)
    assert not tool_is_opted_in_exa(SEARCH_TOOL)
    with pytest.raises(PolicyError) as denied:
        gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool=SEARCH_TOOL))
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL

    monkeypatch.setenv("EXA_BASE_URL", "https://exa.example")
    assert not tool_is_opted_in_exa(CONTENTS_TOOL)
    monkeypatch.setenv("EXA_API_KEY", "configured")
    assert tool_is_opted_in_exa(SEARCH_TOOL)
    gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool=SEARCH_TOOL))
    gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool=CONTENTS_TOOL))
    with pytest.raises(PolicyError) as local_denied:
        gate.authorize(PolicyRequest(action="tool_use", mission=local, tool=SEARCH_TOOL))
    assert local_denied.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(local_denied.value)


def test_build_tool_provider_registers_exa_without_secret(monkeypatch):
    _clear_tool_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", "configured-secret")
    monkeypatch.setenv("EXA_BASE_URL", "https://exa.example")
    provider = build_tool_provider()
    assert provider.provider_id == "exa"
    names = [spec.name for spec in provider.list_tools()]
    assert names == [SEARCH_TOOL, CONTENTS_TOOL]
    rendered = json.dumps([spec.model_dump(mode="json") for spec in provider.list_tools()])
    assert "configured-secret" not in rendered
    assert "exa.execute" not in rendered


@pytest.mark.asyncio
async def test_health_configured_omits_secret(monkeypatch):
    _clear_tool_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", "configured-secret")
    status = await exa_health_status()
    assert status["configured"] is True
    assert status["status"] == "healthy"
    assert status["tools"] == [SEARCH_TOOL, CONTENTS_TOOL]
    assert "configured-secret" not in json.dumps(status)
    from app.main import health
    payload = await health()
    assert payload["exa"]["provider"] == "exa"
    assert "configured-secret" not in json.dumps(payload["exa"])


@pytest.mark.asyncio
async def test_runtime_search_records_source_url(tmp_path, monkeypatch):
    _clear_tool_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", "configured-secret")

    def handler(_):
        return httpx.Response(200, json={"results": [{
            "url": "https://docs.example/evidence",
            "text": "from the driver",
        }]})

    store = Store(str(tmp_path / "swarm.db"))
    provider = ExaToolProvider(api_key="configured-secret", base_url="https://exa.test", transport=exa_transport(handler))
    runtime = SwarmRuntime(store, tools=provider)
    mission = Mission(goal="Find a source")
    store.save_mission(mission)
    result = await runtime.invoke_tool(mission, SEARCH_TOOL, {"query": "evidence"})
    assert result["ok"] is True
    assert result["output"]["results"][0]["url"] == "https://docs.example/evidence"
    assert result["output"]["results"][0]["text"] == "from the driver"
    events = store.events(mission.id)
    assert any(event.event_type == "tool.started" for event in events)
    assert any(event.event_type == "tool.completed" for event in events)
    assert runtime.tool_calls_used(mission.id) == 1
    rendered = json.dumps(result)
    assert "configured-secret" not in rendered

    private = Mission(goal="Stay local", privacy="local_only")
    store.save_mission(private)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(private, SEARCH_TOOL, {"query": "evidence"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(private.id) == 0
