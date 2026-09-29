"""Stripe PaymentProvider seed. MockTransport only — no live Stripe calls."""
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest

from app.health import payments_health_status
from app.models import FailureClass, Mission, MissionAnswer, PaymentIntent
from app.payments import (
    PaymentError,
    SimulatedPaymentProvider,
    UnconfiguredLivePaymentProvider,
    build_live_payment_provider,
    build_payment_provider,
    live_wallet_configured,
    resolve_payment_provider,
)
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.stripe_payments import StripePaymentProvider as StripeAdapter
from app.stripe_payments import live_payment_question

FAKE_KEY = "sk_test_FAKEKEY123"
_ENV = (
    "SWARM_LIVE_PAYMENTS",
    "STRIPE_SECRET_KEY",
    "SWARM_STRIPE_MERCHANT_ALLOWLIST",
    "SWARM_STRIPE_OBJECTIVE_CAP_USD",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PUBLISHABLE_KEY",
    "WALLET_PRIVATE_KEY",
)


def _clear(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _arm(monkeypatch, *, cap: str | None = None, flag: str = "1"):
    _clear(monkeypatch)
    monkeypatch.setenv("SWARM_LIVE_PAYMENTS", flag)
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_KEY)
    monkeypatch.setenv("SWARM_STRIPE_MERCHANT_ALLOWLIST", "acct_ok,merchant.example")
    if cap is not None:
        monkeypatch.setenv("SWARM_STRIPE_OBJECTIVE_CAP_USD", cap)


def _mission(**overrides) -> Mission:
    fields = dict(goal="pay", budget=10, live_payments=True, limits={"max_payment_amount": 5})
    fields.update(overrides)
    return Mission(**fields)


def _intent(mission: Mission, amount: float = 1.5, recipient: str = "acct_ok", key: str = "pay-1") -> PaymentIntent:
    return PaymentIntent(
        mission_id=mission.id,
        recipient=recipient,
        amount=amount,
        reason="test work",
        asset="usd",
        idempotency_key=key,
    )


def _approve(mission: Mission, amount: float, recipient: str, key: str, answer: str = "approve") -> None:
    mission.answers.append(MissionAnswer(
        question_id=str(uuid4()),
        question=live_payment_question(amount, recipient, key),
        answer=answer,
        kind="approval",
        approval_action="live_payment",
    ))


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "id": "pi_test123",
            "status": "succeeded",
            "client_secret": "pi_test123_secret_SHOULD_NOT_LEAK",
        })
    return handler


def _no_secret(blob: str) -> None:
    assert FAKE_KEY not in blob
    assert "SHOULD_NOT_LEAK" not in blob
    assert "whsec_" not in blob
    assert "client_secret" not in blob


@pytest.mark.parametrize("setup", [
    {},
    {"STRIPE_SECRET_KEY": FAKE_KEY},
    {"SWARM_LIVE_PAYMENTS": "1"},
    {"SWARM_STRIPE_MERCHANT_ALLOWLIST": "acct_ok"},
    {"SWARM_LIVE_PAYMENTS": "1", "STRIPE_SECRET_KEY": FAKE_KEY},
    {"STRIPE_SECRET_KEY": FAKE_KEY, "SWARM_STRIPE_MERCHANT_ALLOWLIST": "acct_ok"},
    {"SWARM_LIVE_PAYMENTS": "1", "SWARM_STRIPE_MERCHANT_ALLOWLIST": "acct_ok"},
    {"SWARM_LIVE_PAYMENTS": "0", "STRIPE_SECRET_KEY": FAKE_KEY, "SWARM_STRIPE_MERCHANT_ALLOWLIST": "acct_ok"},
    {"STRIPE_WEBHOOK_SECRET": "whsec_example", "STRIPE_PUBLISHABLE_KEY": "pk_test_example"},
    {"WALLET_PRIVATE_KEY": "0xnot-read"},
    {"SWARM_LIVE_PAYMENTS": "1", "STRIPE_SECRET_KEY": FAKE_KEY, "SWARM_STRIPE_MERCHANT_ALLOWLIST": "sk_test_notamerchant"},
    {"SWARM_LIVE_PAYMENTS": "1", "STRIPE_SECRET_KEY": FAKE_KEY, "SWARM_STRIPE_MERCHANT_ALLOWLIST": "4111111111111111"},
    {
        "SWARM_LIVE_PAYMENTS": "1",
        "STRIPE_SECRET_KEY": FAKE_KEY,
        "SWARM_STRIPE_MERCHANT_ALLOWLIST": "acct_ok",
        "SWARM_STRIPE_OBJECTIVE_CAP_USD": "nope",
    },
])
def test_partial_env_stays_unconfigured(monkeypatch, setup):
    _clear(monkeypatch)
    for name, value in setup.items():
        monkeypatch.setenv(name, value)
    assert live_wallet_configured() is False
    live = build_live_payment_provider()
    assert isinstance(live, UnconfiguredLivePaymentProvider)
    assert isinstance(build_payment_provider(), SimulatedPaymentProvider)
    assert live.spend_enabled() is False


