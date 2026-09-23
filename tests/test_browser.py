import json

import httpx
import pytest

from app.browser import (
    BrowserDriver, BrowserToolProvider, HttpxStagehandTransport, browser_opted_in,
)
from app.health import browser_health_status
from app.models import FailureClass, Mission
from app.policy import PolicyError, PolicyGate, PolicyRequest, tool_is_dangerous, tool_is_opted_in_browser
from app.runtime import SwarmRuntime
from app.store import Store
from app.tools import ToolCall, ToolError, ToolProvider, build_tool_provider

REMOTE_KEY = "browserbase-test-secret"
REMOTE_PROJECT = "project-test-id"


class FakeBrowserDriver(BrowserDriver):
    def __init__(self, pages=None, fail: Exception | None = None, invalid=None):
        self.calls: list[tuple[str, str | None]] = []
        self._page: dict | None = None
        self._pages = pages or {}
        self._fail = fail
        self._invalid = invalid

    async def navigate(self, url: str) -> dict:
        self.calls.append(("navigate", url))
        if self._fail is not None:
            raise self._fail
        if self._invalid is not None:
            return self._invalid
        page = self._pages.get(url) or {
            "url": url,
            "title": "Example",
            "text": "hello from fake browser",
            "api_key": "must-not-leak",
        }
        self._page = page
        return page

    async def snapshot(self) -> dict:
        self.calls.append(("snapshot", None))
        if self._fail is not None:
            raise self._fail
        if self._page is None:
            raise ToolError("No page is open; navigate first", FailureClass.TOOL_FAILURE)
        return self._page

    async def click(self, selector: str) -> dict:
        self.calls.append(("click", selector))
        if self._fail is not None:
            raise self._fail
        if self._page is None:
            raise ToolError("No page is open; navigate first", FailureClass.TOOL_FAILURE)
        updated = dict(self._page)
        updated["text"] = f"clicked:{selector}"
        self._page = updated
        return updated


