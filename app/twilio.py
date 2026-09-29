from __future__ import annotations

import os
import re
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
    require_arguments,
)

SMS_SEND = "sms.send"
DEFAULT_TWILIO_BASE_URL = "https://api.twilio.com"
DEFAULT_TWILIO_TIMEOUT = 20.0
MAX_SMS_BODY = 1600
_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
_SECRET_MARKERS = ("account_sid", "auth_token", "accountsid", "authtoken")


def twilio_sms_configured() -> bool:
    """True only when every SMS opt-in variable is non-empty. Partial env stays off."""
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        and os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        and os.getenv("TWILIO_FROM_NUMBER", "").strip()
        and os.getenv("TWILIO_SMS_ALLOWLIST", "").strip()
    )


def e164_allowlist(raw: str | None) -> frozenset[str]:
    """Exact E.164 entries. Non-E.164 tokens never become sendable destinations."""
    allowed: set[str] = set()
    for part in (raw or "").split(","):
        entry = part.strip()
        if _E164_RE.fullmatch(entry):
            allowed.add(entry)
    return frozenset(allowed)


def sms_send_refusal(
    arguments: dict[str, Any] | None,
    *,
    allowlist_raw: str,
    from_number: str,
) -> tuple[FailureClass, str] | None:
    """Refuse a send before any network call. One destination, exact allowlist match."""
    payload = arguments if isinstance(arguments, dict) else {}
    destination = payload.get("to")
    if isinstance(destination, (list, tuple)):
        return FailureClass.POLICY_REFUSAL, "sms.send accepts one allowlisted destination"
    if not isinstance(destination, str) or destination not in e164_allowlist(allowlist_raw):
        return FailureClass.POLICY_REFUSAL, "sms.send destination is not an allowlisted E.164 number"
    sender = (from_number or "").strip()
    if not _E164_RE.fullmatch(sender):
        return FailureClass.POLICY_REFUSAL, "Twilio from number is not an E.164 number"
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        return FailureClass.TOOL_FAILURE, "sms.send requires a message body"
    if len(body) > MAX_SMS_BODY:
        return FailureClass.TOOL_FAILURE, "sms.send body is too long"
    return None


def _scrub_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


class TwilioSmsToolProvider(ToolProvider):
    """Opt-in single-destination SMS. Voice and mass-blast are intentionally absent."""

    provider_id = "twilio"

    def __init__(
        self,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        allowlist: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._account_sid = (
            account_sid if account_sid is not None else os.getenv("TWILIO_ACCOUNT_SID", "")
        ).strip()
        self._auth_token = (
            auth_token if auth_token is not None else os.getenv("TWILIO_AUTH_TOKEN", "")
        ).strip()
        self._from_number = (
            from_number if from_number is not None else os.getenv("TWILIO_FROM_NUMBER", "")
        ).strip()
        self._allowlist_raw = (
            allowlist if allowlist is not None else os.getenv("TWILIO_SMS_ALLOWLIST", "")
        ).strip()
        self._base_url = (
            base_url if base_url is not None else os.getenv("TWILIO_API_BASE_URL", DEFAULT_TWILIO_BASE_URL)
        ).rstrip("/")
        self.transport = transport

    def configured(self) -> bool:
        return bool(self._account_sid and self._auth_token and self._from_number and self._allowlist_raw)

    def list_tools(self) -> list[ToolSpec]:
        if not self.configured():
            return []
        return [
            ToolSpec(
                name=SMS_SEND,
                description="Send one SMS to an allowlisted E.164 destination. Requires human approval.",
                provider=self.provider_id,
                permissions=["twilio", "network", "sms"],
                risk_class="external_side_effect",
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
                        "body": {"type": "string", "maxLength": MAX_SMS_BODY},
                    },
                    "required": ["to", "body"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "message_sid": {"type": "string"},
                        "to": {"type": "string"},
                        "from": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
            )
        ]

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self.configured():
            raise ToolError("Twilio SMS is not configured", FailureClass.TOOL_MISSING)
        if call.name != SMS_SEND:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        arguments = require_arguments(call.arguments)
        blocked = sms_send_refusal(
            arguments,
            allowlist_raw=self._allowlist_raw,
            from_number=self._from_number,
        )
        if blocked is not None:
            failure_class, message = blocked
            raise ToolError(message, failure_class)
        output = await self._send(str(arguments["to"]), str(arguments["body"]))
        return ToolResult(
            name=call.name,
            call_id=call.call_id,
            ok=True,
            output=output,
            provider=self.provider_id,
        )

    async def health(self) -> ToolHealth:
        if not self.configured():
            return ToolHealth(
                provider=self.provider_id,
                status="unconfigured",
                detail="Twilio SMS is not configured",
            )
        return ToolHealth(
            provider=self.provider_id,
            status="healthy",
            detail="Twilio SMS credentials are present; voice is disabled. Live Twilio was not contacted.",
            tools=[SMS_SEND],
        )

    async def _send(self, destination: str, body: str) -> dict[str, Any]:
        url = f"{self._base_url}/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TWILIO_TIMEOUT, connect=5.0),
                trust_env=False,
                transport=self.transport,
                auth=(self._account_sid, self._auth_token),
            ) as client:
                response = await client.post(
                    url,
                    data={"To": destination, "From": self._from_number, "Body": body},
                )
        except httpx.TimeoutException:
            raise ToolError("Twilio request timed out", FailureClass.TIMEOUT) from None
        except httpx.RequestError:
            raise ToolError("Could not reach Twilio", FailureClass.PROVIDER_OUTAGE) from None
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
        return self._public_message(payload)

    def _public_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        message_sid = payload.get("sid")
        if not isinstance(message_sid, str) or not message_sid.startswith("SM"):
            raise ToolError("Twilio returned an invalid message", FailureClass.TOOL_FAILURE)
        output = {
            "message_sid": message_sid,
            "to": payload.get("to") if isinstance(payload.get("to"), str) else None,
            "from": payload.get("from") if isinstance(payload.get("from"), str) else None,
            "status": payload.get("status") if isinstance(payload.get("status"), str) else None,
        }
        secrets = (self._account_sid, self._auth_token)
        scrubbed: dict[str, Any] = {}
        for key, value in output.items():
            if str(key).lower() in _SECRET_MARKERS:
                continue
            scrubbed[key] = _scrub_text(value, secrets) if isinstance(value, str) else value
        rendered = " ".join(str(item) for item in scrubbed.values())
        if any(secret and secret in rendered for secret in secrets):
            raise ToolError("Twilio result included a credential", FailureClass.TOOL_FAILURE)
        return scrubbed