@pytest.mark.asyncio
async def test_full_env_wires_stripe_without_changing_simulated_default(monkeypatch):
    _arm(monkeypatch, flag="yes")
    assert live_wallet_configured() is True
    live = build_live_payment_provider()
    assert isinstance(live, StripeAdapter)
    assert live.configured() is True
    assert FAKE_KEY not in repr(live)
    assert isinstance(build_payment_provider(), SimulatedPaymentProvider)
    simulated = _mission(live_payments=False)
    assert isinstance(resolve_payment_provider(simulated), SimulatedPaymentProvider)
    stub_paid = {"n": 0}

    class Stub:
        provider_id = "stub-live"
        mode = "live"

        def spend_enabled(self):
            return True

        async def pay(self, intent, mission):
            stub_paid["n"] += 1
            return intent

    resolved = resolve_payment_provider(_mission(), override=Stub())
    assert isinstance(resolved, StripeAdapter)
    assert stub_paid["n"] == 0
    wallet = await SimulatedPaymentProvider().pay(_intent(simulated), simulated)
    assert wallet.status == "simulated"
    assert wallet.transaction_hash is None


@pytest.mark.asyncio
async def test_health_does_not_probe_or_echo_secrets(monkeypatch):
    def boom(api_key: str):
        raise AssertionError("health must not open a Stripe client")

    monkeypatch.setattr("app.stripe_payments.build_stripe_client", boom)
    _clear(monkeypatch)
    quiet = await payments_health_status()
    assert quiet["configured"] is False
    assert quiet["status"] == "unconfigured"
    assert quiet["spend_enabled"] is False
    assert quiet["default_provider"] == "simulated"
    _no_secret(str(quiet))

    _arm(monkeypatch)
    armed = await payments_health_status()
    assert armed["configured"] is True
    assert armed["status"] == "healthy"
    assert armed["provider"] == "stripe"
    assert armed["spend_enabled"] is True
    assert "approval" in (armed["detail"] or "")
    _no_secret(str(armed))
    health = await StripeAdapter.from_env().health()
    _no_secret(str(health.model_dump()))


@pytest.mark.asyncio
async def test_guards_run_before_any_network_call(monkeypatch):
    seen: list = []
    _arm(monkeypatch)
    provider = StripeAdapter.from_env(client=_client(_ok(seen)))
    mission = _mission()

    with pytest.raises(PaymentError) as missing_key:
        await provider.pay(_intent(mission, key=""), mission)
    assert missing_key.value.failure_class == FailureClass.INVALID_OUTPUT

    with pytest.raises(PaymentError) as denied_dest:
        bad = _intent(mission, recipient="acct_other")
        _approve(mission, 1.5, "acct_other", "pay-1")
        await provider.pay(bad, mission)
    assert denied_dest.value.failure_class == FailureClass.POLICY_REFUSAL

    mission.answers.clear()
    _approve(mission, 6, "acct_ok", "pay-over")
    with pytest.raises(PaymentError) as over_cap:
        await provider.pay(_intent(mission, amount=6, key="pay-over"), mission)
    assert over_cap.value.failure_class == FailureClass.RESOURCE_EXHAUSTED

    _arm(monkeypatch, cap="1.00")
    capped = StripeAdapter.from_env(client=_client(_ok(seen)))
    tight = _mission()
    _approve(tight, 1.5, "acct_ok", "pay-tight")
    with pytest.raises(PaymentError) as objective:
        await capped.pay(_intent(tight, amount=1.5, key="pay-tight"), tight)
    assert objective.value.failure_class == FailureClass.RESOURCE_EXHAUSTED

    mission.answers.clear()
    with pytest.raises(PaymentError) as needs_approval:
        await provider.pay(_intent(mission), mission)
    assert needs_approval.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED

    _approve(mission, 1.5, "acct_ok", "pay-1", answer="deny")
    with pytest.raises(PaymentError) as denied:
        await provider.pay(_intent(mission), mission)
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL

    local = _mission(privacy="local_only")
    _approve(local, 1.5, "acct_ok", "pay-1")
    with pytest.raises(PaymentError) as local_only:
        await provider.pay(_intent(local), local)
    assert local_only.value.failure_class == FailureClass.POLICY_REFUSAL
    assert seen == []
    _no_secret(str(denied.value))


