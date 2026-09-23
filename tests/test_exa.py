import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.exa import CONTENTS_TOOL, SEARCH_TOOL, SEARCH_WEB_TOOL, ExaToolProvider
from app.health import exa_health_status
from app.models import FailureClass, Mission
from app.policy import OPTED_IN_EXA_TOOLS, PolicyError, PolicyGate, PolicyRequest, tool_is_opted_in_exa
from app.runtime import SwarmRuntime
from app.store import Store
from app.tools import ToolCall, ToolError, build_tool_provider

SECRET = "exa-test-secret"


def _clear_tool_env(monkeypatch):
    for name in (
        "SWARM_LOCAL_TOOLS", "MCP_SERVER_URL", "MCP_API_KEY", "SWARM_BROWSER",
        "SWARM_SELFMOD", "SWARM_SELFMOD_WRITE", "COMPOSIO_API_KEY",
        "EXA_API_KEY", "SWARM_EXA", "EXA_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _transport(handler):
    return httpx.MockTransport(handler)


def _provider(handler, **kwargs):
    return ExaToolProvider(
        api_key=kwargs.pop("api_key", SECRET),
        base_url=kwargs.pop("base_url", "https://exa.test"),
        transport=_transport(handler),
        **kwargs,
    )


def test_allowlist_matches_policy():
    assert OPTED_IN_EXA_TOOLS == {SEARCH_TOOL, SEARCH_WEB_TOOL, CONTENTS_TOOL}


@pytest.mark.asyncio
async def test_unconfigured_is_tool_missing_and_lists_nothing():
    provider = ExaToolProvider(api_key="", transport=_transport(lambda request: (_ for _ in ()).throw(AssertionError(request.url))))
    assert provider.list_tools() == []
    health = await provider.health()
    assert health.status == "unconfigured"
    assert health.tools == []
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "evidence"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_search_returns_source_urls_and_strips_secrets():
    seen = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((str(request.url), dict(request.headers), body))
        return httpx.Response(200, json={
            "requestId": "req-1",
            "results": [
                {
                    "title": "Evidence page",
                    "url": "https://example.com/source",
                    "text": "cited fact",
                    "highlights": ["cited fact"],
                    "publishedDate": "2026-01-02",
                    "api_key": SECRET,
                    "nested": {"token": "must-not-leak"},
                },
                {"title": "no url", "text": "invented"},
                {"id": "https://user:pass@example.com/secret", "text": "drop userinfo"},
                {"id": "not-a-url", "text": "drop"},
            ],
        })

    provider = _provider(handler)
    result = await provider.invoke(ToolCall(
        name=SEARCH_TOOL,
        arguments={"query": "cited fact", "num_results": 2, "api_key": SECRET},
    ))
    assert result.ok
    assert result.output["query"] == "cited fact"
    assert result.output["results"] == [{
        "url": "https://example.com/source",
        "title": "Evidence page",
        "text": "cited fact",
        "highlights": ["cited fact"],
        "published_date": "2026-01-02",
    }]
    blob = json.dumps(result.output)
    assert SECRET not in blob
    assert "must-not-leak" not in blob
    assert "invented" not in blob
    url, headers, body = seen[0]
    assert url == "https://exa.test/search"
    assert headers["x-api-key"] == SECRET
    assert body["query"] == "cited fact"
    assert body["numResults"] == 2
    assert SECRET not in json.dumps(body)


@pytest.mark.asyncio
async def test_search_web_alias_and_empty_results_are_not_invented():
    def handler(request: httpx.Request):
        assert request.url.path == "/search"
        return httpx.Response(200, json={"results": []})

    provider = _provider(handler)
    result = await provider.invoke(ToolCall(name=SEARCH_WEB_TOOL, arguments={"query": "nothing"}))
    assert result.output == {"query": "nothing", "results": []}


@pytest.mark.asyncio
async def test_contents_returns_only_real_urls():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert request.url.path == "/contents"
        assert body["urls"] == ["https://example.com/a", "https://example.com/b"]
        assert "contents" not in body
        return httpx.Response(200, json={
            "results": [
                {"url": "https://example.com/a", "text": "page a", "password": "nope"},
            ],
        })

    provider = _provider(handler)
    result = await provider.invoke(ToolCall(
        name=CONTENTS_TOOL,
        arguments={"urls": ["https://example.com/a", "https://example.com/a", "https://example.com/b"]},
    ))
    assert result.output["urls"] == ["https://example.com/a", "https://example.com/b"]
    assert result.output["results"] == [{
        "url": "https://example.com/a",
        "title": "",
        "text": "page a",
        "highlights": [],
    }]
    assert "nope" not in json.dumps(result.output)


@pytest.mark.asyncio
async def test_invalid_contents_urls_do_not_call_network():
    def handler(_request: httpx.Request):
        raise AssertionError("network")

    provider = _provider(handler)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=CONTENTS_TOOL, arguments={"urls": ["file:///etc/passwd"]}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "failure"), [
    (401, FailureClass.AUTHORIZATION_REQUIRED),
    (429, FailureClass.RATE_LIMIT),
    (503, FailureClass.PROVIDER_OUTAGE),
    (400, FailureClass.TOOL_FAILURE),
])
async def test_http_failures_are_classified_without_bodies(status, failure):
    def handler(_request: httpx.Request):
        return httpx.Response(status, json={"error": f"leak {SECRET}", "api_key": SECRET})

    provider = _provider(handler)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "q"}))
    assert exc.value.failure_class == failure
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_and_outage_are_classified():
    def timeout(_request: httpx.Request):
        raise httpx.ReadTimeout(f"slow {SECRET}")

    provider = _provider(timeout)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_TOOL, arguments={"query": "q"}))
    assert exc.value.failure_class == FailureClass.TIMEOUT
    assert SECRET not in str(exc.value)

    def down(_request: httpx.Request):
        raise httpx.ConnectError(f"down {SECRET}")

    provider = _provider(down)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name=SEARCH_WEB_TOOL, arguments={"query": "q"}))
    assert exc.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert SECRET not in str(exc.value)


