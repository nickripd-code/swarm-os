"""PaymentProvider seam behind WalletAdapter.

The default factory stays simulated. Live x402 is selected only by the
live factory when every x402 opt-in variable is present; otherwise live
missions stay unconfigured and fail closed. Never log or return payment
credentials.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

from .models import FailureClass, Mission, PaymentIntent


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


def live_wallet_configured() -> bool:
    """True only when x402 opt-in is complete. Never returns secret values."""
    from .x402_payments import x402_live_opt_in
    return x402_live_opt_in()


def build_payment_provider() -> PaymentProvider:
    """Default production factory. Always simulated, even if x402 flags are set."""
    return SimulatedPaymentProvider()


def build_live_payment_provider() -> PaymentProvider:
    """Live factory. x402 only when every opt-in flag is set; otherwise fail closed."""
    from .x402_payments import X402PaymentProvider, x402_live_opt_in
    if not x402_live_opt_in():
        return UnconfiguredLivePaymentProvider()
    provider = X402PaymentProvider.from_env()
    if not provider.configured():
        return UnconfiguredLivePaymentProvider()
    return provider


def resolve_payment_provider(
    mission: Mission,
    *,
    override: PaymentProvider | None = None,
) -> PaymentProvider:
    """Simulated by default. Live missions use the live factory, never an injected spender."""
    if mission.live_payments:
        return build_live_payment_provider()
    if override is not None and override.mode == "simulated":
        return override
    return SimulatedPaymentProvider()
