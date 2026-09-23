"""Stripe PaymentProvider seed. Fake client only — no Stripe network."""

import pytest

from app.models import FailureClass, Mission, MissionAnswer, PaymentIntent
from app.payments import (
    PaymentError,
    SimulatedPaymentProvider,
    StripeChargeResult,
    StripePaymentProvider,
    UnconfiguredLivePaymentProvider,
    build_live_payment_provider,
    build_payment_provider,
    resolve_payment_provider,
    stripe_live_opt_in,
)
from app.runtime import PolicyError, WalletAdapter

SECRET = "sk_test_sentinel_do_not_leak"
MERCHANT = "acct_allow"


class FakeStripe:
    def __init__(self, *, status: str = "succeeded", error: Exception | None = None):
        self.calls: list[dict] = []
        self.status = status
        self.error = error

    async def create_payment_intent(self, **kwargs):
        assert SECRET not in str(kwargs)
        if self.error is not None:
            raise self.error
        self.calls.append(kwargs)
        return StripeChargeResult(id=f"pi_fake{len(self.calls)}", status=self.status)


def _enable(monkeypatch, **overrides):
    values = {
        "SWARM_LIVE_PAYMENTS": "1",
        "STRIPE_SECRET_KEY": SECRET,
        "SWARM_STRIPE_MERCHANT_ALLOWLIST": MERCHANT,
    }
    values.update(overrides)
    for name in (
        "SWARM_LIVE_PAYMENTS",
        "STRIPE_SECRET_KEY",
        "SWARM_STRIPE_MERCHANT_ALLOWLIST",
        "SWARM_STRIPE_OBJECTIVE_CAP_USD",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        if value is None:
            continue
        monkeypatch.setenv(name, value)


def _mission(**overrides) -> Mission:
    fields = {
        "goal": "pay",
        "live_payments": True,
        "budget": 10,
        "limits": {"max_payment_amount": 5},
    }
    fields.update(overrides)
    return Mission(**fields)


def _intent(mission: Mission, amount: float = 2, *, recipient: str = MERCHANT, key: str = "pay-1",
            reason: str = "test work", asset: str = "usd") -> PaymentIntent:
    return PaymentIntent(
        mission_id=mission.id,
        recipient=recipient,
        asset=asset,
        amount=amount,
        reason=reason,
        idempotency_key=key,
    )


def _provider(fake: FakeStripe, **kwargs) -> StripePaymentProvider:
    return StripePaymentProvider(
        api_key=kwargs.pop("api_key", SECRET),
        allowlist=kwargs.pop("allowlist", frozenset({MERCHANT})),
        client=fake,
        **kwargs,
    )


def test_default_factory_stays_simulated_when_stripe_flags_are_set(monkeypatch):
    _enable(monkeypatch)
    assert stripe_live_opt_in() is True
    assert isinstance(build_payment_provider(), SimulatedPaymentProvider)
    mission = _mission()
    resolved = resolve_payment_provider(mission, override=_provider(FakeStripe()))
    assert isinstance(resolved, UnconfiguredLivePaymentProvider)
    assert resolved.spend_enabled() is False
    live = build_live_payment_provider()
    assert isinstance(live, StripePaymentProvider)
    assert live.configured() is True
    assert live.spend_enabled() is True
    assert SECRET not in repr(live)


@pytest.mark.asyncio
async def test_live_provider_health_omits_secrets(monkeypatch):
    _enable(monkeypatch)
    health = await build_live_payment_provider().health()
    dumped = str(health.model_dump())
    assert health.status == "healthy"
    assert SECRET not in dumped
    assert "sk_" not in dumped
    assert "secret" not in dumped.lower()


@pytest.mark.parametrize("missing", ["SWARM_LIVE_PAYMENTS", "STRIPE_SECRET_KEY", "SWARM_STRIPE_MERCHANT_ALLOWLIST"])
def test_partial_live_env_refuses(monkeypatch, missing):
    _enable(monkeypatch, **{missing: None})
    assert stripe_live_opt_in() is False
    provider = build_live_payment_provider()
    assert isinstance(provider, UnconfiguredLivePaymentProvider)
    assert provider.spend_enabled() is False


def test_card_allowlist_and_bad_cap_do_not_opt_in(monkeypatch):
    _enable(monkeypatch, SWARM_STRIPE_MERCHANT_ALLOWLIST="4242424242424242")
    assert stripe_live_opt_in() is False
    _enable(monkeypatch, SWARM_STRIPE_OBJECTIVE_CAP_USD="not-a-cap")
    assert stripe_live_opt_in() is False
    assert isinstance(build_live_payment_provider(), UnconfiguredLivePaymentProvider)


@pytest.mark.asyncio
async def test_unconfigured_stripe_provider_refuses_without_calling_client():
    fake = FakeStripe()
    provider = _provider(fake, api_key="")
    mission = _mission()
    assert provider.configured() is False
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert SECRET not in str(exc.value)
    assert fake.calls == []


@pytest.mark.asyncio
async def test_allowlisted_charge_parks_for_approval():
    fake = FakeStripe()
    provider = _provider(fake)
    mission = _mission()
    intent = _intent(mission)
    with pytest.raises(PaymentError) as exc:
        await provider.pay(intent, mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert "human approval" in str(exc.value).lower()
    assert provider.has_pending(mission, "pay-1") is True
    with pytest.raises(PaymentError) as replay:
        await provider.pay(intent, mission)
    assert replay.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert fake.calls == []
    assert intent.status != "succeeded"
    assert intent.transaction_hash is None


@pytest.mark.asyncio
async def test_approve_once_then_idempotent_replay():
    fake = FakeStripe()
    provider = _provider(fake)
    mission = _mission()
    intent = _intent(mission, reason=f"work {SECRET}")
    with pytest.raises(PaymentError):
        await provider.pay(intent, mission)
    provider.record_approval(mission, "pay-1", "approve")
    result = await provider.pay(intent, mission)
    assert result.status == "succeeded"
    assert result.transaction_hash == "pi_fake1"
    assert provider.has_pending(mission, "pay-1") is False
    replay = await provider.pay(intent, mission)
    assert replay.transaction_hash == "pi_fake1"
    assert replay.status == "succeeded"
    assert len(fake.calls) == 1
    assert fake.calls[0]["idempotency_key"] == "pay-1"
    assert fake.calls[0]["destination"] == MERCHANT
    assert fake.calls[0]["amount_cents"] == 200
    assert SECRET not in str(fake.calls)
    assert SECRET not in str(result.model_dump())


@pytest.mark.asyncio
async def test_mission_answer_approve_charges_once_and_deny_does_not():
    approved = _mission()
    approved.answers.append(MissionAnswer(
        question_id="q-approve",
        question="Approve this live payment?",
        answer="approve",
        kind="approval",
        approval_action="live_payment",
    ))
    fake = FakeStripe()
    provider = _provider(fake)
    result = await provider.pay(_intent(approved), approved)
    assert result.status == "succeeded"
    assert len(fake.calls) == 1

    denied = _mission()
    denied.answers.append(MissionAnswer(
        question_id="q-deny",
        question="Approve this live payment?",
        answer="deny",
        kind="approval",
        approval_action="live_payment",
    ))
    denied_fake = FakeStripe()
    denied_provider = _provider(denied_fake)
    with pytest.raises(PaymentError) as exc:
        await denied_provider.pay(_intent(denied), denied)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert denied_fake.calls == []


@pytest.mark.asyncio
async def test_deny_does_not_charge_and_replay_stays_denied():
    fake = FakeStripe()
    provider = _provider(fake)
    mission = _mission()
    intent = _intent(mission)
    provider.record_approval(mission, "pay-1", "deny")
    with pytest.raises(PaymentError) as exc:
        await provider.pay(intent, mission)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    provider.record_approval(mission, "pay-1", "approve")
    with pytest.raises(PaymentError) as replay:
        await provider.pay(intent, mission)
    assert replay.value.failure_class == FailureClass.POLICY_REFUSAL
    assert fake.calls == []
    assert intent.transaction_hash is None


@pytest.mark.asyncio
async def test_ambiguous_approval_does_not_charge():
    fake = FakeStripe()
    provider = _provider(fake)
    mission = _mission()
    with pytest.raises(PaymentError) as exc:
        provider.record_approval(mission, "pay-1", "maybe later")
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    with pytest.raises(PaymentError):
        await provider.pay(_intent(mission), mission)
    assert fake.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("amount", "spent", "cap_cents"), [
    (6, 0, None),
    (4, 8, None),
    (4, 0, 300),
])
async def test_over_cap_refuses(amount, spent, cap_cents):
    fake = FakeStripe()
    provider = _provider(fake, objective_cap_cents=cap_cents)
    mission = _mission(spent=spent)
    provider.record_approval(mission, "pay-1", "approve")
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission, amount), mission)
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    assert fake.calls == []
    assert provider.has_pending(mission, "pay-1") is False


