"""Opt-in Stripe PaymentProvider seed.

Live spend is unconfigured unless every required environment variable is set:

- ``SWARM_LIVE_PAYMENTS`` is ``1`` / ``true`` / ``yes`` / ``on``
- ``STRIPE_SECRET_KEY`` is non-empty
- ``SWARM_STRIPE_MERCHANT_ALLOWLIST`` contains at least one merchant token

Optional ``SWARM_STRIPE_OBJECTIVE_CAP_USD`` can only tighten the mission budget.
A present but invalid cap leaves Stripe unconfigured. Partial env stays
unconfigured. ``STRIPE_WEBHOOK_SECRET``, publishable keys, and wallet private
keys do not opt in.

This module never logs or returns secret material. Health does not call Stripe.
"""
from __future__ import annotations

import os
import re
from decimal import Decimal

import httpx

from .models import FailureClass, Mission, MissionAnswer, PaymentIntent
from .payments import PaymentError, PaymentHealth, PaymentProvider
from .policy import TRUE_ENV, PolicyError, interpret_approval

_SECRET_RE = re.compile(
    r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+|whsec_[A-Za-z0-9]+",
    re.IGNORECASE,
)
_MERCHANT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,80}$")
_ACCT_RE = re.compile(r"^acct_[A-Za-z0-9]+$")
_PI_RE = re.compile(r"^pi_[A-Za-z0-9]+$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_PAN_RE = re.compile(r"\d{13,19}")
_STRIPE_MAX_CENTS = 99_999_999
_SUCCESS_STATUSES = frozenset({"succeeded", "processing", "requires_capture"})
_KNOWN_STATUSES = _SUCCESS_STATUSES | frozenset({
    "requires_payment_method", "requires_confirmation", "requires_action", "canceled",
})
_STRIPE_URL = "https://api.stripe.com/v1/payment_intents"


def redact_payment_text(message: str) -> str:
    """Remove secret-shaped and card-shaped substrings. Safe to put in errors."""
    redacted = _SECRET_RE.sub("[redacted]", message or "")
    return _PAN_RE.sub("[redacted]", redacted)


def _merchant_ok(token: str) -> bool:
    if not _MERCHANT_RE.fullmatch(token):
        return False
    if _SECRET_RE.search(token) or _PAN_RE.fullmatch(token):
        return False
    return True


def allowlist_from_env() -> frozenset[str]:
    raw = os.environ.get("SWARM_STRIPE_MERCHANT_ALLOWLIST", "")
    return frozenset(part.strip() for part in raw.split(",") if _merchant_ok(part.strip()))


def objective_cap_dollars() -> Decimal | None:
    """Optional tighter cap. Invalid values raise; empty means no extra cap."""
    raw = os.environ.get("SWARM_STRIPE_OBJECTIVE_CAP_USD", "").strip()
    if not raw:
        return None
    try:
        dec = Decimal(raw)
    except Exception:
        raise PaymentError("Stripe objective cap is invalid", FailureClass.AUTHORIZATION_REQUIRED) from None
    if not dec.is_finite() or dec < 0 or dec != dec.quantize(Decimal("0.01")):
        raise PaymentError("Stripe objective cap is invalid", FailureClass.AUTHORIZATION_REQUIRED)
    return dec


def stripe_live_opt_in() -> bool:
    """True only when every required flag is present. Does not return secrets."""
    flag = os.environ.get("SWARM_LIVE_PAYMENTS", "").strip().lower()
    if flag not in TRUE_ENV:
        return False
    if not os.environ.get("STRIPE_SECRET_KEY", "").strip():
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
    if not _IDEMPOTENCY_RE.fullmatch(token) or _SECRET_RE.search(token):
        raise PaymentError("Live payment requires an idempotency key", FailureClass.INVALID_OUTPUT)
    return token


def live_payment_question(amount: float, recipient: str, idempotency_key: str) -> str:
    dec = Decimal(str(amount)).quantize(Decimal("0.01"))
    return (
        f"Approve live payment {format(dec, 'f')} USD to {recipient} "
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


def _money_cents(amount: float) -> int:
    try:
        dec = Decimal(str(amount))
    except Exception:
        raise PaymentError("Payment amount is invalid", FailureClass.INVALID_OUTPUT) from None
    if not dec.is_finite() or dec != dec.quantize(Decimal("0.01")):
        raise PaymentError("Payment amount must be whole cents", FailureClass.INVALID_OUTPUT)
    cents = int(dec.quantize(Decimal("0.01")) * 100)
    if cents <= 0 or cents > _STRIPE_MAX_CENTS:
        raise PaymentError("Payment amount is invalid", FailureClass.INVALID_OUTPUT)
    return cents


def _classify_status(status: int) -> PaymentError:
    if status in {401, 403}:
        return PaymentError("Stripe rejected the API key", FailureClass.AUTHORIZATION_REQUIRED)
    if status == 429:
        return PaymentError("Stripe quota or rate limit reached", FailureClass.RATE_LIMIT)
    if status == 408:
        return PaymentError("Stripe request timed out", FailureClass.TIMEOUT)
    if status == 402:
        return PaymentError("Stripe credits are exhausted", FailureClass.RESOURCE_EXHAUSTED)
    if status in {500, 502, 503, 504}:
        return PaymentError("Stripe is unavailable", FailureClass.PROVIDER_OUTAGE)
    if status in {400, 422}:
        return PaymentError("Stripe rejected the charge request", FailureClass.INVALID_OUTPUT)
    return PaymentError("Stripe rejected the charge", FailureClass.AUTHORIZATION_REQUIRED)


def build_stripe_client(api_key: str) -> httpx.AsyncClient:
    """Production client. Tests inject their own transport and never call this."""
    del api_key
    return httpx.AsyncClient(timeout=20.0, follow_redirects=False)


class StripePaymentProvider(PaymentProvider):
    """Live Stripe adapter. Charges only after the runtime's human approval.

    Missing approval, a denied approval, a missing idempotency key, an
    over-cap amount, or a destination outside the allowlist never opens a
    socket. One approval question names one idempotency key.
    """

    provider_id = "stripe"
    mode = "live"

    def __init__(
        self,
        *,
        api_key: str,
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
        self._ready = bool((api_key or "").strip()) and bool(merchants) and cap_ok
        self._api_key = (api_key or "").strip() if self._ready else ""
        self._allowlist = merchants if self._ready else frozenset()
        self._objective_cap = objective_cap if self._ready and cap_ok else None
        self._client = client if self._ready else None

    def __repr__(self) -> str:
        return f"StripePaymentProvider(configured={self.configured()}, merchants={len(self._allowlist)})"

    def configured(self) -> bool:
        return self._ready

    def spend_enabled(self) -> bool:
        return self._ready

    @classmethod
    def from_env(cls, client: httpx.AsyncClient | None = None) -> StripePaymentProvider:
        if not stripe_live_opt_in():
            return cls(api_key="", allowlist=frozenset())
        try:
            cap = objective_cap_dollars()
        except PaymentError:
            return cls(api_key="", allowlist=frozenset())
        return cls(
            api_key=os.environ.get("STRIPE_SECRET_KEY", ""),
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
                "Stripe is configured; each charge still needs approval, caps, and an allowlisted merchant"
                if ready else "Stripe live payments are not configured"
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
        self._check_caps(intent, mission)
        self._check_approval(intent, mission, key)
        asset = (intent.asset or "").strip().lower()
        if asset not in {"usd", "usdc"}:
            raise PaymentError("Stripe seed settles mission USD amounts only", FailureClass.CAPABILITY_MISMATCH)
        cents = _money_cents(intent.amount)
        result_id, result_status = await self._create_intent(
            amount_cents=cents,
            destination=destination,
            idempotency_key=key,
            mission_id=str(mission.id),
            reason=redact_payment_text(intent.reason)[:200],
        )
        if result_status not in _SUCCESS_STATUSES:
            raise PaymentError("Stripe charge was not completed", FailureClass.AUTHORIZATION_REQUIRED)
        intent.asset = "usd"
        intent.chain = "stripe"
        intent.reason = redact_payment_text(intent.reason)[:200]
        intent.status = "succeeded" if result_status == "succeeded" else "submitted"
        intent.transaction_hash = result_id
        return intent

    def _check_destination(self, recipient: str) -> str:
        token = (recipient or "").strip()
        if token not in self._allowlist:
            raise PaymentError("Payment destination is not allowlisted", FailureClass.POLICY_REFUSAL)
        return token

    def _check_caps(self, intent: PaymentIntent, mission: Mission) -> None:
        cents = _money_cents(intent.amount)
        charge = Decimal(cents) / Decimal(100)
        if charge > Decimal(str(mission.limits.max_payment_amount)):
            raise PaymentError("Payment exceeds mission budget or payment cap", FailureClass.RESOURCE_EXHAUSTED)
        if Decimal(str(mission.spent)) + charge > Decimal(str(mission.budget)):
            raise PaymentError("Payment exceeds mission budget or payment cap", FailureClass.RESOURCE_EXHAUSTED)
        if self._objective_cap is not None and (
            charge > self._objective_cap or Decimal(str(mission.spent)) + charge > self._objective_cap
        ):
            raise PaymentError("Payment exceeds mission budget or payment cap", FailureClass.RESOURCE_EXHAUSTED)

    def _check_approval(self, intent: PaymentIntent, mission: Mission, key: str) -> None:
        del intent
        record = matching_live_approval(mission, key)
        if record is None:
            raise PaymentError("Live payment requires human approval", FailureClass.AUTHORIZATION_REQUIRED)
        try:
            interpret_approval(record.answer)
        except PolicyError as exc:
            raise PaymentError(redact_payment_text(str(exc)), exc.failure_class) from None

    async def _create_intent(
        self,
        *,
        amount_cents: int,
        destination: str,
        idempotency_key: str,
        mission_id: str,
        reason: str,
    ) -> tuple[str, str]:
        data = {
            "amount": str(amount_cents),
            "currency": "usd",
            "description": reason,
            "metadata[mission_id]": mission_id,
            "metadata[destination]": destination,
        }
        if _ACCT_RE.fullmatch(destination):
            data["transfer_data[destination]"] = destination
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": idempotency_key,
        }
        try:
            if self._client is not None:
                response = await self._client.post(_STRIPE_URL, data=data, headers=headers)
            else:
                async with build_stripe_client(self._api_key) as client:
                    response = await client.post(_STRIPE_URL, data=data, headers=headers)
        except httpx.TimeoutException:
            raise PaymentError("Stripe request timed out", FailureClass.TIMEOUT) from None
        except httpx.HTTPError:
            raise PaymentError("Stripe is unavailable", FailureClass.PROVIDER_OUTAGE) from None
        except Exception:
            raise PaymentError("Stripe charge failed", FailureClass.PROVIDER_OUTAGE) from None
        if response.status_code != 200:
            raise _classify_status(response.status_code)
        try:
            body = response.json()
        except Exception:
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT) from None
        pi = body.get("id") if isinstance(body, dict) else None
        status = body.get("status") if isinstance(body, dict) else None
        if not isinstance(pi, str) or not isinstance(status, str):
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT)
        if not _PI_RE.fullmatch(pi) or status not in _KNOWN_STATUSES or _SECRET_RE.search(pi):
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT)
        return pi, status