def test_policy_requires_opt_in_and_local_only_refuses(monkeypatch):
    _clear_tool_env(monkeypatch)
    gate = PolicyGate()
    cloud = Mission(goal="research")
    local = Mission(goal="private", privacy="local_only")
    assert not tool_is_opted_in_exa(SEARCH_TOOL)
    with pytest.raises(PolicyError) as denied:
        gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool=SEARCH_TOOL))
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL

    monkeypatch.setenv("SWARM_EXA", "1")
    assert tool_is_opted_in_exa(SEARCH_WEB_TOOL)
    gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool=SEARCH_WEB_TOOL))
    with pytest.raises(PolicyError) as local_exc:
        gate.authorize(PolicyRequest(action="tool_use", mission=local, tool=CONTENTS_TOOL))
    assert local_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(local_exc.value)
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool="web.search"))
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool="exa.execute"))

    monkeypatch.delenv("SWARM_EXA", raising=False)
    monkeypatch.setenv("EXA_API_KEY", SECRET)
    gate.authorize(PolicyRequest(action="tool_use", mission=cloud, tool=SEARCH_TOOL))


def test_build_tool_provider_registers_exa_without_the_secret(monkeypatch):
    _clear_tool_env(monkeypatch)
    assert build_tool_provider() is None
    monkeypatch.setenv("SWARM_EXA", "1")
    assert build_tool_provider() is None
    monkeypatch.setenv("EXA_API_KEY", SECRET)
    provider = build_tool_provider()
    assert provider.provider_id == "exa"
    names = [spec.name for spec in provider.list_tools()]
    assert names == [SEARCH_TOOL, SEARCH_WEB_TOOL, CONTENTS_TOOL]
    rendered = json.dumps([spec.model_dump(mode="json") for spec in provider.list_tools()])
    assert SECRET not in rendered


@pytest.mark.asyncio
async def test_runtime_invoke_charges_budget_and_emits_events(tmp_path, monkeypatch):
    _clear_tool_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", SECRET)

    def handler(request: httpx.Request):
        return httpx.Response(200, json={
            "results": [{"url": "https://example.com/cite", "text": "fact", "api_key": SECRET}],
        })

    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=_provider(handler))
    mission = Mission(goal="Find a source", limits={"max_tool_calls": 1})
    store.save_mission(mission)
    result = await runtime.invoke_tool(mission, SEARCH_TOOL, {"query": "fact"})
    assert result["ok"] is True
    assert result["used"] == 1
    assert result["output"]["results"][0]["url"] == "https://example.com/cite"
    assert SECRET not in json.dumps(result)
    events = store.events(mission.id)
    assert any(event.event_type == "tool.started" for event in events)
    assert any(event.event_type == "tool.completed" for event in events)
    assert not any(event.event_type == "tool.failed" for event in events)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SEARCH_WEB_TOOL, {"query": "more"}, idempotency_key="exa-2")
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED


@pytest.mark.asyncio
async def test_runtime_local_only_and_unconfigured_fail_before_start(tmp_path, monkeypatch):
    _clear_tool_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", SECRET)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=_provider(lambda _request: httpx.Response(500, json={})))
    mission = Mission(goal="Stay local", privacy="local_only")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, SEARCH_TOOL, {"query": "secret research"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(event.event_type == "tool.started" for event in store.events(mission.id))

    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setenv("SWARM_EXA", "1")
    bare = SwarmRuntime(store, tools=build_tool_provider())
    cloud = Mission(goal="No key")
    store.save_mission(cloud)
    with pytest.raises(PolicyError) as missing:
        await bare.invoke_tool(cloud, SEARCH_TOOL, {"query": "q"})
    assert missing.value.failure_class == FailureClass.TOOL_MISSING
    assert bare.tool_calls_used(cloud.id) == 0
    assert not any(event.event_type == "tool.started" for event in store.events(cloud.id))


@pytest.mark.asyncio
async def test_health_reports_exa_without_secrets(monkeypatch):
    _clear_tool_env(monkeypatch)
    status = await exa_health_status()
    assert status["configured"] is False
    assert status["opt_in"] is False
    assert status["provider"] == "exa"
    assert status["status"] == "unconfigured"
    assert status["tools"] == []
    assert status["fallback"] is False
    monkeypatch.setenv("EXA_API_KEY", SECRET)
    status = await exa_health_status()
    assert status["configured"] is True
    assert status["status"] == "healthy"
    assert status["tools"] == [SEARCH_TOOL, SEARCH_WEB_TOOL, CONTENTS_TOOL]
    assert SECRET not in json.dumps(status)

    from app.main import health
    payload = await health()
    assert payload["exa"]["provider"] == "exa"
    assert SEARCH_TOOL in payload["exa"]["tools"]
    assert SECRET not in json.dumps(payload["exa"])


def test_health_endpoint_hides_the_key(monkeypatch, tmp_path):
    _clear_tool_env(monkeypatch)
    monkeypatch.setenv("EXA_API_KEY", SECRET)
    monkeypatch.setenv("SWARM_DATABASE_PATH", str(tmp_path / "swarm.db"))
    from app.main import app
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["exa"]["configured"] is True
    assert body["exa"]["provider"] == "exa"
    assert SEARCH_WEB_TOOL in body["exa"]["tools"]
    assert SECRET not in response.text
