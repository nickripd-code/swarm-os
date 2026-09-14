"""Playwright browser capability behind ToolProvider.

Disabled by default (`SWARM_BROWSER` unset). Never invents a successful browse.
CI tests inject a fake driver; this module does not launch a live browser in tests.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse, urlunparse

from .models import FailureClass
from .tools import (
    ToolCall, ToolError, ToolHealth, ToolProvider, ToolResult, ToolSpec,
    public_tool_data, require_arguments,
)

BROWSER_TOOL_NAMES = ("browser.navigate", "browser.snapshot", "browser.click")
ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_URL_BYTES = 2048
MAX_SELECTOR_BYTES = 512
MAX_TEXT_CHARS = 4000
DEFAULT_TIMEOUT_MS = 15_000
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def browser_opted_in(raw: str | None = None) -> bool:
    text = (raw if raw is not None else os.getenv("SWARM_BROWSER", "")).strip().lower()
    return text in TRUE_VALUES


def playwright_importable() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


def require_http_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("browser.navigate requires a string url argument", FailureClass.TOOL_FAILURE)
    url = value.strip()
    if len(url.encode("utf-8")) > MAX_URL_BYTES:
        raise ToolError("URL exceeds the size limit", FailureClass.TOOL_FAILURE)
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ToolError("Only http and https URLs are allowed", FailureClass.TOOL_FAILURE)
    if not parsed.netloc:
        raise ToolError("URL is missing a host", FailureClass.TOOL_FAILURE)
    return url


def public_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, host, parsed.path, parsed.params, parsed.query, ""))


def require_selector(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("browser.click requires a string selector argument", FailureClass.TOOL_FAILURE)
    selector = value.strip()
    if len(selector.encode("utf-8")) > MAX_SELECTOR_BYTES:
        raise ToolError("Selector exceeds the size limit", FailureClass.TOOL_FAILURE)
    return selector


def page_output(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ToolError("Browser driver returned an invalid page", FailureClass.TOOL_FAILURE)
    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ToolError("Browser driver omitted the page URL", FailureClass.TOOL_FAILURE)
    title = raw.get("title") if isinstance(raw.get("title"), str) else ""
    text = raw.get("text") if isinstance(raw.get("text"), str) else ""
    return public_tool_data({
        "url": public_url(url),
        "title": title,
        "text": text[:MAX_TEXT_CHARS],
    })


class BrowserDriver(ABC):
    """Real or test-double page driver. Implementations must not fake a successful browse."""

    @abstractmethod
    async def navigate(self, url: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def click(self, selector: str) -> dict[str, Any]:
        raise NotImplementedError


class PlaywrightBrowserDriver(BrowserDriver):
    """Lazy Playwright Chromium driver. Import/launch failures stay fail-closed."""

    def __init__(self, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._page = None

    async def navigate(self, url: str) -> dict[str, Any]:
        page = await self._ensure_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except Exception as exc:
            raise _playwright_error(exc, "navigation") from None
        if response is None:
            raise ToolError("Browser navigation returned no response", FailureClass.TOOL_FAILURE)
        if not response.ok:
            raise ToolError("Browser navigation did not succeed", FailureClass.TOOL_FAILURE)
        return await self._capture(page)

    async def snapshot(self) -> dict[str, Any]:
        page = self._require_open_page()
        return await self._capture(page)

    async def click(self, selector: str) -> dict[str, Any]:
        page = self._require_open_page()
        try:
            await page.click(selector, timeout=self.timeout_ms)
        except Exception as exc:
            raise _playwright_error(exc, "click") from None
        return await self._capture(page)

    def _require_open_page(self):
        if self._page is None:
            raise ToolError("No page is open; navigate first", FailureClass.TOOL_FAILURE)
        return self._page

    async def _ensure_page(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ToolError("Playwright is not installed", FailureClass.TOOL_FAILURE) from None
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._page = await self._browser.new_page()
        except Exception as exc:
            raise _playwright_error(exc, "launch") from None
        return self._page

    async def _capture(self, page) -> dict[str, Any]:
        try:
            url = str(page.url or "")
            title = await page.title()
            text = await page.inner_text("body")
        except Exception as extra:
            raise _playwright_error(extra, "snapshot") from None
        return {"url": url, "title": title if isinstance(title, str) else "", "text": text or ""}


def _playwright_error(exc: Exception, action: str) -> ToolError:
    name = type(exc).__name__
    if "Timeout" in name:
        return ToolError(f"Browser {action} timed out", FailureClass.TIMEOUT)
    if "ImportError" in name:
        return ToolError("Playwright is not installed", FailureClass.TOOL_FAILURE)
    if action == "launch":
        return ToolError("Could not start the Playwright browser", FailureClass.PROVIDER_OUTAGE)
    return ToolError(f"Browser {action} failed", FailureClass.TOOL_FAILURE)


def _browser_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="browser.navigate",
            description="Open an http(s) URL in the Playwright browser and return title, URL, and visible text.",
            provider="playwright",
            permissions=["browser"],
            risk_class="browser",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["url"],
            },
            environment=["SWARM_BROWSER"],
        ),
        ToolSpec(
            name="browser.snapshot",
            description="Return the current Playwright page URL, title, and visible text.",
            provider="playwright",
            permissions=["browser"],
            risk_class="browser",
            input_schema={"type": "object", "properties": {}},
            output_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["url"],
            },
            environment=["SWARM_BROWSER"],
        ),
        ToolSpec(
            name="browser.click",
            description="Click a CSS selector on the current Playwright page and return the resulting snapshot.",
            provider="playwright",
            permissions=["browser"],
            risk_class="browser",
            input_schema={
                "type": "object",
                "properties": {"selector": {"type": "string"}},
                "required": ["selector"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["url"],
            },
            environment=["SWARM_BROWSER"],
        ),
    ]


class BrowserToolProvider(ToolProvider):
    """Fail-closed Playwright tools. Unconfigured until SWARM_BROWSER is set."""

    provider_id = "playwright"

    def __init__(self, *, opted_in: bool | None = None, driver: BrowserDriver | None = None):
        self._opted_in = browser_opted_in() if opted_in is None else opted_in
        self._driver = driver
        self._specs = _browser_specs() if self._opted_in else []

    def configured(self) -> bool:
        return self._opted_in

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self._opted_in:
            raise ToolError("Browser tools are disabled", FailureClass.TOOL_MISSING)
        if call.name not in BROWSER_TOOL_NAMES:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        arguments = require_arguments(call.arguments)
        driver = self._require_driver()
        try:
            if call.name == "browser.navigate":
                raw = await driver.navigate(require_http_url(arguments.get("url")))
            elif call.name == "browser.snapshot":
                raw = await driver.snapshot()
            else:
                raw = await driver.click(require_selector(arguments.get("selector")))
        except ToolError:
            raise
        except TimeoutError:
            raise ToolError("Browser action timed out", FailureClass.TIMEOUT) from None
        except Exception:
            raise ToolError("Browser driver failed", FailureClass.TOOL_FAILURE) from None
        return ToolResult(
            name=call.name,
            call_id=call.call_id,
            ok=True,
            output=page_output(raw),
            provider=self.provider_id,
        )

    async def health(self) -> ToolHealth:
        if not self._opted_in:
            return ToolHealth(
                provider=self.provider_id,
                status="unconfigured",
                detail="Browser tools are disabled until SWARM_BROWSER is set",
            )
        if self._driver is not None:
            return ToolHealth(
                provider=self.provider_id,
                status="healthy",
                detail="Playwright browser driver is ready",
                tools=[spec.name for spec in self._specs],
            )
        if playwright_importable():
            return ToolHealth(
                provider=self.provider_id,
                status="healthy",
                detail="Playwright is installed; health does not launch a browser",
                tools=[spec.name for spec in self._specs],
            )
        return ToolHealth(
            provider=self.provider_id,
            status="unavailable",
            detail="SWARM_BROWSER is set but Playwright is not installed",
            tools=[spec.name for spec in self._specs],
        )

    def _require_driver(self) -> BrowserDriver:
        if self._driver is not None:
            return self._driver
        if not playwright_importable():
            raise ToolError("Playwright is not installed", FailureClass.TOOL_FAILURE)
        self._driver = PlaywrightBrowserDriver()
        return self._driver
