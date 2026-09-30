"""x402 PaymentProvider seed. MockTransport only — no live spend."""
from uuid import uuid4

import httpx
import pytest

from app.health import payments_health_status
from app.models import FailureClass, Mission, MissionAnswer, PaymentIntent
from app.payments import (
    SimulatedPaymentProvider,
    UnconfiguredLivePaymentProvider,
    build_live_payment_provider,
    build_payment_provider,
    live_wallet_configured,
    resolve_payment_provider,
)
from app.payments import PaymentError
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.x402_payments import X402PaymentProvider, live_payment_question

FAKE_KEY = "x402_test_FAKEKEY123"
FAKE_ENDPOINT = "https://x402.test/settle"
FAKE_TX = "0x" + ("ab" * 32)
MERCHANT = "merchant.example"
_ENV = (
    "SWARM_LIVE_PAYMENTS",
    "SWARM_X402_API_KEY",
    "SWARM_X402_ENDPOINT",
    "SWARM_X402_MERCHANT_ALLOWLIST",
    "SWARM_X402_OBJECTIVE_CAP_USD",
    "STRIPE_SECRET_KEY",
    "WALLET_PRIVATE_KEY",
    "X402_PRIVATE_KEY",
)


def _clear(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _arm(monkeypatch, *, cap: str | None = None, flag: str = "1"):
    _clear(monkeypatch)
    monkeypatch.setenv("SWARM_LIVE_PAYMENTS", flag)
    monkeypatch.setenv("SWARM_X402_API_KEY", FAKE_KEY)
    monkeypatch.setenv("SWARM_X402_ENDPOINT", FAKE_ENDPOINT)
    monkeypatch.setenv("SWARM_X402_MERCHANT_ALLOWLIST", MERCHANT)
    if cap is not None:
        monkeypatch.setenv("SWARM_X402_OBJECTIVE_CAP_USD", cap)


def _mission(**overrides) -> Mission:
    fields = dict(goal="pay", budget=10, live_payments=True, limits={"max_payment_amount": 5})
    fields.update(overrides)
    return Mission(**fields)


def _intent(mission: Mission, amount: float = 1.5, recipient: str = MERCHANT, key: str = "pay-1") -> PaymentIntent:
    return PaymentIntent(
        mission_id=mission.id,
        recipient=recipient,
        amount=amount,
        reason="test work",
        asset="usdc",
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


def _ok(seen: list, *, status: str = "settled", amount: str = "1.50", pay_to: str = MERCHANT):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "success": True,
            "status": status,
            "transaction": FAKE_TX,
            "amount": amount,
            "payTo": pay_to,
            "detail": FAKE_KEY,
        })
    return handler


def _no_secret(blob: str) -> None:
    assert FAKE_KEY not in blob
    assert "SHOULD_NOT_LEAK" not in blob
    assert FAKE_ENDPOINT not in blob


