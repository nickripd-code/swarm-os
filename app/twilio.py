"""Opt-in Twilio Messaging SMS adapter. Voice and mass sends stay disabled."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .models import FailureClass
from .tools import (
    ToolCall,
    ToolError,
    ToolHealth,
    ToolProvider,
    ToolResult,
    ToolSpec,
    public_tool_data,
    require_arguments,
)

SMS_SEND_TOOL = "sms.send"
DEFAULT_TWILIO_BASE_URL = "https://api.twilio.com"
DEFAULT_TWILIO_TIMEOUT = 15.0
MAX_SMS_CHARS = 1600
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_SID_RE = re.compile(r"^AC[A-Za-z0-9]{16,64}$")
_MESSAGE_SID_RE = re.compile(r"^SM[A-Za-z0-9]{16,64}$")
_ALLOWED_ARGUMENTS = frozenset({"to", "body"})


@dataclass(frozen=True)
class TwilioSmsSettings:
    account_sid: str
    auth_token: str
    from_number: str
    allowlist: frozenset[str]


def normalize_e164(value: object) -> str | None:
    """Accept one E.164 number. Prefixes, lists, and extensions are not numbers."""
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[\s().-]", "", value.strip())
    if _E164_RE.fullmatch(cleaned):
        return cleaned
    return None


def parse_allowlist(raw: str) -> frozenset[str]:
    numbers: set[str] = set()
    for item in (raw or "").split(","):
        number = normalize_e164(item)
        if number:
            numbers.add(number)
    return frozenset(numbers)


def _valid_secret(value: str) -> bool:
    text = value.strip()
    return len(text) >= 8 and " " not in text and "\n" not in text and "/" not in text


def settings_from_env() -> TwilioSmsSettings | None:
    """Full opt-in only. A missing SID, token, from-number, or allowlist stays unconfigured."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = normalize_e164(os.getenv("TWILIO_FROM_NUMBER", ""))
    allowlist = parse_allowlist(os.getenv("TWILIO_SMS_ALLOWLIST", ""))
    if not (_SID_RE.fullmatch(account_sid) and _valid_secret(auth_token) and from_number and allowlist):
        return None
    return TwilioSmsSettings(account_sid, auth_token, from_number, allowlist)


def twilio_sms_configured() -> bool:
    return settings_from_env() is not None


def redact_twilio_secrets(text: str, settings: TwilioSmsSettings | None = None) -> str:
    resolved = settings if settings is not None else settings_from_env()
    redacted = text
    if resolved is None:
        return redacted
    for secret in (resolved.auth_token, resolved.account_sid):
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def sms_body_preview(arguments: dict[str, Any] | None, settings: TwilioSmsSettings | None = None) -> str:
    body = ""
    if isinstance(arguments, dict) and isinstance(arguments.get("body"), str):
        body = " ".join(arguments["body"].split())
    if len(body) > 120:
        body = body[:117] + "..."
    return redact_twilio_secrets(body, settings)


def sms_destination(arguments: dict[str, Any] | None) -> str | None:
    if not isinstance(arguments, dict):
        return None
    return normalize_e164(arguments.get("to"))


def sms_refusal_reason(
    arguments: dict[str, Any] | None,
    settings: TwilioSmsSettings | None = None,
) -> str | None:
    """Refuse before any network call. None means this single SMS may be attempted."""
    resolved = settings if settings is not None else settings_from_env()
    if resolved is None:
        return "Twilio SMS is not configured"
    if not isinstance(arguments, dict):
        return "SMS destination is not allowlisted"
    extra = set(arguments) - _ALLOWED_ARGUMENTS
    if extra:
        return "SMS arguments are not allowed"
    destination = sms_destination(arguments)
    if destination is None or destination not in resolved.allowlist:
        return "SMS destination is not allowlisted"
    body = arguments.get("body")
    if not isinstance(body, str) or not body.strip():
        return "SMS body is required"
    if len(body) > MAX_SMS_CHARS:
        return "SMS body is too long"
    return None


