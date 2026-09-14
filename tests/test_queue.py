from datetime import timedelta

import pytest

from app.leases import LeaseConflict, WorkerLeases
from app.llm import FallbackController
from app.models import FailureClass, Mission, utcnow
from app.queue import QueueError, WorkQueue
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store, WorkItemRow, WorkerLeaseRow


def _store(tmp_path) -> Store:
    return Store(str(tmp_path / "swarm.db"))


def _expire(store: Store, item_id: str) -> None:
    past = utcnow() - timedelta(seconds=1)
    with store.sessions.begin() as db:
        item = db.get(WorkItemRow, item_id)
        item.expires_at = past
        if item.lease_id:
            lease = db.get(WorkerLeaseRow, item.lease_id)
            lease.expires_at = past


def _make_available(store: Store, item_id: str) -> None:
    with store.sessions.begin() as db:
        db.get(WorkItemRow, item_id).available_at = utcnow() - timedelta(seconds=1)


def test_enqueue_claim_complete(tmp_path):
    store = _store(tmp_path)
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="echo", payload={"text": "hi"})
    assert item.status == "pending"
    assert item.result is None
    claimed = queue.claim(owner_id="w1", mission_id="m1", item_id=item.id, ttl_seconds=30)
    assert claimed is not None
    assert claimed.item.status == "claimed"
    assert claimed.item.owner_id == "w1"
    assert claimed.item.attempt == 1
    assert claimed.lease.reclaimed is False
    done = queue.complete(item.id, "w1", result={"ok": True})
    assert done.status == "completed"
    assert done.result == {"ok": True}
    assert queue.get(item.id).status == "completed"
    with pytest.raises(QueueError, match="already completed"):
        queue.complete(item.id, "w1", result={"ok": False})
    assert queue.get(item.id).result == {"ok": True}


def test_double_claim_fail_closed(tmp_path):
    store = _store(tmp_path)
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="work")
    first = queue.claim(owner_id="w1", item_id=item.id, ttl_seconds=30)
    assert first.item.live() is True
    with pytest.raises(LeaseConflict):
        queue.claim(owner_id="w2", item_id=item.id, ttl_seconds=30)
    again = queue.claim(owner_id="w1", item_id=item.id, ttl_seconds=45)
    assert again.item.id == item.id
    assert again.lease.reclaimed is False
    other = WorkQueue(store)
    with pytest.raises(LeaseConflict):
        other.claim(owner_id="w2", item_id=item.id, ttl_seconds=30)
    assert queue.get(item.id).owner_id == "w1"
    assert queue.get(item.id).status == "claimed"


def test_lease_expiry_is_reclaimable_and_complete_fail_closed(tmp_path):
    store = _store(tmp_path)
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="work")
    first = queue.claim(owner_id="w1", item_id=item.id, ttl_seconds=30)
    _expire(store, first.item.id)
    with pytest.raises(LeaseConflict, match="reclaimed"):
        queue.complete(item.id, "w1", result={"ok": True})
    assert queue.get(item.id).status == "claimed"
    assert queue.get(item.id).result is None
    reclaimed = queue.claim(owner_id="w2", item_id=item.id, ttl_seconds=30)
    assert reclaimed.lease.reclaimed is True
    assert reclaimed.item.owner_id == "w2"
    assert reclaimed.item.attempt == 2
    with pytest.raises(LeaseConflict):
        queue.complete(item.id, "w1", result={"stolen": True})
    done = queue.complete(item.id, "w2", result={"ok": True})
    assert done.status == "completed"
    assert done.result == {"ok": True}


def test_restart_persistence(tmp_path):
    path = str(tmp_path / "queue.db")
    first_store = Store(path)
    first = WorkQueue(first_store)
    pending = first.enqueue(mission_id="m1", kind="persist", payload={"n": 1})
    claimed_id = first.enqueue(mission_id="m1", kind="persist", payload={"n": 2}).id
    first.claim(owner_id="w1", item_id=claimed_id, ttl_seconds=30)

    reopened = WorkQueue(Store(path))
    loaded_pending = reopened.get(pending.id)
    loaded_claimed = reopened.get(claimed_id)
    assert loaded_pending.status == "pending"
    assert loaded_pending.payload == {"n": 1}
    assert loaded_claimed.status == "claimed"
    assert loaded_claimed.owner_id == "w1"
    assert loaded_claimed.result is None

    dequeued = reopened.claim(owner_id="w2", mission_id="m1", ttl_seconds=30)
    assert dequeued.item.id == pending.id
    done = reopened.complete(pending.id, "w2", result={"n": 1})
    assert done.status == "completed"

    after = WorkQueue(Store(path))
    assert after.get(pending.id).status == "completed"
    assert after.get(pending.id).result == {"n": 1}
    assert after.get(claimed_id).status == "claimed"
    assert after.claim(owner_id="w2", mission_id="m1") is None
    held = after.get(claimed_id)
    assert WorkerLeases(Store(path)).get("job", held.id).owner_id == "w1"


