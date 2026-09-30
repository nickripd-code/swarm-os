"""Opt-in x402 PaymentProvider seed.

Live spend is unconfigured unless every required environment variable is set:

- ``SWARM_LIVE_PAYMENTS`` is ``1`` / ``true`` / ``yes`` / ``on``
- ``SWARM_X402_API_KEY`` is non-empty
- ``SWARM_X402_ENDPOINT`` is an ``https`` URL with no userinfo, query, or fragment
- ``SWARM_X402_MERCHANT_ALLOWLIST`` contains at least one payTo address or merchant token

Optional ``SWARM_X402_OBJECTIVE_CAP_USD`` can only tighten the mission budget.
A present but invalid cap leaves x402 unconfigured. Partial env stays
unconfigured and must not be reported as a simulated success.

This seed does not read wallet private keys and does not sign EIP-3009
payloads. After the runtime's one-shot approval it POSTs the approved intent
to the configured endpoint. A facilitator that expects a signed payload will
reject the call and this process fails closed. Health does not open a socket.

Never log or return the API key.
"""
from __future__ import annotations

import os
import re
from decimal import Decimal
from urllib.parse import urlsplit

import httpx

from .models import FailureClass, Mission, MissionAnswer, PaymentIntent
from .payments import PaymentError, PaymentHealth, PaymentProvider
from .policy import TRUE_ENV, PolicyError, interpret_approval