@pytest.mark.parametrize("setup", [
    {},
    {"SWARM_X402_API_KEY": FAKE_KEY},
    {"SWARM_LIVE_PAYMENTS": "1"},
    {"SWARM_X402_ENDPOINT": FAKE_ENDPOINT},
    {"SWARM_X402_MERCHANT_ALLOWLIST": MERCHANT},
    {"SWARM_LIVE_PAYMENTS": "1", "SWARM_X402_API_KEY": FAKE_KEY},
    {"SWARM_LIVE_PAYMENTS": "1", "SWARM_X402_API_KEY": FAKE_KEY, "SWARM_X402_ENDPOINT": FAKE_ENDPOINT},
    {
        "SWARM_LIVE_PAYMENTS": "1",
        "SWARM_X402_API_KEY": FAKE_KEY,
        "SWARM_X402_MERCHANT_ALLOWLIST": MERCHANT,
    },
    {"SWARM_LIVE_PAYMENTS": "0", "SWARM_X402_API_KEY": FAKE_KEY,
     "SWARM_X402_ENDPOINT": FAKE_ENDPOINT, "SWARM_X402_MERCHANT_ALLOWLIST": MERCHANT},
    {"SWARM_LIVE_PAYMENTS": "1", "SWARM_X402_API_KEY": FAKE_KEY,
     "SWARM_X402_ENDPOINT": "http://x402.test/settle", "SWARM_X402_MERCHANT_ALLOWLIST": MERCHANT},
    {"SWARM_LIVE_PAYMENTS": "1", "SWARM_X402_API_KEY": FAKE_KEY,
     "SWARM_X402_ENDPOINT": f"https://x402.test/settle?token={FAKE_KEY}",
     "SWARM_X402_MERCHANT_ALLOWLIST": MERCHANT},
    {"STRIPE_SECRET_KEY": "sk_test_should_not_opt_in", "WALLET_PRIVATE_KEY": "0x" + "ab" * 32},
    {"X402_PRIVATE_KEY": "0x" + "cd" * 32},
    {"SWARM_LIVE_PAYMENTS": "1", "SWARM_X402_API_KEY": FAKE_KEY, "SWARM_X402_ENDPOINT": FAKE_ENDPOINT,
     "SWARM_X402_MERCHANT_ALLOWLIST": "0x" + "ab" * 32},
    {"SWARM_LIVE_PAYMENTS": "1", "SWARM_X402_API_KEY": FAKE_KEY, "SWARM_X402_ENDPOINT": FAKE_ENDPOINT,
     "SWARM_X402_MERCHANT_ALLOWLIST": MERCHANT, "SWARM_X402_OBJECTIVE_CAP_USD": "nope"},
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
async def test_full_env_keeps_simulated_default_and_ignores_injected_spender(monkeypatch):
    _arm(monkeypatch, flag="yes")
    assert live_wallet_configured() is True
    live = build_live_payment_provider()
    assert isinstance(live, X402PaymentProvider)
    assert live.configured() is True
    assert FAKE_KEY not in repr(live)
    assert FAKE_ENDPOINT not in repr(live)
    assert isinstance(build_payment_provider(), SimulatedPaymentProvider)
    simulated = _mission(live_payments=False)
    assert isinstance(resolve_payment_provider(simulated), SimulatedPaymentProvider)
    paid = {"n": 0}

    class Stub:
        provider_id = "stub-live"
        mode = "live"

        def spend_enabled(self):
            return True

        async def pay(self, intent, mission):
            paid["n"] += 1
            intent.status = "succeeded"
            return intent

    resolved = resolve_payment_provider(_mission(), override=Stub())
    assert isinstance(resolved, X402PaymentProvider)
    assert paid["n"] == 0
    wallet = await SimulatedPaymentProvider().pay(_intent(simulated), simulated)
    assert wallet.status == "simulated"
    assert wallet.transaction_hash is None


@pytest.mark.asyncio
async def test_health_does_not_probe_or_echo_secrets(monkeypatch):
    def boom(api_key: str):
        raise AssertionError("health must not open an x402 client")

    monkeypatch.setattr("app.x402_payments.build_x402_client", boom)
    _clear(monkeypatch)
    quiet = await payments_health_status()
    assert quiet["configured"] is False
    assert quiet["status"] == "unconfigured"
    assert quiet["spend_enabled"] is False
    assert quiet["default_provider"] == "simulated"
    assert quiet["fallback"] is False
    _no_secret(str(quiet))

    _arm(monkeypatch)
    armed = await payments_health_status()
    assert armed["configured"] is True
    assert armed["status"] == "healthy"
    assert armed["provider"] == "x402"
    assert armed["spend_enabled"] is True
    assert "approval" in (armed["detail"] or "")
    _no_secret(str(armed))
    health = await X402PaymentProvider.from_env().health()
    _no_secret(str(health.model_dump()))


@pytest.mark.asyncio
async def test_guards_run_before_any_network_call(monkeypatch):
    seen: list = []
    _arm(monkeypatch)
    provider = X402PaymentProvider.from_env(client=_client(_ok(seen)))
    mission = _mission()

    with pytest.raises(PaymentError) as missing_key:
        await provider.pay(_intent(mission, key=""), mission)
    assert missing_key.value.failure_class == FailureClass.INVALID_OUTPUT

    with pytest.raises(PaymentError) as denied_dest:
        bad = _intent(mission, recipient="other.example")
        _approve(mission, 1.5, "other.example", "pay-1")
        await provider.pay(bad, mission)
    assert denied_dest.value.failure_class == FailureClass.POLICY_REFUSAL

    mission.answers.clear()
    _approve(mission, 6, MERCHANT, "pay-over")
    with pytest.raises(PaymentError) as over_cap:
        await provider.pay(_intent(mission, amount=6, key="pay-over"), mission)
    assert over_cap.value.failure_class == FailureClass.RESOURCE_EXHAUSTED

    _arm(monkeypatch, cap="1.00")
    capped = X402PaymentProvider.from_env(client=_client(_ok(seen)))
    tight = _mission()
    _approve(tight, 1.5, MERCHANT, "pay-tight")
    with pytest.raises(PaymentError) as objective:
        await capped.pay(_intent(tight, amount=1.5, key="pay-tight"), tight)
    assert objective.value.failure_class == FailureClass.RESOURCE_EXHAUSTED

    mission.answers.clear()
    with pytest.raises(PaymentError) as needs_approval:
        await provider.pay(_intent(mission), mission)
    assert needs_approval.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED

    _approve(mission, 1.5, MERCHANT, "pay-1", answer="deny")
    with pytest.raises(PaymentError) as denied:
        await provider.pay(_intent(mission), mission)
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL

    local = _mission(privacy="local_only")
    _approve(local, 1.5, MERCHANT, "pay-1")
    with pytest.raises(PaymentError) as local_only:
        await provider.pay(_intent(local), local)
    assert local_only.value.failure_class == FailureClass.POLICY_REFUSAL
    assert seen == []
    _no_secret(str(denied.value))


@pytest.mark.asyncio
async def test_approved_settle_is_one_key_and_does_not_echo_secrets(monkeypatch):
    seen: list = []
    _arm(monkeypatch)
    provider = X402PaymentProvider.from_env(client=_client(_ok(seen)))
    mission = _mission()
    _approve(mission, 1.5, MERCHANT, "pay-1")
    intent = _intent(mission)
    intent.reason = f"note {FAKE_KEY} {'9' * 16}"
    result = await provider.pay(intent, mission)
    assert result.status == "succeeded"
    assert result.transaction_hash == FAKE_TX
    assert result.asset == "usdc"
    assert result.chain == "x402"
    assert result.status != "simulated"
    _no_secret(str(result.model_dump()))
    body = seen[0].content.decode()
    assert '"amount":"1.50"' in body or '"amount": "1.50"' in body
    assert MERCHANT in body
    assert seen[0].headers["Idempotency-Key"] == "pay-1"
    assert seen[0].headers["PAYMENT-PROTOCOL"] == "x402"
    assert FAKE_KEY not in body
    assert FAKE_KEY in seen[0].headers["Authorization"]

    with pytest.raises(PaymentError) as second:
        await provider.pay(_intent(mission, key="pay-2"), mission)
    assert second.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,match,klass", [
    (401, "API key", FailureClass.AUTHORIZATION_REQUIRED),
    (429, "rate limit", FailureClass.RATE_LIMIT),
    (408, "timed out", FailureClass.TIMEOUT),
    (402, "not accepted", FailureClass.RESOURCE_EXHAUSTED),
    (503, "unavailable", FailureClass.PROVIDER_OUTAGE),
    (400, "rejected the payment request", FailureClass.INVALID_OUTPUT),
])
async def test_http_status_is_classified_without_body_leak(monkeypatch, status, match, klass):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": FAKE_KEY}})

    _arm(monkeypatch)
    provider = X402PaymentProvider.from_env(client=_client(handler))
    mission = _mission()
    _approve(mission, 1.5, MERCHANT, "pay-1")
    with pytest.raises(PaymentError, match=match) as exc:
        await provider.pay(_intent(mission), mission)
    assert exc.value.failure_class == klass
    _no_secret(str(exc.value))
    assert exc.value.__cause__ is None