def test_complete_does_not_invent_success_for_pending(tmp_path):
    store = _store(tmp_path)
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="work")
    with pytest.raises(QueueError, match="claimed"):
        queue.complete(item.id, "w1", result={"ok": True})
    assert queue.get(item.id).status == "pending"
    assert queue.get(item.id).result is None
    assert queue.claim(owner_id="w1", mission_id="m1") is not None
    assert queue.claim(owner_id="w1", mission_id="m1") is None


def test_terminal_failure_releases_lease_and_survives_restart(tmp_path):
    path = str(tmp_path / "queue.db")
    store = Store(path)
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="work", payload={"n": 1})
    claimed = queue.claim(owner_id="w1", item_id=item.id, ttl_seconds=30)
    failed = queue.fail(
        item.id,
        "w1",
        {"error": "worker crashed", "failure_class": "MODEL_FAILURE"},
    )
    assert failed.retry_scheduled is False
    assert failed.released_lease_id == claimed.item.lease_id
    assert failed.item.status == "failed"
    assert failed.item.result == {
        "error": "worker crashed",
        "failure_class": "MODEL_FAILURE",
    }
    assert failed.item.completed_at is not None
    with store.sessions() as db:
        lease = db.get(WorkerLeaseRow, failed.released_lease_id)
        assert lease.status == "released"
    reopened = WorkQueue(Store(path))
    assert reopened.get(item.id).status == "failed"
    with pytest.raises(QueueError, match="already failed"):
        reopened.claim(owner_id="w2", item_id=item.id)
    with pytest.raises(QueueError, match="already failed"):
        reopened.complete(item.id, "w1", {"invented": "success"})
    with pytest.raises(QueueError, match="already failed"):
        reopened.fail(item.id, "w1", {"error": "again"})


def test_retry_failure_is_not_claimable_until_available_then_reclaims(tmp_path):
    store = _store(tmp_path)
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="work")
    claimed = queue.claim(owner_id="w1", item_id=item.id, ttl_seconds=30)
    retry_at = utcnow() + timedelta(minutes=5)
    failed = queue.fail(
        item.id,
        "w1",
        {"error": "temporary", "failure_class": "PROVIDER_OUTAGE"},
        retry_at=retry_at,
    )
    assert failed.retry_scheduled is True
    assert failed.released_lease_id == claimed.item.lease_id
    assert failed.item.status == "pending"
    assert failed.item.owner_id is None
    assert failed.item.lease_id is None
    assert failed.item.expires_at is None
    assert failed.item.result["failure_class"] == "PROVIDER_OUTAGE"
    with pytest.raises(LeaseConflict):
        queue.claim(owner_id="w2", item_id=item.id)
    _make_available(store, item.id)
    retried = queue.claim(owner_id="w2", item_id=item.id, ttl_seconds=30)
    assert retried.item.attempt == 2
    assert retried.item.owner_id == "w2"
    done = queue.complete(item.id, "w2", {"ok": True})
    assert done.status == "completed"
    assert done.result == {"ok": True}


def test_failure_rejects_foreign_or_expired_owner_without_mutation(tmp_path):
    store = _store(tmp_path)
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="work")
    queue.claim(owner_id="w1", item_id=item.id, ttl_seconds=30)
    with pytest.raises(LeaseConflict, match="claiming worker"):
        queue.fail(item.id, "w2", {"error": "foreign"})
    assert queue.get(item.id).status == "claimed"
    _expire(store, item.id)
    with pytest.raises(LeaseConflict, match="reclaimed"):
        queue.fail(item.id, "w1", {"error": "late"})
    assert queue.get(item.id).status == "claimed"