@pytest.mark.asyncio
async def test_approved_charge_is_idempotent_and_one_approval_does_not_repeat(monkeypatch):
    seen: list = []
    _arm(monkeypatch)
    provider = StripeAdapter.from_env(client=_client(_ok(seen)))
    mission = _mission()
    _approve(mission, 1.5, "acct_ok", "pay-1")
    intent = _intent(mission)
    pan = "9" * 16
    intent.reason = f"note {FAKE_KEY} {pan}"
    result = await provider.pay(intent, mission)
    assert pan not in str(result.model_dump())
    assert result.status == "succeeded"
    assert result.transaction_hash == "pi_test123"
    assert result.asset == "usd"
    assert result.chain == "stripe"
    _no_secret(str(result.model_dump()))
    body = parse_qs(seen[0].content.decode())
    assert body["amount"] == ["150"]
    assert body["currency"] == ["usd"]
    assert body["transfer_data[destination]"] == ["acct_ok"]
    assert seen[0].headers["Idempotency-Key"] == "pay-1"
    assert FAKE_KEY not in seen[0].content.decode()

    with pytest.raises(PaymentError) as second:
        await provider.pay(_intent(mission, key="pay-2"), mission)
    assert second.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,match,klass", [
    (401, "API key", FailureClass.AUTHORIZATION_REQUIRED),
    (429, "rate limit", FailureClass.RATE_LIMIT),
    (408, "timed out", FailureClass.TIMEOUT),
    (402, "exhausted", FailureClass.RESOURCE_EXHAUSTED),
    (503, "unavailable", FailureClass.PROVIDER_OUTAGE),
    (400, "rejected the charge request", FailureClass.INVALID_OUTPUT),
])
async def test_http_status_is_classified_without_body_leak(monkeypatch, status, match, klass):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": FAKE_KEY}})

    _arm(monkeypatch)
    provider = StripeAdapter.from_env(client=_client(handler))
    mission = _mission()
    _approve(mission, 1.5, "acct_ok", "pay-1")
    with pytest.raises(PaymentError, match=match) as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == klass
    _no_secret(str(exc.value))
    assert exc.value.__cause__ is None


@pytest.mark.asyncio
async def test_timeout_and_connect_are_classified(monkeypatch):
    _arm(monkeypatch)
    mission = _mission()
    _approve(mission, 1.5, "acct_ok", "pay-1")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException(FAKE_KEY)

    provider = StripeAdapter.from_env(client=_client(timeout))
    with pytest.raises(PaymentError, match="timed out") as timed:
        await provider.pay(_intent(mission), mission)
    assert timed.value.failure_class == FailureClass.TIMEOUT
    _no_secret(str(timed.value))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(FAKE_KEY)

    provider = StripeAdapter.from_env(client=_client(down))
    with pytest.raises(PaymentError, match="unavailable") as outage:
        await provider.pay(_intent(mission), mission)
    assert outage.value.failure_class == FailureClass.PROVIDER_OUTAGE
    _no_secret(str(outage.value))