def _no_browser_env(monkeypatch):
    monkeypatch.delenv("SWARM_BROWSER", raising=False)
    monkeypatch.delenv("SWARM_BROWSER_REMOTE", raising=False)
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    monkeypatch.delenv("STAGEHAND_BASE_URL", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD_WRITE", raising=False)
    monkeypatch.delenv("SWARM_LOCAL_TOOLS", raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _clear_remote_browser_env(monkeypatch):
    monkeypatch.delenv("SWARM_BROWSER_REMOTE", raising=False)
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    monkeypatch.delenv("STAGEHAND_BASE_URL", raising=False)


def _stagehand_action(method: str, result: dict) -> dict:
    return {
        "success": True,
        "error": None,
        "action": {"method": method, "status": "completed", "error": None, "result": result},
    }


class RemoteScript:
    """In-memory Stagehand v4 responses. Never opens a socket."""

    def __init__(self, *, status_code: int = 200, fail: Exception | None = None, goto_ok: bool = True,
                 page_url: str = "https://user:secret@example.com/page", text: str | None = None):
        self.status_code = status_code
        self.fail = fail
        self.goto_ok = goto_ok
        self.page_url = page_url
        self.text = text if text is not None else f"hello {REMOTE_KEY} {REMOTE_PROJECT}"
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[dict | None] = []
        self.seen_keys: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        self.seen_keys.append(request.headers.get("x-bb-api-key", ""))
        body = json.loads(request.content) if request.content else None
        self.bodies.append(body)
        if self.fail is not None:
            raise self.fail
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={
                "success": False, "error": "denied", "statusCode": self.status_code, "stack": REMOTE_KEY,
            })
        path = request.url.path
        if path == "/v4/browsersession":
            return httpx.Response(200, json={"success": True, "data": {"browserSession": {"id": "sess-1"}}})
        if path == "/v4/browsersession/newPage":
            return httpx.Response(200, json=_stagehand_action("newPage", {
                "page": {"pageId": "page-1", "targetId": "target-1", "mainFrameId": "frame-1", "url": "about:blank"},
            }))
        if path == "/v4/page/goto":
            return httpx.Response(200, json=_stagehand_action("goto", {
                "url": "https://example.com/page",
                "response": {
                    "url": "https://example.com/page",
                    "status": 200 if self.goto_ok else 500,
                    "statusText": "OK" if self.goto_ok else "Error",
                    "ok": self.goto_ok,
                    "headers": {},
                },
            }))
        if path == "/v4/page/url":
            return httpx.Response(200, json=_stagehand_action("url", {"url": self.page_url}))
        if path == "/v4/page/title":
            return httpx.Response(200, json=_stagehand_action("title", {"title": "Example"}))
        if path == "/v4/page/snapshot":
            return httpx.Response(200, json=_stagehand_action("snapshot", {
                "formattedTree": self.text, "xpathMap": {}, "urlMap": {},
            }))
        if path == "/v4/page/click":
            self.text = "clicked:#go"
            return httpx.Response(200, json=_stagehand_action("click", {"selector": {"css": "#go"}}))
        raise AssertionError(f"unexpected remote path {path}")


def _remote_provider(script: RemoteScript, monkeypatch) -> BrowserToolProvider:
    monkeypatch.setenv("SWARM_BROWSER", "1")
    monkeypatch.setenv("SWARM_BROWSER_REMOTE", "1")
    monkeypatch.setenv("BROWSERBASE_API_KEY", REMOTE_KEY)
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", REMOTE_PROJECT)
    transport = HttpxStagehandTransport(
        api_key=REMOTE_KEY,
        project_id=REMOTE_PROJECT,
        base_url="https://api.stagehand.browserbase.com",
        transport=httpx.MockTransport(script.handler),
    )
    return BrowserToolProvider(transport=transport)


def test_browser_opt_in_is_off_by_default(monkeypatch):
    _no_browser_env(monkeypatch)
    assert browser_opted_in() is False
    assert BrowserToolProvider().configured() is False


@pytest.mark.asyncio
async def test_unconfigured_browser_is_missing_not_success(monkeypatch):
    _no_browser_env(monkeypatch)
    provider = BrowserToolProvider()
    assert provider.list_tools() == []
    health = await provider.health()
    assert health.status == "unconfigured"
    assert health.tools == []
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_opted_in_without_playwright_is_unavailable_not_success(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    provider = BrowserToolProvider()
    monkeypatch.setattr("app.browser.playwright_importable", lambda: False)
    health = await provider.health()
    assert health.status == "unavailable"
    assert "Playwright" in (health.detail or "")
    names = [spec.name for spec in provider.list_tools()]
    assert names == ["browser.navigate", "browser.snapshot", "browser.click"]
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert "example.com" not in str(exc.value)


@pytest.mark.asyncio
async def test_fake_navigate_snapshot_click_are_real_and_strip_secrets(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    driver = FakeBrowserDriver()
    provider = BrowserToolProvider(opted_in=True, driver=driver)
    assert isinstance(provider, ToolProvider)
    navigated = await provider.invoke(ToolCall(
        name="browser.navigate",
        arguments={"url": "https://user:secret@example.com/page"},
    ))
    assert navigated.ok
    assert navigated.output["url"] == "https://example.com/page"
    assert navigated.output["title"] == "Example"
    assert navigated.output["text"] == "hello from fake browser"
    assert "secret" not in json.dumps(navigated.output)
    assert "api_key" not in navigated.output
    snapped = await provider.invoke(ToolCall(name="browser.snapshot", arguments={}))
    assert snapped.output["url"] == "https://example.com/page"
    clicked = await provider.invoke(ToolCall(name="browser.click", arguments={"selector": "#go"}))
    assert clicked.output["text"] == "clicked:#go"
    assert driver.calls == [
        ("navigate", "https://user:secret@example.com/page"),
        ("snapshot", None),
        ("click", "#go"),
    ]


@pytest.mark.asyncio
async def test_non_http_url_fails_closed(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    driver = FakeBrowserDriver()
    provider = BrowserToolProvider(opted_in=True, driver=driver)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "file:///etc/passwd"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert driver.calls == []


@pytest.mark.asyncio
async def test_snapshot_without_navigate_fails_closed(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    provider = BrowserToolProvider(opted_in=True, driver=FakeBrowserDriver())
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.snapshot", arguments={}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE


@pytest.mark.asyncio
async def test_driver_failure_is_not_success(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    provider = BrowserToolProvider(
        opted_in=True,
        driver=FakeBrowserDriver(fail=ToolError("navigation failed", FailureClass.TOOL_FAILURE)),
    )
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert "example.com" not in str(exc.value)


@pytest.mark.asyncio
async def test_driver_omitting_url_is_not_success(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    provider = BrowserToolProvider(opted_in=True, driver=FakeBrowserDriver(invalid={"title": "nope"}))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE


@pytest.mark.asyncio
async def test_driver_timeout_is_classified(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    provider = BrowserToolProvider(opted_in=True, driver=FakeBrowserDriver(fail=TimeoutError()))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TIMEOUT


def test_build_tool_provider_includes_browser_only_when_opted_in(monkeypatch):
    _no_browser_env(monkeypatch)
    assert build_tool_provider() is None
    monkeypatch.setenv("SWARM_BROWSER", "1")
    provider = build_tool_provider()
    assert [spec.name for spec in provider.list_tools()] == [
        "browser.navigate", "browser.snapshot", "browser.click",
    ]
    assert provider.provider_id == "playwright"


@pytest.mark.asyncio
async def test_health_is_unconfigured_by_default(monkeypatch):
    _no_browser_env(monkeypatch)
    status = await browser_health_status()
    assert status["configured"] is False
    assert status["status"] == "unconfigured"
    assert status["tools"] == []
    assert status["fallback"] is False
    assert status["remote"] is False
    assert status["provider"] == "playwright"
    assert "secret" not in json.dumps(status)


def test_policy_still_denies_browser_without_opt_in(monkeypatch):
    _no_browser_env(monkeypatch)
    gate = PolicyGate()
    mission = Mission(goal="tools")
    assert tool_is_dangerous("browser.navigate")
    assert not tool_is_opted_in_browser("browser.navigate")
    with pytest.raises(PolicyError) as exc:
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="browser.navigate"))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="browser.open"))


def test_policy_allows_opted_in_browser_tools_only(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    gate = PolicyGate()
    mission = Mission(goal="browse")
    assert tool_is_opted_in_browser("browser.navigate")
    gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="browser.navigate"))
    with pytest.raises(PolicyError) as shell:
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="shell"))
    assert shell.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="browser.open"))


