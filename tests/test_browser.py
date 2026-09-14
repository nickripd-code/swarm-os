import json

import pytest

from app.browser import BrowserDriver, BrowserToolProvider, browser_opted_in
from app.health import browser_health_status
from app.models import FailureClass, Mission
from app.policy import PolicyError, PolicyGate, PolicyRequest, tool_is_dangerous, tool_is_opted_in_browser
from app.runtime import SwarmRuntime
from app.store import Store
from app.tools import ToolCall, ToolError, ToolProvider, build_tool_provider


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
    monkeypatch.delenv("SWARM_LOCAL_TOOLS", raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)


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