class TwilioSmsProvider(ToolProvider):
    """One allowlisted SMS per call. No voice, no blast, no unset-allowlist send."""

    provider_id = "twilio"

    def __init__(
        self,
        *,
        settings: TwilioSmsSettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str | None = None,
    ):
        self._settings = settings
        self.transport = transport
        self.base_url = (base_url or DEFAULT_TWILIO_BASE_URL).rstrip("/")

    def settings(self) -> TwilioSmsSettings | None:
        if self._settings is not None:
            return self._settings
        return settings_from_env()

    def configured(self) -> bool:
        return self.settings() is not None

    def list_tools(self) -> list[ToolSpec]:
        if not self.configured():
            return []
        return [
            ToolSpec(
                name=SMS_SEND_TOOL,
                description="Send one SMS to a single allowlisted phone number.",
                provider=self.provider_id,
                permissions=["twilio", "network", "sms"],
                risk_class="external_message",
                environment=[
                    "TWILIO_ACCOUNT_SID",
                    "TWILIO_AUTH_TOKEN",
                    "TWILIO_FROM_NUMBER",
                    "TWILIO_SMS_ALLOWLIST",
                ],
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "body": {"type": "string", "maxLength": MAX_SMS_CHARS},
                    },
                    "required": ["to", "body"],
                    "additionalProperties": False,
                },
            )
        ]

    async def invoke(self, call: ToolCall) -> ToolResult:
        if call.name != SMS_SEND_TOOL:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        settings = self.settings()
        if settings is None:
            raise ToolError("Twilio SMS is not configured", FailureClass.TOOL_MISSING)
        arguments = require_arguments(call.arguments)
        reason = sms_refusal_reason(arguments, settings)
        if reason:
            failure = (
                FailureClass.TOOL_MISSING
                if reason == "Twilio SMS is not configured"
                else FailureClass.POLICY_REFUSAL
            )
            raise ToolError(reason, failure)
        output = await self._send(settings, arguments)
        return ToolResult(
            name=call.name,
            call_id=call.call_id,
            ok=True,
            output=public_tool_data(output),
            provider=self.provider_id,
        )

    async def health(self) -> ToolHealth:
        if not self.configured():
            return ToolHealth(
                provider=self.provider_id,
                status="unconfigured",
                detail=(
                    "Twilio SMS requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
                    "TWILIO_FROM_NUMBER, and TWILIO_SMS_ALLOWLIST"
                ),
            )
        settings = self.settings()
        count = len(settings.allowlist) if settings else 0
        return ToolHealth(
            provider=self.provider_id,
            status="healthy",
            detail=f"SMS configured with {count} allowlisted destination(s); voice disabled",
            tools=[SMS_SEND_TOOL],
        )

    async def _send(self, settings: TwilioSmsSettings, arguments: dict[str, Any]) -> dict[str, Any]:
        destination = sms_destination(arguments)
        body = arguments.get("body")
        if destination is None or not isinstance(body, str):
            raise ToolError("SMS destination is not allowlisted", FailureClass.POLICY_REFUSAL)
        url = f"{self.base_url}/2010-04-01/Accounts/{settings.account_sid}/Messages.json"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TWILIO_TIMEOUT, connect=5.0),
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    url,
                    data={"To": destination, "From": settings.from_number, "Body": body},
                    auth=(settings.account_sid, settings.auth_token),
                )
        except httpx.TimeoutException:
            raise ToolError("Twilio request timed out", FailureClass.TIMEOUT) from None
        except httpx.RequestError:
            raise ToolError("Could not reach Twilio", FailureClass.PROVIDER_OUTAGE) from None
        return self._message(response, settings)

    def _message(self, response: httpx.Response, settings: TwilioSmsSettings) -> dict[str, Any]:
        if response.status_code in {401, 403}:
            raise ToolError("Twilio authorization failed", FailureClass.AUTHORIZATION_REQUIRED)
        if response.status_code == 429:
            raise ToolError("Twilio rate limit reached", FailureClass.RATE_LIMIT)
        if response.status_code >= 500:
            raise ToolError("Twilio is unavailable", FailureClass.PROVIDER_OUTAGE)
        if response.is_error:
            raise ToolError("Twilio request failed", FailureClass.TOOL_FAILURE)
        try:
            payload = response.json()
        except ValueError:
            raise ToolError("Twilio returned invalid JSON", FailureClass.TOOL_FAILURE) from None
        if not isinstance(payload, dict):
            raise ToolError("Twilio returned an invalid response", FailureClass.TOOL_FAILURE)
        message_sid = payload.get("sid")
        if not isinstance(message_sid, str) or not _MESSAGE_SID_RE.fullmatch(message_sid):
            raise ToolError("Twilio returned an invalid message", FailureClass.TOOL_FAILURE)
        status = payload.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ToolError("Twilio returned an invalid message", FailureClass.TOOL_FAILURE)
        return {
            "message_sid": redact_twilio_secrets(message_sid, settings),
            "status": redact_twilio_secrets(status.strip(), settings),
            "to": redact_twilio_secrets(str(payload.get("to") or ""), settings),
            "from": redact_twilio_secrets(str(payload.get("from") or ""), settings),
            "body": redact_twilio_secrets(str(payload.get("body") or ""), settings),
        }