_SECRET_RE = re.compile(
    r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+|whsec_[A-Za-z0-9]+|bearer\s+[A-Za-z0-9._\-]+",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_PRIVATE_KEY_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
_MERCHANT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,80}$")
_TX_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
_PAY_ID_RE = re.compile(r"^x402_[A-Za-z0-9]{8,64}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_PAN_RE = re.compile(r"\d{13,19}")
_SUCCESS_STATUSES = frozenset({"settled", "submitted"})
_KNOWN_STATUSES = _SUCCESS_STATUSES | frozenset({"required", "failed", "rejected"})
_DEFAULT_NETWORK = "eip155:8453"


def redact_payment_text(message: str, secret: str = "") -> str:
    """Remove secret-shaped substrings. Safe to put in errors and stored reasons."""
    redacted = _SECRET_RE.sub("[redacted]", message or "")
    redacted = _PAN_RE.sub("[redacted]", redacted)
    token = (secret or "").strip()
    if token and token in redacted:
        redacted = redacted.replace(token, "[redacted]")
    return redacted


def _merchant_ok(token: str) -> bool:
    if _PRIVATE_KEY_RE.fullmatch(token) or _PAN_RE.fullmatch(token):
        return False
    if _SECRET_RE.search(token):
        return False
    if _ADDRESS_RE.fullmatch(token):
        return True
    return _MERCHANT_RE.fullmatch(token) is not None


def allowlist_from_env() -> frozenset[str]:
    raw = os.environ.get("SWARM_X402_MERCHANT_ALLOWLIST", "")
    return frozenset(part.strip() for part in raw.split(",") if _merchant_ok(part.strip()))


def endpoint_from_env() -> str | None:
    """Return the facilitator URL only when it cannot carry the API key."""
    raw = os.environ.get("SWARM_X402_ENDPOINT", "").strip()
    key = os.environ.get("SWARM_X402_API_KEY", "").strip()
    if not raw or len(raw) > 300 or (key and key in raw):
        return None
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    return raw


def objective_cap_dollars() -> Decimal | None:
    """Optional tighter cap. Invalid values raise; empty means no extra cap."""
    raw = os.environ.get("SWARM_X402_OBJECTIVE_CAP_USD", "").strip()
    if not raw:
        return None
    try:
        dec = Decimal(raw)
    except Exception:
        raise PaymentError("x402 objective cap is invalid", FailureClass.AUTHORIZATION_REQUIRED) from None
    if not dec.is_finite() or dec < 0 or dec != dec.quantize(Decimal("0.01")):
        raise PaymentError("x402 objective cap is invalid", FailureClass.AUTHORIZATION_REQUIRED)
    return dec


def x402_live_opt_in() -> bool:
    """True only when every required flag is present. Does not return secrets."""
    flag = os.environ.get("SWARM_LIVE_PAYMENTS", "").strip().lower()
    if flag not in TRUE_ENV:
        return False
    if not os.environ.get("SWARM_X402_API_KEY", "").strip():
        return False
    if endpoint_from_env() is None:
        return False
    if not allowlist_from_env():
        return False
    try:
        objective_cap_dollars()
    except PaymentError:
        return False
    return True


def idempotency_key_ok(key: str | None) -> str:
    token = (key or "").strip()
    if not _IDEMPOTENCY_RE.fullmatch(token) or _SECRET_RE.search(token) or _PRIVATE_KEY_RE.fullmatch(token):
        raise PaymentError("Live payment requires an idempotency key", FailureClass.INVALID_OUTPUT)
    return token


def live_payment_question(amount: float, recipient: str, idempotency_key: str) -> str:
    dec = Decimal(str(amount)).quantize(Decimal("0.01"))
    return (
        f"Approve live x402 payment {format(dec, 'f')} USDC to {recipient} "
        f"for idempotency {idempotency_key}? Reply approve or deny."
    )


def matching_live_approval(mission: Mission, idempotency_key: str) -> MissionAnswer | None:
    """Return the approval that covers this charge key only."""
    needle = f"for idempotency {idempotency_key}?"
    for item in reversed(mission.answers):
        if item.kind != "approval" or item.approval_action != "live_payment":
            continue
        if needle not in (item.question or ""):
            continue
        return item
    return None


def assert_destination_allowed(recipient: str) -> str:
    token = (recipient or "").strip()
    if token not in allowlist_from_env():
        raise PaymentError("Payment destination is not allowlisted", FailureClass.POLICY_REFUSAL)
    return token


def exceeds_objective_cap(amount: float, spent: float) -> bool:
    cap = objective_cap_dollars()
    if cap is None:
        return False
    charge = Decimal(str(amount))
    total = Decimal(str(spent)) + charge
    return charge > cap or total > cap


def _money_amount(amount: float) -> str:
    try:
        dec = Decimal(str(amount))
    except Exception:
        raise PaymentError("Payment amount is invalid", FailureClass.INVALID_OUTPUT) from None
    if not dec.is_finite() or dec <= 0 or dec != dec.quantize(Decimal("0.01")):
        raise PaymentError("Payment amount must be whole cents", FailureClass.INVALID_OUTPUT)
    if dec > Decimal("999999.99"):
        raise PaymentError("Payment amount is invalid", FailureClass.INVALID_OUTPUT)
    return format(dec.quantize(Decimal("0.01")), "f")


def _classify_status(status: int) -> PaymentError:
    if status in {401, 403}:
        return PaymentError("x402 rejected the API key", FailureClass.AUTHORIZATION_REQUIRED)
    if status == 429:
        return PaymentError("x402 quota or rate limit reached", FailureClass.RATE_LIMIT)
    if status == 408:
        return PaymentError("x402 request timed out", FailureClass.TIMEOUT)
    if status == 402:
        return PaymentError("x402 payment was not accepted", FailureClass.RESOURCE_EXHAUSTED)
    if status in {500, 502, 503, 504}:
        return PaymentError("x402 is unavailable", FailureClass.PROVIDER_OUTAGE)
    if status in {400, 422}:
        return PaymentError("x402 rejected the payment request", FailureClass.INVALID_OUTPUT)
    return PaymentError("x402 rejected the payment", FailureClass.AUTHORIZATION_REQUIRED)


def build_x402_client(api_key: str) -> httpx.AsyncClient:
    """Production client. Tests inject their own transport and never call this."""
    del api_key
    return httpx.AsyncClient(timeout=20.0, follow_redirects=False)


class X402PaymentProvider(PaymentProvider):
    """Live x402 adapter. Settles only after the runtime's human approval.

    Missing approval, a denied approval, a missing idempotency key, an
    over-cap amount, or a destination outside the allowlist never opens a
    socket. One approval question names one idempotency key.
    """

    provider_id = "x402"
    mode = "live"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        allowlist: frozenset[str],
        objective_cap: Decimal | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        merchants = frozenset(token for token in allowlist if _merchant_ok(token))
        cap_ok = objective_cap is None or (
            isinstance(objective_cap, Decimal)
            and objective_cap.is_finite()
            and objective_cap >= 0
            and objective_cap == objective_cap.quantize(Decimal("0.01"))
        )
        url = (endpoint or "").strip()
        parsed = urlsplit(url) if url else None
        url_ok = bool(
            parsed
            and parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and (not (api_key or "").strip() or (api_key or "").strip() not in url)
        )
        self._ready = bool((api_key or "").strip()) and url_ok and bool(merchants) and cap_ok
        self._api_key = (api_key or "").strip() if self._ready else ""
        self._endpoint = url if self._ready else ""
        self._allowlist = merchants if self._ready else frozenset()
        self._objective_cap = objective_cap if self._ready and cap_ok else None
        self._client = client if self._ready else None

    def __repr__(self) -> str:
        return f"X402PaymentProvider(configured={self.configured()}, merchants={len(self._allowlist)})"

    def configured(self) -> bool:
        return self._ready

    def spend_enabled(self) -> bool:
        return self._ready

    @classmethod
    def from_env(cls, client: httpx.AsyncClient | None = None) -> X402PaymentProvider:
        if not x402_live_opt_in():
            return cls(api_key="", endpoint="", allowlist=frozenset())
        try:
            cap = objective_cap_dollars()
        except PaymentError:
            return cls(api_key="", endpoint="", allowlist=frozenset())
        return cls(
            api_key=os.environ.get("SWARM_X402_API_KEY", ""),
            endpoint=endpoint_from_env() or "",
            allowlist=allowlist_from_env(),
            objective_cap=cap,
            client=client,
        )

    async def health(self) -> PaymentHealth:
        ready = self.configured()
        return PaymentHealth(
            provider=self.provider_id,
            mode="live",
            status="healthy" if ready else "unconfigured",
            configured=ready,
            spend_enabled=ready,
            detail=(
                "x402 is configured; each charge still needs approval, caps, and an allowlisted merchant"
                if ready else "x402 live payments are not configured"
            ),
        )

    async def pay(self, intent: PaymentIntent, mission: Mission) -> PaymentIntent:
        if not self.configured():
            raise PaymentError("Live wallet provider is not configured", FailureClass.AUTHORIZATION_REQUIRED)
        if not mission.live_payments:
            raise PaymentError("Live payments are not enabled for this mission", FailureClass.POLICY_REFUSAL)
        if mission.privacy == "local_only":
            raise PaymentError("local_only policy forbids live payments", FailureClass.POLICY_REFUSAL)
        key = idempotency_key_ok(intent.idempotency_key)
        destination = self._check_destination(intent.recipient)
        amount = self._check_caps(intent, mission)
        self._check_approval(mission, key)
        asset = (intent.asset or "").strip().lower()
        if asset not in {"usdc", "usd"}:
            raise PaymentError("x402 seed settles USDC amounts only", FailureClass.CAPABILITY_MISMATCH)
        reference, result_status = await self._settle(
            amount=amount,
            destination=destination,
            idempotency_key=key,
            mission_id=str(mission.id),
            reason=redact_payment_text(intent.reason, self._api_key)[:200],
        )
        intent.asset = "usdc"
        intent.chain = "x402"
        intent.reason = redact_payment_text(intent.reason, self._api_key)[:200]
        intent.status = "succeeded" if result_status == "settled" else "submitted"
        intent.transaction_hash = reference
        return intent

    def _check_destination(self, recipient: str) -> str:
        token = (recipient or "").strip()
        if token not in self._allowlist:
            raise PaymentError("Payment destination is not allowlisted", FailureClass.POLICY_REFUSAL)
        return token

    def _check_caps(self, intent: PaymentIntent, mission: Mission) -> str:
        amount = _money_amount(intent.amount)
        charge = Decimal(amount)
        if charge > Decimal(str(mission.limits.max_payment_amount)):
            raise PaymentError("Payment exceeds mission budget or payment cap", FailureClass.RESOURCE_EXHAUSTED)
        if Decimal(str(mission.spent)) + charge > Decimal(str(mission.budget)):
            raise PaymentError("Payment exceeds mission budget or payment cap", FailureClass.RESOURCE_EXHAUSTED)
        if self._objective_cap is not None and (
            charge > self._objective_cap or Decimal(str(mission.spent)) + charge > self._objective_cap
        ):
            raise PaymentError("Payment exceeds mission budget or payment cap", FailureClass.RESOURCE_EXHAUSTED)
        return amount

    def _check_approval(self, mission: Mission, key: str) -> None:
        record = matching_live_approval(mission, key)
        if record is None:
            raise PaymentError("Live payment requires human approval", FailureClass.AUTHORIZATION_REQUIRED)
        try:
            interpret_approval(record.answer)
        except PolicyError as exc:
            raise PaymentError(redact_payment_text(str(exc), self._api_key), exc.failure_class) from None

    async def _settle(
        self,
        *,
        amount: str,
        destination: str,
        idempotency_key: str,
        mission_id: str,
        reason: str,
    ) -> tuple[str, str]:
        payload = {
            "x402Version": 1,
            "scheme": "exact",
            "network": _DEFAULT_NETWORK,
            "payTo": destination,
            "asset": "USDC",
            "amount": amount,
            "idempotencyKey": idempotency_key,
            "missionId": mission_id,
            "reason": reason,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": idempotency_key,
            "PAYMENT-PROTOCOL": "x402",
            "Content-Type": "application/json",
        }
        try:
            if self._client is not None:
                response = await self._client.post(self._endpoint, json=payload, headers=headers)
            else:
                async with build_x402_client(self._api_key) as client:
                    response = await client.post(self._endpoint, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise PaymentError("x402 request timed out", FailureClass.TIMEOUT) from None
        except httpx.HTTPError:
            raise PaymentError("x402 is unavailable", FailureClass.PROVIDER_OUTAGE) from None
        except Exception:
            raise PaymentError("x402 payment failed", FailureClass.PROVIDER_OUTAGE) from None
        if response.status_code != 200:
            raise _classify_status(response.status_code)
        try:
            body = response.json()
        except Exception:
            raise PaymentError("x402 returned an invalid payment reference", FailureClass.INVALID_OUTPUT) from None
        return _accepted_reference(body, amount=amount, destination=destination, secret=self._api_key)


def _accepted_reference(body: object, *, amount: str, destination: str, secret: str) -> tuple[str, str]:
    if not isinstance(body, dict) or body.get("success") is not True:
        raise PaymentError("x402 payment was not completed", FailureClass.AUTHORIZATION_REQUIRED)
    status = body.get("status", "settled")
    reference = body.get("transaction") or body.get("txHash") or body.get("paymentId")
    echoed_amount = body.get("amount")
    echoed_to = body.get("payTo")
    if not isinstance(status, str) or not isinstance(reference, str):
        raise PaymentError("x402 returned an invalid payment reference", FailureClass.INVALID_OUTPUT)
    if status not in _KNOWN_STATUSES or status not in _SUCCESS_STATUSES:
        raise PaymentError("x402 payment was not completed", FailureClass.AUTHORIZATION_REQUIRED)
    if not (_TX_RE.fullmatch(reference) or _PAY_ID_RE.fullmatch(reference)):
        raise PaymentError("x402 returned an invalid payment reference", FailureClass.INVALID_OUTPUT)
    if secret and secret in reference:
        raise PaymentError("x402 returned an invalid payment reference", FailureClass.INVALID_OUTPUT)
    if echoed_amount is not None and str(echoed_amount) != amount:
        raise PaymentError("x402 payment was not completed", FailureClass.AUTHORIZATION_REQUIRED)
    if echoed_to is not None and str(echoed_to) != destination:
        raise PaymentError("x402 payment was not completed", FailureClass.AUTHORIZATION_REQUIRED)
    return reference, status