@pytest.mark.asyncio
async def test_timeout_connect_and_unsettled_are_not_success(monkeypatch):
    _arm(monkeypatch)
    mission = _mission()
    _approve(mission, 1.5, MERCHANT, "pay-1")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException(FAKE_KEY)

    provider = X402PaymentProvider.from_env(client=_client(timeout))
    with pytest.raises(PaymentError, match="timed out") as timed:
        await provider.pay(_intent(mission), mission)
    assert timed.value.failure_class == FailureClass.TIMEOUT
    _no_secret(str(timed.value))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(FAKE_KEY)

    provider = X402PaymentProvider.from_env(client=_client(down))
    with pytest.raises(PaymentError, match="unavailable") as outage:
        await provider.pay(_intent(mission), mission)
    assert outage.value.failure_class == FailureClass.PROVIDER_OUTAGE

    def unsettled(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "status": "required", "transaction": FAKE_TX})

    provider = X402PaymentProvider.from_env(client=_client(unsettled))
    with pytest.raises(PaymentError, match="not completed") as incomplete:
        await provider.pay(_intent(mission), mission)
    assert incomplete.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED

    def mismatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True, "status": "settled", "transaction": FAKE_TX, "amount": "9.99",
        })

    provider = X402PaymentProvider.from_env(client=_client(mismatch))
    with pytest.raises(PaymentError, match="not completed") as wrong_amount:
        await provider.pay(_intent(mission), mission)
    assert wrong_amount.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_runtime_parks_approval_and_charges_once(tmp_path, monkeypatch):
    seen: list = []

    def factory(api_key: str):
        assert api_key
        return httpx.AsyncClient(transport=httpx.MockTransport(_ok(seen)))

    _arm(monkeypatch)
    monkeypatch.setattr("app.x402_payments.build_x402_client", factory)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)

    with pytest.raises(PolicyError) as parked:
        await runtime.create_payment(mission, MERCHANT, 1.5, "test work", idempotency_key="pay-1")
    assert parked.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    waiting = store.get_mission(mission.id)
    assert waiting.status == "waiting"
    assert waiting.pending_question.kind == "approval"
    assert waiting.pending_question.approval_action == "live_payment"
    assert "pay-1" in waiting.pending_question.question
    assert waiting.spent == 0
    events = store.events(mission.id)
    assert any(e.event_type == "mission.waiting" and e.payload.get("kind") == "approval" for e in events)
    assert not any(e.event_type == "payment.created" for e in events)
    assert seen == []
    _no_secret(str([e.payload for e in events]))

    store.accept_answer(mission.id, waiting.pending_question.question_id, "deny")
    with pytest.raises(PolicyError) as denied:
        await runtime.create_payment(
            store.get_mission(mission.id), MERCHANT, 1.5, "test work", idempotency_key="pay-1",
        )
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL
    assert store.get_mission(mission.id).spent == 0
    assert store.get_mission(mission.id).status == "pending"
    assert seen == []

    fresh = _mission()
    store.save_mission(fresh)
    with pytest.raises(PolicyError):
        await runtime.create_payment(fresh, MERCHANT, 1.5, "test work", idempotency_key="pay-ok")
    pending = store.get_mission(fresh.id).pending_question
    answered = await runtime.submit_answer(fresh.id, pending.question_id, "approve")
    assert answered["resume"] == "payment_approval"
    assert fresh.id not in runtime.runs
    paid = await runtime.create_payment(
        store.get_mission(fresh.id), MERCHANT, 1.5, "test work", idempotency_key="pay-ok",
    )
    assert paid.status == "succeeded"
    assert paid.transaction_hash == FAKE_TX
    saved = store.get_mission(fresh.id)
    assert saved.spent == 1.5
    assert saved.status == "pending"
    assert saved.answers[-1].consumed_at is not None
    created = [e for e in store.events(fresh.id) if e.event_type == "payment.created"]
    assert len(created) == 1
    _no_secret(str(created[0].payload))
    assert len(seen) == 1

    replay = await runtime.create_payment(
        store.get_mission(fresh.id), MERCHANT, 1.5, "test work", idempotency_key="pay-ok",
    )
    assert replay.transaction_hash == FAKE_TX
    assert len(seen) == 1

    with pytest.raises(PolicyError) as later:
        await runtime.create_payment(
            store.get_mission(fresh.id), MERCHANT, 1.0, "later", idempotency_key="pay-later",
        )
    assert later.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    later_mission = store.get_mission(fresh.id)
    assert later_mission.spent == 1.5
    assert later_mission.pending_question.kind == "approval"
    assert "pay-later" in later_mission.pending_question.question
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_runtime_refuses_bad_destination_cap_and_local_only_before_network(tmp_path, monkeypatch):
    seen: list = []

    def factory(api_key: str):
        return httpx.AsyncClient(transport=httpx.MockTransport(_ok(seen)))

    _arm(monkeypatch, cap="1.00")
    monkeypatch.setattr("app.x402_payments.build_x402_client", factory)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)
    with pytest.raises(PolicyError) as dest:
        await runtime.create_payment(mission, "other.example", 1.0, "nope", idempotency_key="pay-dest")
    assert dest.value.failure_class == FailureClass.POLICY_REFUSAL
    assert store.get_mission(mission.id).status != "waiting"

    with pytest.raises(PolicyError) as cap:
        await runtime.create_payment(mission, MERCHANT, 1.5, "over", idempotency_key="pay-cap")
    assert cap.value.failure_class == FailureClass.RESOURCE_EXHAUSTED

    local = _mission(privacy="local_only")
    store.save_mission(local)
    with pytest.raises(PolicyError) as privacy:
        await runtime.create_payment(local, MERCHANT, 1.0, "local", idempotency_key="pay-local")
    assert privacy.value.failure_class == FailureClass.POLICY_REFUSAL
    assert seen == []


@pytest.mark.asyncio
async def test_partial_env_does_not_simulate_success_after_approval(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SWARM_LIVE_PAYMENTS", "1")
    monkeypatch.setenv("SWARM_X402_API_KEY", FAKE_KEY)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)
    with pytest.raises(PolicyError) as parked:
        await runtime.create_payment(mission, MERCHANT, 1.5, "partial", idempotency_key="pay-partial")
    assert parked.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    pending = store.get_mission(mission.id).pending_question
    await runtime.submit_answer(mission.id, pending.question_id, "approve")
    with pytest.raises(PolicyError) as closed:
        await runtime.create_payment(
            store.get_mission(mission.id), MERCHANT, 1.5, "partial", idempotency_key="pay-partial",
        )
    assert closed.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert "not configured" in str(closed.value)
    saved = store.get_mission(mission.id)
    assert saved.spent == 0
    assert not any(e.event_type == "payment.created" for e in store.events(mission.id))
