"""PaymentProvider seam behind WalletAdapter.

Production stays simulated. The agent process never selects a live provider.

Stripe is an extra-flagged seed behind ``build_live_payment_provider`` only.
Live spend is constructed only when all of these are set:

- ``SWARM_LIVE_PAYMENTS`` is ``1`` / ``true`` / ``yes`` / ``on``
- ``STRIPE_SECRET_KEY`` is non-empty
- ``SWARM_STRIPE_MERCHANT_ALLOWLIST`` has at least one merchant id

Optional ``SWARM_STRIPE_OBJECTIVE_CAP_USD`` can only tighten the mission budget.
Partial or invalid env stays ``UnconfiguredLivePaymentProvider``
(``AUTHORIZATION_REQUIRED``). A configured Stripe charge still needs an
idempotency key, a usd amount inside the mission caps, an allowlisted
destination, and PolicyGate ``approval_required`` before any client call.
Card numbers, secret keys, and payment tokens are never returned.

``build_payment_provider`` and ``resolve_payment_provider`` ignore those flags.
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel

from .models import FailureClass, Mission, PaymentIntent
from .policy import TRUE_ENV, PolicyError, PolicyGate, PolicyRequest, parse_approval_answer


class PaymentError(Exception):
    """Safe payment failure. Messages must never contain credentials or secrets."""

    def __init__(self, message: str, failure_class: FailureClass = FailureClass.AUTHORIZATION_REQUIRED):
        super().__init__(message)
        self.failure_class = failure_class


class PaymentHealth(BaseModel):
    provider: str
    mode: Literal["simulated", "live"]
    status: Literal["healthy", "unconfigured", "unavailable"]
    configured: bool
    spend_enabled: bool
    detail: str | None = None


class PaymentProvider(ABC):
    """Provider-neutral payment API owned by Swarm OS.

    A future live adapter (Stripe, x402, isolated wallet) implements this
    contract. Keys and signing material must stay outside the agent process.
    """

    provider_id: str
    mode: Literal["simulated", "live"]

    def configured(self) -> bool:
        return False

    def spend_enabled(self) -> bool:
        return False

    @abstractmethod
    async def health(self) -> PaymentHealth:
        raise NotImplementedError

    @abstractmethod
    async def pay(self, intent: PaymentIntent, mission: Mission) -> PaymentIntent:
        raise NotImplementedError


class SimulatedPaymentProvider(PaymentProvider):
    """Default adapter. Records a simulated intent; never contacts a network or wallet."""

    provider_id = "simulated"
    mode: Literal["simulated", "live"] = "simulated"

    def configured(self) -> bool:
        return True

    async def health(self) -> PaymentHealth:
        return PaymentHealth(
            provider=self.provider_id,
            mode=self.mode,
            status="healthy",
            configured=True,
            spend_enabled=False,
            detail="Simulated payments only; no live settlement",
        )

    async def pay(self, intent: PaymentIntent, mission: Mission) -> PaymentIntent:
        if mission.live_payments:
            raise PaymentError(
                "Simulated provider cannot settle live payments",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        intent.status = "simulated"
        intent.transaction_hash = None
        return intent


class UnconfiguredLivePaymentProvider(PaymentProvider):
    """Reserved live seam. Always unconfigured; never spends."""

    provider_id = "live-unconfigured"
    mode: Literal["simulated", "live"] = "live"

    async def health(self) -> PaymentHealth:
        return PaymentHealth(
            provider=self.provider_id,
            mode=self.mode,
            status="unconfigured",
            configured=False,
            spend_enabled=False,
            detail="Live wallet provider is not configured",
        )

    async def pay(self, intent: PaymentIntent, mission: Mission) -> PaymentIntent:
        del intent, mission
        raise PaymentError("Live wallet provider is not configured", FailureClass.AUTHORIZATION_REQUIRED)


_SECRET_RE = re.compile(
    r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9_]+|whsec_[A-Za-z0-9_]+",
    re.IGNORECASE,
)
_MERCHANT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,80}$")
_PI_RE = re.compile(r"^pi_[A-Za-z0-9]+$")
_STRIPE_MAX_CENTS = 99_999_999
_CHARGE_STATUSES = frozenset({"succeeded", "processing", "requires_capture"})
_KNOWN_STATUSES = _CHARGE_STATUSES | frozenset({
    "requires_payment_method", "requires_confirmation", "requires_action", "canceled",
})


def _looks_sensitive(value: str) -> bool:
    text = (value or "").strip()
    if not text or _SECRET_RE.search(text):
        return bool(text)
    compact = re.sub(r"[\s-]", "", text)
    return bool(re.fullmatch(r"\d{13,19}", compact))


def _safe_text(message: str) -> str:
    redacted = _SECRET_RE.sub("[redacted]", message or "")
    return re.sub(r"\b\d{13,19}\b", "[redacted]", redacted)


def _money_cents(amount: float, *, allow_zero: bool) -> int:
    try:
        dec = Decimal(str(amount))
    except Exception:
        raise PaymentError("Payment amount is invalid", FailureClass.INVALID_OUTPUT) from None
    if not dec.is_finite() or dec != dec.quantize(Decimal("0.01")):
        raise PaymentError("Payment amount must be whole cents", FailureClass.INVALID_OUTPUT)
    cents = int(dec.quantize(Decimal("0.01")) * 100)
    if cents < 0 or cents > _STRIPE_MAX_CENTS or (cents == 0 and not allow_zero):
        raise PaymentError("Payment amount is invalid", FailureClass.INVALID_OUTPUT)
    return cents


def _allowlist_from_env() -> frozenset[str]:
    raw = os.environ.get("SWARM_STRIPE_MERCHANT_ALLOWLIST", "")
    found: list[str] = []
    for part in raw.split(","):
        token = part.strip()
        if _MERCHANT_RE.fullmatch(token) and not _looks_sensitive(token):
            found.append(token)
    return frozenset(found)


def _objective_cap_cents() -> int | None:
    """Return the optional tighter cap, or raise when the env value is unusable."""
    raw = os.environ.get("SWARM_STRIPE_OBJECTIVE_CAP_USD", "").strip()
    if not raw:
        return None
    try:
        dec = Decimal(raw)
    except Exception:
        raise PaymentError("Stripe objective cap is invalid", FailureClass.AUTHORIZATION_REQUIRED) from None
    if not dec.is_finite() or dec < 0 or dec != dec.quantize(Decimal("0.01")):
        raise PaymentError("Stripe objective cap is invalid", FailureClass.AUTHORIZATION_REQUIRED)
    return int(dec.quantize(Decimal("0.01")) * 100)


def stripe_live_opt_in() -> bool:
    """True only when every live-spend flag is present. Does not return secrets."""
    flag = os.environ.get("SWARM_LIVE_PAYMENTS", "").strip().lower()
    if flag not in TRUE_ENV:
        return False
    if not os.environ.get("STRIPE_SECRET_KEY", "").strip():
        return False
    if not _allowlist_from_env():
        return False
    try:
        _objective_cap_cents()
    except PaymentError:
        return False
    return True


def live_wallet_configured() -> bool:
    """True only for the explicit Stripe opt-in. Never returns secret values."""
    return stripe_live_opt_in()


@dataclass(frozen=True)
class StripeChargeResult:
    """Public charge reference. Never includes client secrets or card data."""

    id: str
    status: str


class StripeChargeClient(Protocol):
    async def create_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        destination: str,
        idempotency_key: str,
        mission_id: str,
        reason: str,
    ) -> StripeChargeResult:
        """Create one Stripe PaymentIntent. Implementations must not log credentials."""


class HttpxStripeClient:
    """Real Stripe HTTP client. Tests inject a fake instead of constructing this."""

    def __init__(self, api_key: str):
        self._api_key = api_key.strip()

    def __repr__(self) -> str:
        return "HttpxStripeClient(configured=True)"

    async def create_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        destination: str,
        idempotency_key: str,
        mission_id: str,
        reason: str,
    ) -> StripeChargeResult:
        if not self._api_key:
            raise PaymentError("Live wallet provider is not configured", FailureClass.AUTHORIZATION_REQUIRED)
        import httpx

        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
                response = await client.post(
                    "https://api.stripe.com/v1/payment_intents",
                    data={
                        "amount": str(amount_cents),
                        "currency": currency,
                        "description": reason,
                        "metadata[mission_id]": mission_id,
                        "metadata[destination]": destination,
                        **(
                            {"transfer_data[destination]": destination}
                            if destination.startswith("acct_") else {}
                        ),
                    },
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Idempotency-Key": idempotency_key,
                    },
                )
        except httpx.TimeoutException:
            raise PaymentError("Stripe request timed out", FailureClass.TIMEOUT) from None
        except httpx.HTTPError:
            raise PaymentError("Stripe request failed", FailureClass.PROVIDER_OUTAGE) from None
        if response.status_code != 200:
            raise PaymentError("Stripe refused the charge", FailureClass.AUTHORIZATION_REQUIRED)
        try:
            body = response.json()
        except Exception:
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT) from None
        pi = body.get("id") if isinstance(body, dict) else None
        status = body.get("status") if isinstance(body, dict) else None
        if not isinstance(pi, str) or not isinstance(status, str):
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT)
        return StripeChargeResult(id=pi, status=status)


@dataclass
class _LedgerEntry:
    state: Literal["parked", "denied", "charged", "failed"]
    intent: PaymentIntent | None
    message: str
    failure_class: FailureClass


class StripePaymentProvider(PaymentProvider):
    """Live Stripe adapter. Charges only after PolicyGate approval.

    The default factories never return this. Callers that opt in still cannot
    settle without an allowlisted destination, caps, an idempotency key, and
    an explicit approve. Deny and missing approval do not call Stripe.
    """

    provider_id = "stripe"
    mode: Literal["simulated", "live"] = "live"

    def __init__(
        self,
        *,
        api_key: str,
        allowlist: frozenset[str],
        client: StripeChargeClient | None = None,
        objective_cap_cents: int | None = None,
        gate: PolicyGate | None = None,
    ):
        merchants = frozenset(
            token for token in allowlist if _MERCHANT_RE.fullmatch(token) and not _looks_sensitive(token)
        )
        cap_ok = objective_cap_cents is None or (
            isinstance(objective_cap_cents, int) and 0 <= objective_cap_cents <= _STRIPE_MAX_CENTS
        )
        self._ready = bool(api_key.strip()) and bool(merchants) and cap_ok
        self._allowlist = merchants
        self._client = client if self._ready else None
        self._objective_cap_cents = objective_cap_cents if cap_ok else None
        self._gate = gate or PolicyGate()
        self._records: dict[tuple[str, str], _LedgerEntry] = {}
        self._decisions: dict[tuple[str, str], Literal["approve", "deny"]] = {}
        self._charged_cents: dict[str, int] = {}
        self._inflight: set[tuple[str, str]] = set()

    def __repr__(self) -> str:
        return f"StripePaymentProvider(configured={self.configured()}, merchants={len(self._allowlist)})"

    def configured(self) -> bool:
        return self._ready and self._client is not None

    def spend_enabled(self) -> bool:
        return self.configured()

    @classmethod
    def from_env(cls) -> StripePaymentProvider:
        key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        try:
            cap = _objective_cap_cents()
        except PaymentError:
            cap = -1
        return cls(
            api_key=key,
            allowlist=_allowlist_from_env(),
            client=HttpxStripeClient(key) if key else None,
            objective_cap_cents=cap,
        )

    async def health(self) -> PaymentHealth:
        ready = self.configured()
        return PaymentHealth(
            provider=self.provider_id,
            mode=self.mode,
            status="healthy" if ready else "unconfigured",
            configured=ready,
            spend_enabled=ready,
            detail=(
                "Stripe charges require human approval, caps, and an allowlisted merchant"
                if ready else "Stripe live payments are not configured"
            ),
        )

    def has_pending(self, mission: Mission, idempotency_key: str) -> bool:
        record = self._records.get(self._slot(mission, (idempotency_key or "").strip()))
        return record is not None and record.state == "parked"

    def record_approval(self, mission: Mission, idempotency_key: str, answer: str) -> None:
        """Store a human approve/deny. Does not charge and does not echo the answer."""
        verdict = parse_approval_answer(answer)
        if verdict is None:
            raise PaymentError(
                "Human approval is required; answer must be approve or deny",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        key = (idempotency_key or "").strip()
        if not key:
            raise PaymentError("Live payment requires an idempotency key", FailureClass.INVALID_OUTPUT)
        slot = self._slot(mission, key)
        record = self._records.get(slot)
        if record is not None and record.state == "charged":
            return
        if self._decisions.get(slot) == "deny":
            return
        self._decisions[slot] = verdict

    async def pay(self, intent: PaymentIntent, mission: Mission) -> PaymentIntent:
        if not self.configured():
            raise PaymentError("Live wallet provider is not configured", FailureClass.AUTHORIZATION_REQUIRED)
        key = self._require_key(intent.idempotency_key)
        slot = self._slot(mission, key)
        replay = self._records.get(slot)
        if replay is not None and replay.state == "charged" and replay.intent is not None:
            return replay.intent.model_copy(deep=True)
        if replay is not None and replay.state in {"denied", "failed"}:
            raise PaymentError(replay.message, replay.failure_class)
        self._preflight(intent, mission)
        verdict = self._verdict(mission, slot)
        if verdict is None:
            self._records[slot] = _LedgerEntry(
                state="parked",
                intent=None,
                message="Live payment requires human approval",
                failure_class=FailureClass.AUTHORIZATION_REQUIRED,
            )
            raise PaymentError("Live payment requires human approval", FailureClass.AUTHORIZATION_REQUIRED)
        if verdict == "deny":
            self._records[slot] = _LedgerEntry(
                state="denied",
                intent=None,
                message="Human denied the live payment",
                failure_class=FailureClass.POLICY_REFUSAL,
            )
            raise PaymentError("Human denied the live payment", FailureClass.POLICY_REFUSAL)
        return await self._charge(intent, mission, slot, key)

    def _require_key(self, key: str | None) -> str:
        token = (key or "").strip()
        if not token or len(token) > 255 or _looks_sensitive(token):
            raise PaymentError("Live payment requires an idempotency key", FailureClass.INVALID_OUTPUT)
        return token

    def _slot(self, mission: Mission, key: str) -> tuple[str, str]:
        return (str(mission.id), key)

    def _preflight(self, intent: PaymentIntent, mission: Mission) -> None:
        if mission.privacy == "local_only":
            raise PaymentError("local_only policy forbids live payments", FailureClass.POLICY_REFUSAL)
        if (intent.asset or "").strip().lower() != "usd":
            raise PaymentError("Stripe settles usd only", FailureClass.POLICY_REFUSAL)
        request = PolicyRequest(action="live_payment", mission=mission)
        try:
            self._gate.authorize(request)
        except PolicyError as exc:
            raise PaymentError(_safe_text(str(exc)), exc.failure_class) from None
        if self._gate.approval_required(request) is None:
            raise PaymentError("Live payment requires human approval", FailureClass.AUTHORIZATION_REQUIRED)
        self._check_destination(intent.recipient)
        self._check_caps(intent, mission)

    def _check_destination(self, recipient: str) -> str:
        destination = (recipient or "").strip()
        if destination not in self._allowlist or _looks_sensitive(destination):
            raise PaymentError("Destination is not an allowlisted merchant", FailureClass.POLICY_REFUSAL)
        return destination

    def _check_caps(self, intent: PaymentIntent, mission: Mission) -> int:
        charge = _money_cents(intent.amount, allow_zero=False)
        per_charge = _money_cents(mission.limits.max_payment_amount, allow_zero=True)
        if charge > per_charge:
            raise PaymentError(
                "Payment exceeds mission budget or payment cap",
                FailureClass.RESOURCE_EXHAUSTED,
            )
        ceiling = _money_cents(mission.budget, allow_zero=True)
        if self._objective_cap_cents is not None:
            ceiling = min(ceiling, self._objective_cap_cents)
        spent = _money_cents(mission.spent, allow_zero=True)
        already = self._charged_cents.get(str(mission.id), 0)
        if spent + charge > ceiling or already + charge > ceiling:
            raise PaymentError(
                "Payment exceeds mission budget or payment cap",
                FailureClass.RESOURCE_EXHAUSTED,
            )
        return charge

    def _verdict(self, mission: Mission, slot: tuple[str, str]) -> Literal["approve", "deny"] | None:
        recorded = self._decisions.get(slot)
        if recorded is not None:
            return recorded
        for item in reversed(mission.answers):
            if item.kind == "approval" and item.approval_action == "live_payment":
                return parse_approval_answer(item.answer)
        return None

    async def _charge(
        self,
        intent: PaymentIntent,
        mission: Mission,
        slot: tuple[str, str],
        key: str,
    ) -> PaymentIntent:
        if slot in self._inflight:
            raise PaymentError("Live payment is already in progress", FailureClass.AUTHORIZATION_REQUIRED)
        client = self._client
        if client is None:
            raise PaymentError("Live wallet provider is not configured", FailureClass.AUTHORIZATION_REQUIRED)
        cents = self._check_caps(intent, mission)
        destination = self._check_destination(intent.recipient)
        intent.reason = _safe_text(intent.reason)[:200]
        self._inflight.add(slot)
        try:
            try:
                result = await client.create_payment_intent(
                    amount_cents=cents,
                    currency="usd",
                    destination=destination,
                    idempotency_key=key,
                    mission_id=str(mission.id),
                    reason=_safe_text(intent.reason)[:200],
                )
            except PaymentError as exc:
                raise PaymentError(_safe_text(str(exc)), exc.failure_class) from None
            except Exception:
                raise PaymentError("Stripe charge failed", FailureClass.PROVIDER_OUTAGE) from None
        finally:
            self._inflight.discard(slot)
        self._accept_result(result)
        if result.status not in _CHARGE_STATUSES:
            self._records[slot] = _LedgerEntry(
                state="failed",
                intent=None,
                message="Stripe charge was not completed",
                failure_class=FailureClass.AUTHORIZATION_REQUIRED,
            )
            raise PaymentError("Stripe charge was not completed", FailureClass.AUTHORIZATION_REQUIRED)
        intent.status = "succeeded" if result.status == "succeeded" else "submitted"
        intent.transaction_hash = result.id
        stored = intent.model_copy(deep=True)
        self._records[slot] = _LedgerEntry(
            state="charged",
            intent=stored,
            message="",
            failure_class=FailureClass.UNKNOWN_FAILURE,
        )
        self._charged_cents[str(mission.id)] = self._charged_cents.get(str(mission.id), 0) + cents
        return intent

    def _accept_result(self, result: StripeChargeResult) -> None:
        if not isinstance(result, StripeChargeResult):
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT)
        if not _PI_RE.fullmatch(result.id) or result.status not in _KNOWN_STATUSES:
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT)
        if _looks_sensitive(result.id) or _looks_sensitive(result.status):
            raise PaymentError("Stripe returned an invalid charge reference", FailureClass.INVALID_OUTPUT)


def build_payment_provider() -> PaymentProvider:
    """Default production factory. Always simulated, even if Stripe flags are set."""
    return SimulatedPaymentProvider()


def build_live_payment_provider() -> PaymentProvider:
    """Explicit live factory. Stripe only when every opt-in flag is set."""
    if not stripe_live_opt_in():
        return UnconfiguredLivePaymentProvider()
    provider = StripePaymentProvider.from_env()
    if not provider.configured():
        return UnconfiguredLivePaymentProvider()
    return provider


def resolve_payment_provider(
    mission: Mission,
    *,
    override: PaymentProvider | None = None,
) -> PaymentProvider:
    """Choose a provider for this mission. Live spend is never selected here."""
    if mission.live_payments:
        return UnconfiguredLivePaymentProvider()
    if override is not None and override.mode == "simulated":
        return override
    return SimulatedPaymentProvider()
