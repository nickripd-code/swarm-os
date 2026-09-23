"""Browser capability behind ToolProvider.

Local Playwright is the default when `SWARM_BROWSER` is set. A Browserbase/Stagehand
remote session is a separate opt-in (`SWARM_BROWSER_REMOTE` plus credentials).
Neither path invents a successful browse. CI injects a fake driver or HTTP transport
and does not call Browserbase.
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

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
DEFAULT_STAGEHAND_BASE_URL = "https://api.stagehand.browserbase.com"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_MUTATING_SELECTOR = re.compile(
    r"check\s*-?out|place[-_\s]?order|buy[-_\s]?now|add[-_\s]?to[-_\s]?cart|"
    r"book[-_\s]?now|confirm[-_\s]?booking|pay[-_\s]?now|submit[-_\s]?payment|"
    r"complete[-_\s]?purchase|place[-_\s]?booking",
    re.IGNORECASE,
)


def browser_opted_in(raw: str | None = None) -> bool:
    text = (raw if raw is not None else os.getenv("SWARM_BROWSER", "")).strip().lower()
    return text in TRUE_VALUES


def playwright_importable() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


def remote_browser_opted_in(raw: str | None = None) -> bool:
    text = (raw if raw is not None else os.getenv("SWARM_BROWSER_REMOTE", "")).strip().lower()
    return text in TRUE_VALUES


def remote_browser_credentials() -> tuple[str, str] | None:
    """Read Browserbase credentials from the environment. Never log the return value."""
    api_key = os.getenv("BROWSERBASE_API_KEY", "").strip()
    project_id = os.getenv("BROWSERBASE_PROJECT_ID", "").strip()
    if api_key and project_id:
        return api_key, project_id
    return None


def stagehand_base_url() -> str:
    raw = os.getenv("STAGEHAND_BASE_URL", DEFAULT_STAGEHAND_BASE_URL).strip() or DEFAULT_STAGEHAND_BASE_URL
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.netloc:
        raise ToolError("STAGEHAND_BASE_URL must be an http(s) URL", FailureClass.TOOL_FAILURE)
    return raw.rstrip("/")


def refuse_mutating_browser_action(selector: str) -> None:
    """Checkout, payment, and booking clicks stay out of scope for this seed."""
    if _MUTATING_SELECTOR.search(selector):
        raise ToolError(
            "Checkout, payment, and booking actions are out of scope",
            FailureClass.POLICY_REFUSAL,
        )


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


def _classify_stagehand_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code in {301, 302, 303, 307, 308}:
        raise ToolError("Remote browser returned an unexpected redirect", FailureClass.PROVIDER_OUTAGE)
    if response.status_code in {401, 403}:
        raise ToolError("Remote browser authorization failed", FailureClass.AUTHORIZATION_REQUIRED)
    if response.status_code == 429:
        raise ToolError("Remote browser rate limit reached", FailureClass.RATE_LIMIT)
    if response.status_code == 408:
        raise ToolError("Remote browser request timed out", FailureClass.TIMEOUT)
    if response.status_code >= 500:
        raise ToolError("Remote browser is unavailable", FailureClass.PROVIDER_OUTAGE)
    if response.is_error:
        raise ToolError("Remote browser request failed", FailureClass.TOOL_FAILURE)
    try:
        payload = response.json()
    except ValueError:
        raise ToolError("Remote browser returned invalid JSON", FailureClass.TOOL_FAILURE) from None
    if not isinstance(payload, dict):
        raise ToolError("Remote browser returned an invalid response", FailureClass.TOOL_FAILURE)
    return payload


class HttpxStagehandTransport:
    """Thin Stagehand v4 JSON client. Headers stay on this object and out of errors."""

    def __init__(
        self,
        *,
        api_key: str,
        project_id: str,
        base_url: str | None = None,
        timeout_s: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self._project_id = project_id
        self._base_url = (base_url or stagehand_base_url()).rstrip("/")
        self._timeout_s = DEFAULT_TIMEOUT_MS / 1000 if timeout_s is None else timeout_s
        self._transport = transport

    @property
    def project_id(self) -> str:
        return self._project_id

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-bb-api-key": self._api_key,
            "x-bb-project-id": self._project_id,
            "x-stream-response": "false",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_s, connect=5.0),
                trust_env=False,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    json=json,
                    params=params,
                    headers=headers,
                )
        except httpx.TimeoutException:
            raise ToolError("Remote browser request timed out", FailureClass.TIMEOUT) from None
        except httpx.RequestError:
            raise ToolError("Could not reach the remote browser", FailureClass.PROVIDER_OUTAGE) from None
        return _classify_stagehand_response(response)


def _require_completed(payload: dict[str, Any], action: str) -> dict[str, Any]:
    if payload.get("success") is not True:
        raise ToolError(f"Browser {action} failed", FailureClass.TOOL_FAILURE)
    record = payload.get("action")
    if not isinstance(record, dict):
        raise ToolError(f"Browser {action} returned an invalid result", FailureClass.TOOL_FAILURE)
    if record.get("status") not in (None, "completed"):
        raise ToolError(f"Browser {action} did not complete", FailureClass.TOOL_FAILURE)
    if record.get("error"):
        raise ToolError(f"Browser {action} failed", FailureClass.TOOL_FAILURE)
    return record


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if len(secret) >= 8:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


class BrowserbaseStagehandDriver(BrowserDriver):
    """Stagehand v4 page.goto / page.snapshot / page.click over HTTP.

    Does not call act, type, fill, evaluate, or agent endpoints.
    """

    def __init__(
        self,
        transport: HttpxStagehandTransport,
        *,
        project_id: str,
        redact: tuple[str, ...] = (),
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        self._transport = transport
        self._project_id = project_id
        self._redact = redact
        self._timeout_ms = timeout_ms
        self._session_id: str | None = None
        self._page_id: str | None = None

    async def navigate(self, url: str) -> dict[str, Any]:
        await self._ensure_page()
        payload = await self._transport.request(
            "POST",
            "/v4/page/goto",
            json={
                "sessionId": self._session_id,
                "params": {
                    "pageId": self._page_id,
                    "url": url,
                    "waitUntil": "domcontentloaded",
                    "timeoutMs": self._timeout_ms,
                },
            },
        )
        record = _require_completed(payload, "navigation")
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        response = result.get("response") if isinstance(result, dict) else None
        if isinstance(response, dict) and response.get("ok") is False:
            raise ToolError("Browser navigation did not succeed", FailureClass.TOOL_FAILURE)
        return await self._capture()

    async def snapshot(self) -> dict[str, Any]:
        self._require_open_page()
        return await self._capture()

    async def click(self, selector: str) -> dict[str, Any]:
        refuse_mutating_browser_action(selector)
        self._require_open_page()
        payload = await self._transport.request(
            "POST",
            "/v4/page/click",
            json={
                "sessionId": self._session_id,
                "params": {
                    "pageId": self._page_id,
                    "selector": {"css": selector},
                    "method": "jsevent",
                },
            },
        )
        _require_completed(payload, "click")
        return await self._capture()

    def _require_open_page(self) -> None:
        if self._page_id is None or self._session_id is None:
            raise ToolError("No page is open; navigate first", FailureClass.TOOL_FAILURE)

    async def _ensure_page(self) -> None:
        if self._session_id is None:
            created = await self._transport.request(
                "POST",
                "/v4/browsersession",
                json={
                    "env": "BROWSERBASE",
                    "browserbaseSessionCreateParams": {"projectId": self._project_id},
                },
            )
            if created.get("success") is not True:
                raise ToolError("Could not start the remote browser", FailureClass.PROVIDER_OUTAGE)
            session = created.get("data") if isinstance(created.get("data"), dict) else {}
            browser_session = session.get("browserSession") if isinstance(session, dict) else None
            session_id = browser_session.get("id") if isinstance(browser_session, dict) else None
            if not isinstance(session_id, str) or not session_id.strip():
                raise ToolError("Remote browser did not return a session", FailureClass.TOOL_FAILURE)
            self._session_id = session_id
        if self._page_id is None:
            opened = await self._transport.request(
                "POST",
                "/v4/browsersession/newPage",
                json={"sessionId": self._session_id, "params": {}},
            )
            record = _require_completed(opened, "launch")
            result = record.get("result") if isinstance(record.get("result"), dict) else {}
            page = result.get("page") if isinstance(result, dict) else None
            page_id = page.get("pageId") if isinstance(page, dict) else None
            if not isinstance(page_id, str) or not page_id.strip():
                raise ToolError("Remote browser did not return a page", FailureClass.TOOL_FAILURE)
            self._page_id = page_id

    async def _capture(self) -> dict[str, Any]:
        self._require_open_page()
        url_payload = await self._transport.request(
            "GET",
            "/v4/page/url",
            params={"sessionId": self._session_id, "pageId": self._page_id},
        )
        title_payload = await self._transport.request(
            "GET",
            "/v4/page/title",
            params={"sessionId": self._session_id, "pageId": self._page_id},
        )
        snap_payload = await self._transport.request(
            "POST",
            "/v4/page/snapshot",
            json={"sessionId": self._session_id, "params": {"pageId": self._page_id}},
        )
        url_record = _require_completed(url_payload, "snapshot")
        title_record = _require_completed(title_payload, "snapshot")
        snap_record = _require_completed(snap_payload, "snapshot")
        url_result = url_record.get("result") if isinstance(url_record.get("result"), dict) else {}
        title_result = title_record.get("result") if isinstance(title_record.get("result"), dict) else {}
        snap_result = snap_record.get("result") if isinstance(snap_record.get("result"), dict) else {}
        url = url_result.get("url") if isinstance(url_result, dict) else None
        title = title_result.get("title") if isinstance(title_result, dict) else ""
        text = snap_result.get("formattedTree") if isinstance(snap_result, dict) else ""
        if not isinstance(url, str) or not url.strip():
            raise ToolError("Browser driver omitted the page URL", FailureClass.TOOL_FAILURE)
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise ToolError("Remote browser returned a non-http page", FailureClass.TOOL_FAILURE)
        return {
            "url": _redact_text(url, self._redact),
            "title": _redact_text(title if isinstance(title, str) else "", self._redact),
            "text": _redact_text(text if isinstance(text, str) else "", self._redact),
        }


def _browser_specs(provider: str = "playwright") -> list[ToolSpec]:
    label = "Browserbase" if provider == "browserbase" else "Playwright"
    environment = ["SWARM_BROWSER"]
    if provider == "browserbase":
        environment = ["SWARM_BROWSER", "SWARM_BROWSER_REMOTE", "BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"]
    return [
        ToolSpec(
            name="browser.navigate",
            description=f"Open an http(s) URL in the {label} browser and return title, URL, and visible text.",
            provider=provider,
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
            environment=environment,
        ),
        ToolSpec(
            name="browser.snapshot",
            description=f"Return the current {label} page URL, title, and visible text.",
            provider=provider,
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
            environment=environment,
        ),
        ToolSpec(
            name="browser.click",
            description=(
                f"Click a CSS selector on the current {label} page and return the resulting snapshot. "
                "Checkout, payment, and booking actions are out of scope."
            ),
            provider=provider,
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
            environment=environment,
        ),
    ]


class BrowserToolProvider(ToolProvider):
    """Fail-closed browser tools. Local Playwright unless remote is explicitly configured."""

    provider_id = "playwright"

    def __init__(
        self,
        *,
        opted_in: bool | None = None,
        driver: BrowserDriver | None = None,
        remote: bool | None = None,
        transport: HttpxStagehandTransport | None = None,
    ):
        self._opted_in = browser_opted_in() if opted_in is None else opted_in
        self._remote_requested = remote_browser_opted_in() if remote is None else remote
        if driver is not None and remote is None:
            self._remote_requested = False
        self._driver = driver
        self._transport = transport
        self.provider_id = "browserbase" if self._opted_in and self._remote_requested else "playwright"
        self._specs = _browser_specs(self.provider_id) if self.configured() else []

    @property
    def uses_remote(self) -> bool:
        return self._opted_in and self._remote_requested and self._remote_ready()

    def _remote_ready(self) -> bool:
        if self._driver is not None or self._transport is not None:
            return True
        return remote_browser_credentials() is not None

    def configured(self) -> bool:
        if not self._opted_in:
            return False
        if self._remote_requested:
            return self._remote_ready()
        return True

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self.configured():
            if self._opted_in and self._remote_requested:
                raise ToolError("Remote browser is not configured", FailureClass.TOOL_MISSING)
            raise ToolError("Browser tools are disabled", FailureClass.TOOL_MISSING)
        if call.name not in BROWSER_TOOL_NAMES:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        arguments = require_arguments(call.arguments)
        if call.name == "browser.click" and self._remote_requested:
            refuse_mutating_browser_action(require_selector(arguments.get("selector")))
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
        if self._remote_requested and not self._remote_ready():
            return ToolHealth(
                provider=self.provider_id,
                status="unconfigured",
                detail="Remote browser is unconfigured until BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID are set",
            )
        if self._remote_requested:
            return ToolHealth(
                provider=self.provider_id,
                status="healthy",
                detail="Remote browser is configured; health does not open a session",
                tools=[spec.name for spec in self._specs],
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
        if self._remote_requested:
            creds = remote_browser_credentials()
            if self._transport is None and creds is None:
                raise ToolError("Remote browser is not configured", FailureClass.TOOL_MISSING)
            api_key = creds[0] if creds else ""
            if self._transport is None:
                project_id = creds[1] if creds else ""
                self._transport = HttpxStagehandTransport(api_key=api_key, project_id=project_id)
            else:
                project_id = getattr(self._transport, "project_id", "") or (creds[1] if creds else "")
            if not isinstance(project_id, str) or not project_id:
                raise ToolError("Remote browser is not configured", FailureClass.TOOL_MISSING)
            self._driver = BrowserbaseStagehandDriver(
                self._transport,
                project_id=project_id,
                redact=tuple(secret for secret in (api_key, project_id) if secret),
            )
            return self._driver
        if not playwright_importable():
            raise ToolError("Playwright is not installed", FailureClass.TOOL_FAILURE)
        self._driver = PlaywrightBrowserDriver()
        return self._driver