@pytest.mark.asyncio
async def test_second_charge_over_objective_budget_refuses():
    fake = FakeStripe()
    provider = _provider(fake)
    mission = _mission(limits={"max_payment_amount": 6})
    provider.record_approval(mission, "first", "approve")
    provider.record_approval(mission, "second", "approve")
    first = await provider.pay(_intent(mission, 6, key="first"), mission)
    assert first.status == "succeeded"
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission, 6, key="second"), mission)
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_non_allowlisted_destination_and_card_number_are_refused():
    fake = FakeStripe()
    provider = _provider(fake)
    mission = _mission()
    provider.record_approval(mission, "pay-1", "approve")
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission, recipient="acct_other"), mission)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    card = "4242424242424242"
    with pytest.raises(PaymentError) as card_exc:
        await provider.pay(_intent(mission, recipient=card, key="pay-card"), mission)
    assert card_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert card not in str(card_exc.value)
    assert fake.calls == []


@pytest.mark.asyncio
async def test_missing_policy_approval_mark_refuses_even_after_approve():
    class _NoApproval:
        def authorize(self, request):
            del request

        def approval_required(self, request):
            del request
            return None

    fake = FakeStripe()
    provider = _provider(fake, gate=_NoApproval())
    mission = _mission()
    provider.record_approval(mission, "pay-1", "approve")
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert fake.calls == []


@pytest.mark.asyncio
async def test_client_errors_do_not_leak_secrets():
    fake = FakeStripe(error=RuntimeError(f"stripe down {SECRET} 4242424242424242"))
    provider = _provider(fake)
    mission = _mission()
    provider.record_approval(mission, "pay-1", "approve")
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.PROVIDER_OUTAGE
    assert SECRET not in str(exc.value)
    assert "4242" not in str(exc.value)
    assert fake.calls == []


@pytest.mark.asyncio
async def test_incomplete_stripe_status_is_not_success():
    fake = FakeStripe(status="requires_payment_method")
    provider = _provider(fake)
    mission = _mission()
    provider.record_approval(mission, "pay-1", "approve")
    with pytest.raises(PaymentError) as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    with pytest.raises(PaymentError):
        await provider.pay(_intent(mission), mission)
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_agent_wallet_ignores_stripe_opt_in(monkeypatch):
    _enable(monkeypatch)
    mission = _mission()
    with pytest.raises(PolicyError) as exc:
        await WalletAdapter().pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert SECRET not in str(exc.value)
    assert mission.spent == 0