@pytest.mark.asyncio
async def test_incomplete_payment_intent_is_not_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "pi_test123", "status": "requires_payment_method"})

    _arm(monkeypatch)
    provider = StripeAdapter.from_env(client=_client(handler))
    mission = _mission()
    _approve(mission, 1.5, "acct_ok", "pay-1")
    with pytest.raises(PaymentError, match="not completed") as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_runtime_parks_approval_and_charges_once(tmp_path, monkeypatch):
    seen: list = []

    def factory(api_key: str):
        assert api_key
        return httpx.AsyncClient(transport=httpx.MockTransport(_ok(seen)))

    _arm(monkeypatch)
    monkeypatch.setattr("app.stripe_payments.build_stripe_client", factory)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)

    with pytest.raises(PolicyError) as parked:
        await runtime.create_payment(mission, "acct_ok", 1.5, "test work", idempotency_key="pay-1")
    assert parked.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    waiting = store.get_mission(mission.id)
    assert waiting.status == "waiting"
    assert waiting.pending_question.kind == "approval"
    assert waiting.pending_question.approval_action == "live_payment"
    assert waiting.spent == 0
    events = store.events(mission.id)
    assert any(e.event_type == "mission.waiting" and e.payload.get("kind") == "approval" for e in events)
    assert not any(e.event_type == "payment.created" for e in events)
    assert seen == []
    _no_secret(str([e.payload for e in events]))

    store.accept_answer(mission.id, waiting.pending_question.question_id, "deny")
    with pytest.raises(PolicyError) as denied:
        await runtime.create_payment(store.get_mission(mission.id), "acct_ok", 1.5, "test work", idempotency_key="pay-1")
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL
    assert store.get_mission(mission.id).spent == 0
    assert store.get_mission(mission.id).status == "pending"
    assert seen == []

    fresh = _mission()
    store.save_mission(fresh)
    with pytest.raises(PolicyError):
        await runtime.create_payment(fresh, "acct_ok", 1.5, "test work", idempotency_key="pay-ok")
    pending = store.get_mission(fresh.id).pending_question
    answered = await runtime.submit_answer(fresh.id, pending.question_id, "approve")
    assert answered["resume"] == "payment_approval"
    assert fresh.id not in runtime.runs
    paid = await runtime.create_payment(
        store.get_mission(fresh.id), "acct_ok", 1.5, "test work", idempotency_key="pay-ok",
    )
    assert paid.status == "succeeded"
    assert paid.transaction_hash == "pi_test123"
    saved = store.get_mission(fresh.id)
    assert saved.spent == 1.5
    assert saved.status == "pending"
    assert saved.answers[-1].consumed_at is not None
    created = [e for e in store.events(fresh.id) if e.event_type == "payment.created"]
    assert len(created) == 1
    _no_secret(str(created[0].payload))
    assert len(seen) == 1

    replay = await runtime.create_payment(
        store.get_mission(fresh.id), "acct_ok", 1.5, "test work", idempotency_key="pay-ok",
    )
    assert replay.transaction_hash == "pi_test123"
    assert len(seen) == 1

    with pytest.raises(PolicyError) as later:
        await runtime.create_payment(
            store.get_mission(fresh.id), "acct_ok", 1.0, "later", idempotency_key="pay-later",
        )
    assert later.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert store.get_mission(fresh.id).spent == 1.5
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_runtime_refuses_bad_destination_cap_and_local_only_before_network(tmp_path, monkeypatch):
    seen: list = []

    def factory(api_key: str):
        return httpx.AsyncClient(transport=httpx.MockTransport(_ok(seen)))

    _arm(monkeypatch, cap="1.00")
    monkeypatch.setattr("app.stripe_payments.build_stripe_client", factory)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)
    with pytest.raises(PolicyError) as dest:
        await runtime.create_payment(mission, "acct_other", 1.0, "nope", idempotency_key="pay-dest")
    assert dest.value.failure_class == FailureClass.POLICY_REFUSAL
    assert store.get_mission(mission.id).status != "waiting"

    with pytest.raises(PolicyError) as cap:
        await runtime.create_payment(mission, "acct_ok", 1.5, "over", idempotency_key="pay-cap")
    assert cap.value.failure_class == FailureClass.RESOURCE_EXHAUSTED

    local = _mission(privacy="local_only")
    store.save_mission(local)
    with pytest.raises(PolicyError) as privacy:
        await runtime.create_payment(local, "acct_ok", 1.0, "local", idempotency_key="pay-local")
    assert privacy.value.failure_class == FailureClass.POLICY_REFUSAL
    assert seen == []
