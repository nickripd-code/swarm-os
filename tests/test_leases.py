from datetime import timedelta
from uuid import uuid4

import pytest

from app.leases import IdempotencyError, IdempotencyGuard, LeaseConflict, WorkerLeases
from app.llm import FallbackController
from app.models import FailureClass, Mission, utcnow
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store, WorkerLeaseRow
from app.tools import LocalToolProvider


def _store(tmp_path) -> Store:
    return Store(str(tmp_path / "swarm.db"))


def test_claim_renew_and_same_owner_heartbeat(tmp_path):
    store = _store(tmp_path)
    leases = WorkerLeases(store)
    first = leases.claim(scope="task", scope_id="task-1", mission_id="m1", owner_id="w1", ttl_seconds=30)
    assert first.reclaimed is False
    assert first.lease.expired() is False
    again = leases.claim(scope="task", scope_id="task-1", mission_id="m1", owner_id="w1", ttl_seconds=60)
    assert again.reclaimed is False
    assert again.lease.id == first.lease.id
    assert again.lease.expires_at > first.lease.expires_at
    renewed = leases.renew(first.lease.id, "w1", ttl_seconds=90)
    assert renewed.expires_at >= again.lease.expires_at
    assert renewed.heartbeat_at >= again.lease.heartbeat_at


def test_claim_conflict_while_lease_is_live(tmp_path):
    store = _store(tmp_path)
    leases = WorkerLeases(store)
    leases.claim(scope="mission", scope_id="m1", mission_id="m1", owner_id="w1", ttl_seconds=30)
    with pytest.raises(LeaseConflict):
        leases.claim(scope="mission", scope_id="m1", mission_id="m1", owner_id="w2", ttl_seconds=30)
    with pytest.raises(LeaseConflict):
        held = leases.get("mission", "m1")
        leases.renew(held.id, "w2")


def test_expired_lease_is_reclaimable(tmp_path):
    store = _store(tmp_path)
    leases = WorkerLeases(store)
    first = leases.claim(scope="task", scope_id="task-9", mission_id="m1", owner_id="w1", ttl_seconds=30)
    with store.sessions.begin() as db:
        row = db.get(WorkerLeaseRow, first.lease.id)
        row.expires_at = utcnow() - timedelta(seconds=1)
    with pytest.raises(LeaseConflict):
        leases.renew(first.lease.id, "w1")
    reclaimed = leases.claim(scope="task", scope_id="task-9", mission_id="m1", owner_id="w2", ttl_seconds=30)
    assert reclaimed.reclaimed is True
    assert reclaimed.lease.owner_id == "w2"
    assert reclaimed.lease.expired() is False


def test_release_lets_another_worker_claim(tmp_path):
    store = _store(tmp_path)
    leases = WorkerLeases(store)
    first = leases.claim(scope="task", scope_id="task-2", mission_id="m1", owner_id="w1", ttl_seconds=30)
    released = leases.release(first.lease.id, "w1")
    assert released.status == "released"
    assert released.expired() is True
    second = leases.claim(scope="task", scope_id="task-2", mission_id="m1", owner_id="w2", ttl_seconds=30)
    assert second.reclaimed is False
    assert second.lease.owner_id == "w2"


def test_idempotency_requires_a_key_and_replays_payload(tmp_path):
    store = _store(tmp_path)
    guard = IdempotencyGuard(store)
    with pytest.raises(IdempotencyError):
        guard.require_key("  ")
    first = guard.record("m1", "pay-1", "payment", {"intent": {"id": "a", "amount": 2}})
    again = guard.record("m1", "pay-1", "payment", {"intent": {"id": "b", "amount": 99}})
    assert first == again
    assert again["intent"]["amount"] == 2
    found = guard.lookup("m1", "pay-1")
    assert found["status"] == "completed"


@pytest.mark.asyncio
async def test_runtime_payment_is_fail_closed_and_idempotent(tmp_path):
    store = _store(tmp_path)
    runtime = SwarmRuntime(store)
    mission = Mission(goal="pay", budget=10, limits={"max_payment_amount": 5})
    store.save_mission(mission)
    with pytest.raises(PolicyError) as missing:
        await runtime.create_payment(mission, "0xabc", 2, "test work")
    assert missing.value.failure_class == FailureClass.POLICY_REFUSAL
    first = await runtime.create_payment(mission, "0xabc", 2, "test work", idempotency_key="pay-1")
    replay = await runtime.create_payment(mission, "0xabc", 2, "test work", idempotency_key="pay-1")
    assert first.id == replay.id
    assert mission.spent == 2
    events = [e.event_type for e in store.events(mission.id)]
    assert events.count("payment.created") == 1


@pytest.mark.asyncio
async def test_runtime_tool_invoke_requires_idempotency_key(tmp_path):
    store = _store(tmp_path)
    runtime = SwarmRuntime(store, tools=LocalToolProvider(allowlist=["echo"]))
    mission = Mission(goal="tools", limits={"max_tool_calls": 2})
    store.save_mission(mission)
    with pytest.raises(PolicyError) as missing:
        await runtime.invoke_tool(mission, "echo", {"text": "hi"}, idempotency_key="  ")
    assert missing.value.failure_class == FailureClass.POLICY_REFUSAL
    first = await runtime.invoke_tool(mission, "echo", {"text": "hi"}, idempotency_key="echo-1")
    replay = await runtime.invoke_tool(mission, "echo", {"text": "hi"}, idempotency_key="echo-1")
    assert first["used"] == replay["used"] == 1
    assert first["output"]["text"] == replay["output"]["text"] == "hi"
    assert runtime.tool_calls_used(mission.id) == 1


@pytest.mark.asyncio
async def test_runtime_claim_renew_release_and_conflict_events(tmp_path):
    store = _store(tmp_path)
    holder = SwarmRuntime(store)
    other = SwarmRuntime(store)
    mission = Mission(goal="lease a task")
    store.save_mission(mission)
    task_id = str(uuid4())
    lease = await holder.claim_work(mission, "task", task_id, ttl_seconds=30)
    await holder.renew_work(mission, "task", task_id, ttl_seconds=45)
    with pytest.raises(LeaseConflict):
        await other.claim_work(mission, "task", task_id, ttl_seconds=30)
    await holder.release_work(mission, "task", task_id)
    taken = await other.claim_work(mission, "task", task_id, ttl_seconds=30)
    assert taken.owner_id == str(other.worker_id)
    types = [e.event_type for e in store.events(mission.id)]
    assert types.count("lease.claimed") == 2
    assert "lease.released" in types
    assert lease.owner_id == str(holder.worker_id)


@pytest.mark.asyncio
async def test_runtime_run_skips_mission_held_by_another_worker(tmp_path):
    store = _store(tmp_path)
    holder = SwarmRuntime(store)
    other = SwarmRuntime(store)
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await holder.claim_work(mission, "mission", str(mission.id), ttl_seconds=30)
    await other.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "pending"
    assert not any(e.event_type.startswith("mission.") for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_runtime_reclaims_expired_mission_lease(tmp_path):
    store = _store(tmp_path)
    stale = SwarmRuntime(store)
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    held = await stale.claim_work(mission, "mission", str(mission.id), ttl_seconds=30)
    with store.sessions.begin() as db:
        row = db.get(WorkerLeaseRow, held.id)
        row.expires_at = utcnow() - timedelta(seconds=1)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    types = [e.event_type for e in store.events(mission.id)]
    assert "lease.expired" in types
    assert "lease.claimed" in types
    assert "lease.released" in types
