"""PaymentProvider seam behind WalletAdapter.

Production stays simulated. Live settlement is a reserved interface and
fails closed until an isolated wallet service exists outside this process.
Never load, log, or return payment credentials.
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
    """Live spend is not enabled in this slice. Do not probe payment-secret env vars."""
    return False


def build_payment_provider() -> PaymentProvider:
    """Production factory. Always simulated. Never enables live spend."""
    return SimulatedPaymentProvider()


def build_live_payment_provider() -> PaymentProvider:
    """Reserved live factory. Always the unconfigured fail-closed adapter."""
    return UnconfiguredLivePaymentProvider()


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
