from uuid import uuid4

import pytest

from app.models import FailureClass, Mission, PaymentIntent
from app.payments import (
    PaymentError,
    PaymentProvider,
    SimulatedPaymentProvider,
    UnconfiguredLivePaymentProvider,
    build_live_payment_provider,
    build_payment_provider,
    live_wallet_configured,
    resolve_payment_provider,
)
from app.runtime import PolicyError, SwarmRuntime, WalletAdapter
from app.store import Store


def _intent(mission: Mission, amount: float = 1.5) -> PaymentIntent:
    return PaymentIntent(
        mission_id=mission.id,
        recipient="0xabc",
        amount=amount,
        reason="test work",
    )


class StubLivePaymentProvider(PaymentProvider):
    """Test-only live implementation. Production factory never returns this."""

    provider_id = "stub-live"
    mode = "live"

    def __init__(self):
        self.paid = 0

    def configured(self) -> bool:
        return True

    def spend_enabled(self) -> bool:
        return True

    async def health(self):
        return await UnconfiguredLivePaymentProvider().health()

    async def pay(self, intent: PaymentIntent, mission: Mission) -> PaymentIntent:
        self.paid += 1
        intent.status = "submitted"
        intent.transaction_hash = "0xdead"
        return intent


@pytest.mark.asyncio
async def test_simulated_provider_marks_intent_and_never_hashes():
    mission = Mission(goal="pay")
    provider = SimulatedPaymentProvider()
    result = await provider.pay(_intent(mission), mission)
    assert result.status == "simulated"
    assert result.transaction_hash is None
    health = await provider.health()
    assert health.status == "healthy"
    assert health.mode == "simulated"
    assert health.configured is True
    assert health.spend_enabled is False
    dumped = health.model_dump()
    assert "key" not in str(dumped).lower()
    assert "secret" not in str(dumped).lower()


@pytest.mark.asyncio
async def test_simulated_provider_refuses_live_mission():
    mission = Mission(goal="pay", live_payments=True)
    with pytest.raises(PaymentError) as exc:
        await SimulatedPaymentProvider().pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_unconfigured_live_provider_fails_closed():
    mission = Mission(goal="pay", live_payments=True)
    provider = UnconfiguredLivePaymentProvider()
    assert provider.configured() is False
    assert provider.spend_enabled() is False
    health = await provider.health()
    assert health.status == "unconfigured"
    assert health.spend_enabled is False
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert "not configured" in str(exc.value)
    assert "key" not in str(exc.value).lower()


def test_factory_never_enables_live_spend(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_should_never_be_read")
    monkeypatch.setenv("WALLET_PRIVATE_KEY", "0xshould-never-be-read")
    assert live_wallet_configured() is False
    default = build_payment_provider()
    live = build_live_payment_provider()
    assert isinstance(default, SimulatedPaymentProvider)
    assert default.spend_enabled() is False
    assert isinstance(live, UnconfiguredLivePaymentProvider)
    assert live.configured() is False
    assert live.spend_enabled() is False


def test_resolve_keeps_live_fail_closed_even_with_stub_override():
    simulated = Mission(goal="sim")
    live = Mission(goal="live", live_payments=True)
    stub = StubLivePaymentProvider()
    assert isinstance(resolve_payment_provider(simulated), SimulatedPaymentProvider)
    assert isinstance(resolve_payment_provider(simulated, override=SimulatedPaymentProvider()), SimulatedPaymentProvider)
    resolved_live = resolve_payment_provider(live, override=stub)
    assert isinstance(resolved_live, UnconfiguredLivePaymentProvider)
    assert resolved_live.spend_enabled() is False


@pytest.mark.asyncio
async def test_wallet_adapter_simulates_by_default():
    mission = Mission(goal="pay")
    adapter = WalletAdapter()
    result = await adapter.pay(_intent(mission), mission)
    assert result.status == "simulated"
    assert result.transaction_hash is None


@pytest.mark.asyncio
async def test_wallet_adapter_live_raises_policy_error_not_payment_success():
    mission = Mission(goal="pay", live_payments=True)
    with pytest.raises(PolicyError) as exc:
        await WalletAdapter().pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_wallet_adapter_ignores_injected_live_spender():
    mission = Mission(goal="pay", live_payments=True, budget=10, limits={"max_payment_amount": 5})
    stub = StubLivePaymentProvider()
    with pytest.raises(PolicyError) as exc:
        await WalletAdapter(stub).pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert stub.paid == 0


@pytest.mark.asyncio
async def test_runtime_live_payments_do_not_spend_or_emit_success(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = Mission(goal="pay", budget=10, live_payments=True, limits={"max_payment_amount": 5})
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.create_payment(mission, "0xabc", 2, "live attempt")
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    saved = store.get_mission(mission.id)
    assert saved.spent == 0
    events = store.events(mission.id)
    assert not any(e.event_type == "payment.created" for e in events)


@pytest.mark.asyncio
async def test_runtime_simulated_payment_still_enforces_cap(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = Mission(goal="pay", budget=10, limits={"max_payment_amount": 5})
    store.save_mission(mission)
    intent = await runtime.create_payment(mission, "0xabc", 2, "test work")
    assert intent.status == "simulated"
    assert mission.spent == 2
    assert any(e.event_type == "payment.created" for e in store.events(mission.id))
    with pytest.raises(PolicyError) as exc:
        await runtime.create_payment(mission, "0xabc", 6, "too much")
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    assert mission.spent == 2


@pytest.mark.asyncio
async def test_stub_live_provider_is_implementable_but_unused():
    """The live interface exists for a later isolated wallet; this slice does not call it."""
    mission = Mission(goal="pay", live_payments=True, id=uuid4())
    stub = StubLivePaymentProvider()
    direct = await stub.pay(_intent(mission), mission)
    assert direct.status == "submitted"
    assert stub.paid == 1
    resolved = resolve_payment_provider(mission, override=stub)
    assert isinstance(resolved, UnconfiguredLivePaymentProvider)