@pytest.mark.asyncio
async def test_runtime_enqueue_claim_complete_and_double_claim(tmp_path):
    store = _store(tmp_path)
    holder = SwarmRuntime(store, controller=FallbackController())
    other = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="queue seed")
    store.save_mission(mission)
    item = await holder.enqueue_job(mission, "echo", {"text": "hi"})
    claimed = await holder.claim_job(mission, item.id, ttl_seconds=30)
    assert claimed.status == "claimed"
    with pytest.raises(PolicyError) as conflict:
        await other.claim_job(mission, item.id, ttl_seconds=30)
    assert conflict.value.failure_class == FailureClass.POLICY_REFUSAL
    done = await holder.complete_job(mission, item.id, {"echo": "hi"})
    assert done.status == "completed"
    types = [event.event_type for event in store.events(mission.id)]
    assert types.count("job.enqueued") == 1
    assert types.count("lease.claimed") == 1
    assert types.count("job.completed") == 1
    assert "lease.released" in types
    with pytest.raises(PolicyError):
        await holder.complete_job(mission, item.id, {"echo": "nope"})


@pytest.mark.asyncio
async def test_runtime_queue_survives_restart(tmp_path):
    path = str(tmp_path / "swarm.db")
    mission = Mission(goal="persist jobs")
    first = SwarmRuntime(Store(path), controller=FallbackController())
    first.store.save_mission(mission)
    item = await first.enqueue_job(mission, "work", {"n": 1})
    second = SwarmRuntime(Store(path), controller=FallbackController())
    claimed = await second.claim_job(mission, item.id, ttl_seconds=30)
    assert claimed.status == "claimed"
    third = SwarmRuntime(Store(path), controller=FallbackController())
    with pytest.raises(PolicyError) as conflict:
        await third.claim_job(mission, item.id, ttl_seconds=30)
    assert conflict.value.failure_class == FailureClass.POLICY_REFUSAL
    done = await second.complete_job(mission, item.id, {"n": 1})
    assert done.status == "completed"
    after = SwarmRuntime(Store(path), controller=FallbackController())
    loaded = after.queue.get(item.id)
    assert loaded.status == "completed"
    assert loaded.result == {"n": 1}
    with pytest.raises(PolicyError):
        await after.complete_job(mission, item.id, {"n": 99})


@pytest.mark.asyncio
async def test_runtime_fail_job_emits_terminal_and_retry_events(tmp_path):
    store = _store(tmp_path)
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="report real job failures")
    store.save_mission(mission)

    terminal = await runtime.enqueue_job(mission, "work", {"n": 1})
    await runtime.claim_job(mission, terminal.id, ttl_seconds=30)
    failed = await runtime.fail_job(
        mission,
        terminal.id,
        "worker crashed",
        FailureClass.MODEL_FAILURE,
    )
    assert failed.status == "failed"

    retried = await runtime.enqueue_job(mission, "work", {"n": 2})
    await runtime.claim_job(mission, retried.id, ttl_seconds=30)
    pending = await runtime.fail_job(
        mission,
        retried.id,
        "provider unavailable",
        FailureClass.PROVIDER_OUTAGE,
        retry_at=utcnow() + timedelta(minutes=1),
    )
    assert pending.status == "pending"
    events = store.events(mission.id)
    terminal_event = next(event for event in events if event.event_type == "job.failed")
    assert terminal_event.payload["failure_class"] == "MODEL_FAILURE"
    retry_event = next(event for event in events if event.event_type == "job.retry_scheduled")
    assert retry_event.payload["failure_class"] == "PROVIDER_OUTAGE"
    assert retry_event.payload["available_at"]
    releases = [event for event in events if event.event_type == "lease.released"]
    assert len(releases) == 2
    assert all(event.payload["lease_id"] for event in releases)


@pytest.mark.asyncio
async def test_runtime_fail_job_cannot_attribute_failure_to_another_mission(tmp_path):
    store = _store(tmp_path)
    runtime = SwarmRuntime(store, controller=FallbackController())
    owner = Mission(goal="owns the job")
    other = Mission(goal="must not receive job events")
    store.save_mission(owner)
    store.save_mission(other)
    item = await runtime.enqueue_job(owner, "work")
    await runtime.claim_job(owner, item.id, ttl_seconds=30)
    with pytest.raises(PolicyError, match="does not belong"):
        await runtime.fail_job(
            other,
            item.id,
            "wrong mission",
            FailureClass.MODEL_FAILURE,
        )
    assert runtime.queue.get(item.id).status == "claimed"
    assert not any(event.event_type == "job.failed" for event in store.events(other.id))
