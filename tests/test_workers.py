from __future__ import annotations

import os
import time
from datetime import timedelta

from app.models import utcnow
from app.queue import WorkQueue
from app.store import Store, WorkItemRow, WorkerLeaseRow
from app.workers import ProcessWorkerPool


def _wait_for(queue: WorkQueue, item_id: str, status: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = queue.get(item_id)
        if item is not None and item.status == status:
            return item
        time.sleep(0.02)
    item = queue.get(item_id)
    raise AssertionError(f"work item did not become {status!r}; last state: {item!r}")


def _expire(store: Store, item_id: str) -> None:
    past = utcnow() - timedelta(seconds=1)
    with store.sessions.begin() as db:
        item = db.get(WorkItemRow, item_id)
        item.expires_at = past
        lease = db.get(WorkerLeaseRow, item.lease_id)
        lease.expires_at = past


def test_process_worker_spawns_claims_and_completes(tmp_path):
    path = tmp_path / "swarm.db"
    queue = WorkQueue(Store(str(path)))
    unsupported = queue.enqueue(mission_id="m1", kind="other", payload={"text": "skip"})
    item = queue.enqueue(mission_id="m1", kind="echo", payload={"text": "hello"})
    pool = ProcessWorkerPool(path, {"echo": "tests.worker_handlers:echo"})
    try:
        workers = pool.start()
        completed = _wait_for(queue, item.id, "completed")
        assert len(workers) == 1
        assert workers[0].pid != os.getpid()
        assert completed.owner_id == workers[0].owner_id
        assert completed.attempt == 1
        assert completed.result == {
            "text": "hello",
            "pid": workers[0].pid,
            "attempt": 1,
        }
        assert queue.get(unsupported.id).status == "pending"
    finally:
        pool.stop()


def test_process_worker_respects_foreign_live_lease(tmp_path):
    path = tmp_path / "swarm.db"
    queue = WorkQueue(Store(str(path)))
    item = queue.enqueue(mission_id="m1", kind="echo", payload={"text": "held"})
    parent_claim = queue.claim(owner_id="parent-owner", item_id=item.id, ttl_seconds=5)
    pool = ProcessWorkerPool(
        path,
        {"echo": "tests.worker_handlers:echo"},
        poll_interval_seconds=0.02,
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.1,
    )
    try:
        pool.start()
        time.sleep(0.25)
        still_held = queue.get(item.id)
        assert still_held.status == "claimed"
        assert still_held.owner_id == "parent-owner"
        assert still_held.lease_id == parent_claim.item.lease_id
        assert still_held.attempt == 1
        assert still_held.result is None
        completed = queue.complete(item.id, "parent-owner", {"source": "parent"})
        assert completed.result == {"source": "parent"}
    finally:
        pool.stop()


def test_process_worker_heartbeats_long_job_without_reclaim(tmp_path):
    path = tmp_path / "swarm.db"
    queue = WorkQueue(Store(str(path)))
    item = queue.enqueue(
        mission_id="m1",
        kind="slow",
        payload={"text": "slow", "sleep_seconds": 1.5},
    )
    pool = ProcessWorkerPool(
        path,
        {"slow": "tests.worker_handlers:slow_echo"},
        process_count=2,
        poll_interval_seconds=0.01,
        lease_ttl_seconds=0.75,
        heartbeat_interval_seconds=0.1,
    )
    try:
        pool.start()
        completed = _wait_for(queue, item.id, "completed")
        assert completed.attempt == 1
        assert completed.result["text"] == "slow"
        assert completed.result["pid"] in {worker.pid for worker in pool.workers}
    finally:
        pool.stop()


def test_process_worker_reclaims_expired_job(tmp_path):
    path = tmp_path / "swarm.db"
    store = Store(str(path))
    queue = WorkQueue(store)
    item = queue.enqueue(mission_id="m1", kind="echo", payload={"text": "reclaimed"})
    queue.claim(owner_id="dead-owner", item_id=item.id, ttl_seconds=30)
    _expire(store, item.id)
    pool = ProcessWorkerPool(
        path,
        {"echo": "tests.worker_handlers:echo"},
        poll_interval_seconds=0.01,
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.1,
    )
    try:
        worker = pool.start()[0]
        completed = _wait_for(queue, item.id, "completed")
        assert completed.owner_id == worker.owner_id
        assert completed.attempt == 2
        assert completed.result["attempt"] == 2
    finally:
        pool.stop()


def test_process_worker_records_real_handler_failure(tmp_path):
    path = tmp_path / "swarm.db"
    queue = WorkQueue(Store(str(path)))
    item = queue.enqueue(
        mission_id="m1",
        kind="fail",
        payload={"error": "real worker failure"},
    )
    pool = ProcessWorkerPool(path, {"fail": "tests.worker_handlers:fail"})
    try:
        worker = pool.start()[0]
        failed = _wait_for(queue, item.id, "failed")
        assert failed.owner_id == worker.owner_id
        assert failed.attempt == 1
        assert failed.result == {
            "error": "real worker failure",
            "failure_class": "TOOL_FAILURE",
        }
    finally:
        pool.stop()


def test_process_worker_supplies_trusted_context_outside_payload(tmp_path):
    path = tmp_path / "swarm.db"
    queue = WorkQueue(Store(str(path)))
    item = queue.enqueue(mission_id="m1", kind="context", payload={"task_id": "only"})
    pool = ProcessWorkerPool(path, {"context": "tests.worker_handlers:context_echo"})
    try:
        worker = pool.start()[0]
        completed = _wait_for(queue, item.id, "completed")
        assert completed.payload == {"task_id": "only"}
        assert completed.result == {
            "database_path": str(path.resolve()),
            "owner_id": worker.owner_id,
            "pid": worker.pid,
        }
    finally:
        pool.stop()


def test_process_worker_preserves_classified_handler_failure(tmp_path):
    path = tmp_path / "swarm.db"
    queue = WorkQueue(Store(str(path)))
    item = queue.enqueue(mission_id="m1", kind="auth", payload={})
    pool = ProcessWorkerPool(path, {"auth": "tests.worker_handlers:authorization_failure"})
    try:
        pool.start()
        failed = _wait_for(queue, item.id, "failed")
        assert failed.result == {
            "error": "worker provider is unconfigured",
            "failure_class": "AUTHORIZATION_REQUIRED",
        }
    finally:
        pool.stop()