def test_local_only_still_denies_opted_in_browser(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    gate = PolicyGate()
    mission = Mission(goal="private", privacy="local_only")
    with pytest.raises(PolicyError) as exc:
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="browser.navigate"))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(exc.value)


@pytest.mark.asyncio
async def test_runtime_invokes_opted_in_browser_with_fake_driver(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        tools=BrowserToolProvider(opted_in=True, driver=FakeBrowserDriver()),
    )
    mission = Mission(goal="Browse with a fake")
    store.save_mission(mission)
    result = await runtime.invoke_tool(mission, "browser.navigate", {"url": "https://example.com"})
    assert result["ok"] is True
    assert result["output"]["text"] == "hello from fake browser"
    events = store.events(mission.id)
    assert any(e.event_type == "tool.started" for e in events)
    assert any(e.event_type == "tool.completed" for e in events)
    assert not any(e.event_type == "tool.failed" for e in events)
    assert runtime.tool_calls_used(mission.id) == 1


@pytest.mark.asyncio
async def test_runtime_denies_browser_when_listed_but_not_opted_in(tmp_path, monkeypatch):
    _no_browser_env(monkeypatch)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        tools=BrowserToolProvider(opted_in=True, driver=FakeBrowserDriver()),
    )
    mission = Mission(goal="No browse")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "browser.navigate", {"url": "https://example.com"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(e.event_type == "tool.started" for e in store.events(mission.id))


def _opt_in_remote(monkeypatch):
    monkeypatch.setenv("SWARM_BROWSER", "1")
    monkeypatch.setenv("SWARM_BROWSER_REMOTE", "1")
    monkeypatch.setenv("BROWSERBASE_API_KEY", REMOTE_KEY)
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", REMOTE_PROJECT)


def test_remote_flag_without_swarm_browser_stays_disabled(monkeypatch):
    _no_browser_env(monkeypatch)
    monkeypatch.setenv("SWARM_BROWSER_REMOTE", "1")
    monkeypatch.setenv("BROWSERBASE_API_KEY", REMOTE_KEY)
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", REMOTE_PROJECT)
    provider = BrowserToolProvider()
    assert provider.configured() is False
    assert provider.uses_remote is False
    assert provider.provider_id == "playwright"
    gate = PolicyGate()
    with pytest.raises(PolicyError) as exc:
        gate.authorize(PolicyRequest(
            action="tool_use", mission=Mission(goal="no"), tool="browser.navigate",
        ))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL


@pytest.mark.asyncio
async def test_remote_without_credentials_is_unconfigured_not_playwright(monkeypatch):
    _no_browser_env(monkeypatch)
    monkeypatch.setenv("SWARM_BROWSER", "1")
    monkeypatch.setenv("SWARM_BROWSER_REMOTE", "1")
    provider = BrowserToolProvider()
    assert provider.configured() is False
    assert provider.list_tools() == []
    assert provider.provider_id == "browserbase"
    built = build_tool_provider()
    names = [] if built is None else [spec.name for spec in built.list_tools()]
    assert "browser.navigate" not in names
    health = await provider.health()
    assert health.status == "unconfigured"
    assert REMOTE_KEY not in json.dumps(health.model_dump())
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_remote_health_with_credentials_does_not_open_a_session(monkeypatch):
    _no_browser_env(monkeypatch)
    _opt_in_remote(monkeypatch)
    provider = BrowserToolProvider()
    assert provider.uses_remote is True
    assert [spec.name for spec in provider.list_tools()] == [
        "browser.navigate", "browser.snapshot", "browser.click",
    ]
    health = await provider.health()
    assert health.status == "healthy"
    assert health.provider == "browserbase"
    status = await browser_health_status()
    assert status["configured"] is True
    assert status["remote"] is True
    assert status["provider"] == "browserbase"
    assert status["fallback"] is False
    dumped = json.dumps({"health": health.model_dump(), "status": status})
    assert REMOTE_KEY not in dumped
    assert REMOTE_PROJECT not in dumped


def test_injected_driver_stays_local_when_remote_env_is_set(monkeypatch):
    _opt_in_remote(monkeypatch)
    provider = BrowserToolProvider(driver=FakeBrowserDriver())
    assert provider.provider_id == "playwright"
    assert provider.uses_remote is False


@pytest.mark.asyncio
async def test_remote_navigate_snapshot_click_uses_stagehand_paths(monkeypatch):
    script = RemoteScript()
    provider = _remote_provider(script, monkeypatch)
    navigated = await provider.invoke(ToolCall(
        name="browser.navigate", arguments={"url": "https://user:secret@example.com/page"},
    ))
    assert navigated.ok
    assert navigated.provider == "browserbase"
    assert navigated.output["url"] == "https://example.com/page"
    assert navigated.output["title"] == "Example"
    assert "[redacted]" in navigated.output["text"]
    dumped = json.dumps(navigated.output)
    assert REMOTE_KEY not in dumped
    assert REMOTE_PROJECT not in dumped
    assert "secret" not in dumped
    snapped = await provider.invoke(ToolCall(name="browser.snapshot", arguments={}))
    assert snapped.output["url"] == "https://example.com/page"
    clicked = await provider.invoke(ToolCall(name="browser.click", arguments={"selector": "#go"}))
    assert clicked.output["text"] == "clicked:#go"
    paths = [path for _, path in script.calls]
    assert paths[0:3] == ["/v4/browsersession", "/v4/browsersession/newPage", "/v4/page/goto"]
    assert "/v4/page/click" in paths
    assert "/v4/page/snapshot" in paths
    assert not any(path.endswith(("/act", "/type", "/fill", "/agentExecute")) for path in paths)
    assert set(script.seen_keys) == {REMOTE_KEY}
    create = script.bodies[0]
    assert create["env"] == "BROWSERBASE"
    assert create["browserbaseSessionCreateParams"]["projectId"] == REMOTE_PROJECT
    click = next(body for body in script.bodies if isinstance(body, dict) and "selector" in body.get("params", {}))
    assert click["params"]["selector"] == {"css": "#go"}
    assert click["params"]["method"] == "jsevent"


@pytest.mark.asyncio
async def test_remote_checkout_selector_is_refused_without_a_request(monkeypatch):
    script = RemoteScript()
    provider = _remote_provider(script, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.click", arguments={"selector": "button.buy-now"}))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert script.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,failure", [
    (401, FailureClass.AUTHORIZATION_REQUIRED),
    (403, FailureClass.AUTHORIZATION_REQUIRED),
    (408, FailureClass.TIMEOUT),
    (429, FailureClass.RATE_LIMIT),
    (500, FailureClass.PROVIDER_OUTAGE),
    (503, FailureClass.PROVIDER_OUTAGE),
])
async def test_remote_http_errors_are_classified_without_leaking_secrets(monkeypatch, status, failure):
    script = RemoteScript(status_code=status)
    provider = _remote_provider(script, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == failure
    assert REMOTE_KEY not in str(exc.value)
    assert "stack" not in str(exc.value)


@pytest.mark.asyncio
async def test_remote_timeout_and_outage_are_classified(monkeypatch):
    timeout = RemoteScript(fail=httpx.ReadTimeout("timed out"))
    provider = _remote_provider(timeout, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TIMEOUT
    offline = RemoteScript(fail=httpx.ConnectError("offline"))
    provider = _remote_provider(offline, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.PROVIDER_OUTAGE


@pytest.mark.asyncio
async def test_remote_failed_navigation_and_missing_url_are_not_success(monkeypatch):
    failed = RemoteScript(goto_ok=False)
    provider = _remote_provider(failed, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    missing = RemoteScript(page_url="")
    provider = _remote_provider(missing, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE


@pytest.mark.asyncio
async def test_remote_non_http_page_is_not_success(monkeypatch):
    script = RemoteScript(page_url="file:///etc/passwd")
    provider = _remote_provider(script, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert "passwd" not in str(exc.value)


@pytest.mark.asyncio
async def test_remote_snapshot_before_navigate_fails_closed(monkeypatch):
    script = RemoteScript()
    provider = _remote_provider(script, monkeypatch)
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.snapshot", arguments={}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert script.calls == []


def test_local_only_still_denies_remote_browser(monkeypatch):
    _opt_in_remote(monkeypatch)
    gate = PolicyGate()
    mission = Mission(goal="private", privacy="local_only")
    with pytest.raises(PolicyError) as exc:
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="browser.snapshot"))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="browser.open"))


@pytest.mark.asyncio
async def test_runtime_remote_does_not_bypass_local_only(tmp_path, monkeypatch):
    _opt_in_remote(monkeypatch)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        tools=BrowserToolProvider(opted_in=True, remote=True, driver=FakeBrowserDriver()),
    )
    mission = Mission(goal="private browse", privacy="local_only")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "browser.navigate", {"url": "https://example.com"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(e.event_type == "tool.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_invalid_stagehand_base_url_fails_closed(monkeypatch):
    _no_browser_env(monkeypatch)
    _opt_in_remote(monkeypatch)
    monkeypatch.setenv("STAGEHAND_BASE_URL", "file:///tmp/stagehand")
    provider = BrowserToolProvider()
    health = await provider.health()
    assert health.status == "healthy"
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="browser.navigate", arguments={"url": "https://example.com"}))
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
