"""Durable work-item queue with lease-friendly dequeue.

Execution may still run in-process. Rows survive restart. Completing a job
requires an explicit complete() from the live lease owner — never invented.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .leases import ClaimOutcome, LeaseConflict, WorkerLeases
from .models import utcnow
from .store import Store, WorkItemRow, WorkerLeaseRow

JOB_STATUSES = frozenset({"pending", "claimed", "completed", "failed"})
DEFAULT_JOB_KIND = "work"


class QueueError(Exception):
    """Work item is missing, not claimable, or not legally completable."""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _dump_object(payload: dict[str, Any] | None) -> str:
    data = payload if payload is not None else {}
    if not isinstance(data, dict):
        raise QueueError("Work item payload must be an object")
    return json.dumps(data, default=str)


def _load_object(raw: str | None, *, required: bool) -> dict[str, Any] | None:
    if raw is None:
        if required:
            raise QueueError("Stored work item payload is missing")
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise QueueError("Stored work item payload is not an object")
    return data


@dataclass(frozen=True)
class WorkItem:
    id: str
    kind: str
    mission_id: str
    payload: dict[str, Any]
    status: str
    owner_id: str | None
    lease_id: str | None
    attempt: int
    available_at: datetime
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    result: dict[str, Any] | None

    def live(self, now: datetime | None = None) -> bool:
        moment = now or utcnow()
        return (
            self.status == "claimed"
            and self.expires_at is not None
            and _aware(self.expires_at) > moment
        )


@dataclass(frozen=True)
class ClaimedWork:
    item: WorkItem
    lease: ClaimOutcome


@dataclass(frozen=True)
class FailedWork:
    item: WorkItem
    released_lease_id: str
    retry_scheduled: bool


def _row_to_item(row: WorkItemRow) -> WorkItem:
    return WorkItem(
        id=row.id,
        kind=row.kind,
        mission_id=row.mission_id,
        payload=_load_object(row.payload, required=True) or {},
        status=row.status,
        owner_id=row.owner_id,
        lease_id=row.lease_id,
        attempt=row.attempt,
        available_at=_aware(row.available_at),
        expires_at=_aware(row.expires_at) if row.expires_at is not None else None,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
        completed_at=_aware(row.completed_at) if row.completed_at is not None else None,
        result=_load_object(row.result, required=False),
    )


def _held(row: WorkItemRow, now: datetime) -> bool:
    return (
        row.status == "claimed"
        and row.expires_at is not None
        and _aware(row.expires_at) > now
    )


def _available(row: WorkItemRow, now: datetime) -> bool:
    if row.status == "pending":
        return _aware(row.available_at) <= now
    if row.status == "claimed":
        return not _held(row, now)
    return False


class WorkQueue:
    def __init__(self, store: Store, leases: WorkerLeases | None = None):
        self.store = store
        self.leases = leases or WorkerLeases(store)

    def get(self, item_id: str) -> WorkItem | None:
        with self.store.sessions() as db:
            row = db.get(WorkItemRow, item_id)
            return _row_to_item(row) if row else None

    def enqueue(
        self,
        *,
        mission_id: str,
        kind: str = DEFAULT_JOB_KIND,
        payload: dict[str, Any] | None = None,
        item_id: str | None = None,
    ) -> WorkItem:
        name = (kind or "").strip()
        if not name:
            raise QueueError("Work item kind is required")
        if not mission_id:
            raise QueueError("Work item mission is required")
        now = utcnow()
        row = WorkItemRow(
            id=item_id or str(uuid4()),
            kind=name,
            mission_id=mission_id,
            payload=_dump_object(payload),
            status="pending",
            owner_id=None,
            lease_id=None,
            attempt=0,
            available_at=now,
            expires_at=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            result=None,
        )
        try:
            with self.store.sessions.begin() as db:
                db.add(row)
                db.flush()
                return _row_to_item(row)
        except IntegrityError as exc:
            raise QueueError(f"Work item {row.id} already exists") from exc

    def claim(
        self,
        *,
        owner_id: str,
        mission_id: str | None = None,
        item_id: str | None = None,
        kinds: Collection[str] | None = None,
        ttl_seconds: float | None = None,
    ) -> ClaimedWork | None:
        if not owner_id:
            raise QueueError("Lease owner is required")
        kind_filter = None
        if kinds is not None:
            candidates = (kinds,) if isinstance(kinds, str) else kinds
            kind_filter = frozenset(
                str(kind).strip() for kind in candidates if str(kind).strip()
            )
            if not kind_filter:
                raise QueueError("At least one accepted work kind is required")
        try:
            with self.store.sessions.begin() as db:
                now = utcnow()
                row = self._select_row(
                    db,
                    item_id=item_id,
                    mission_id=mission_id,
                    owner_id=owner_id,
                    kinds=kind_filter,
                    now=now,
                )
                if row is None:
                    return None
                was_pending = row.status == "pending"
                outcome = self.leases.claim_in_session(
                    db,
                    scope="job",
                    scope_id=row.id,
                    mission_id=row.mission_id,
                    owner_id=owner_id,
                    ttl_seconds=ttl_seconds,
                )
                row.status = "claimed"
                row.owner_id = owner_id
                row.lease_id = outcome.lease.id
                row.expires_at = outcome.lease.expires_at
                row.updated_at = now
                if was_pending or outcome.reclaimed:
                    row.attempt = int(row.attempt or 0) + 1
                db.flush()
                return ClaimedWork(item=_row_to_item(row), lease=outcome)
        except IntegrityError as exc:
            raise LeaseConflict("Work item could not be claimed") from exc

    def heartbeat(
        self,
        item_id: str,
        owner_id: str,
        *,
        ttl_seconds: float | None = None,
    ) -> WorkItem:
        """Atomically extend a live job claim without reclaiming expired work."""
        if not owner_id:
            raise QueueError("Lease owner is required")
        with self.store.sessions.begin() as db:
            row = db.get(WorkItemRow, item_id)
            if row is None:
                raise QueueError("Work item not found")
            if row.status != "claimed":
                raise QueueError("Only a claimed work item can be heartbeated")
            if row.owner_id != owner_id:
                raise LeaseConflict("Only the claiming worker can heartbeat a work item")
            now = utcnow()
            if row.expires_at is None or _aware(row.expires_at) <= now:
                raise LeaseConflict("Expired jobs must be reclaimed, not heartbeated")
            if not row.lease_id:
                raise QueueError("Claimed work item is missing a lease")
            lease_row = db.get(WorkerLeaseRow, row.lease_id)
            if (
                lease_row is None
                or lease_row.scope != "job"
                or lease_row.scope_id != row.id
                or lease_row.mission_id != row.mission_id
            ):
                raise QueueError("Claimed work item has an invalid lease")
            if lease_row.owner_id != owner_id or lease_row.status != "claimed":
                raise LeaseConflict("Only the live lease owner can heartbeat a work item")
            if _aware(lease_row.expires_at) <= now:
                raise LeaseConflict("Expired jobs must be reclaimed, not heartbeated")
            outcome = self.leases.claim_in_session(
                db,
                scope="job",
                scope_id=row.id,
                mission_id=row.mission_id,
                owner_id=owner_id,
                ttl_seconds=ttl_seconds,
            )
            if outcome.reclaimed or outcome.lease.id != row.lease_id:
                raise LeaseConflict("Expired jobs must be reclaimed, not heartbeated")
            row.expires_at = outcome.lease.expires_at
            row.updated_at = now
            db.flush()
            return _row_to_item(row)

    def complete(
        self,
        item_id: str,
        owner_id: str,
        result: dict[str, Any] | None = None,
    ) -> WorkItem:
        if not owner_id:
            raise QueueError("Lease owner is required")
        if result is not None and not isinstance(result, dict):
            raise QueueError("Work item result must be an object")
        with self.store.sessions.begin() as db:
            row = db.get(WorkItemRow, item_id)
            if row is None:
                raise QueueError("Work item not found")
            if row.status in {"completed", "failed"}:
                raise QueueError(f"Work item already {row.status}")
            if row.status != "claimed":
                raise QueueError("Only a claimed work item can be completed")
            if row.owner_id != owner_id:
                raise LeaseConflict("Only the claiming worker can complete a work item")
            now = utcnow()
            if row.expires_at is None or _aware(row.expires_at) <= now:
                raise LeaseConflict("Expired jobs must be reclaimed, not completed")
            if not row.lease_id:
                raise QueueError("Claimed work item is missing a lease")
            self.leases.release_in_session(db, row.lease_id, owner_id)
            row.status = "completed"
            row.completed_at = now
            row.updated_at = now
            row.expires_at = now
            row.result = _dump_object(result)
            db.flush()
            return _row_to_item(row)

    def fail(
        self,
        item_id: str,
        owner_id: str,
        error: dict[str, Any],
        *,
        mission_id: str | None = None,
        retry_at: datetime | None = None,
    ) -> FailedWork:
        """Record a real worker failure and optionally requeue after a not-before time."""
        if not owner_id:
            raise QueueError("Lease owner is required")
        if not isinstance(error, dict) or not error:
            raise QueueError("Work item failure must be a non-empty object")
        with self.store.sessions.begin() as db:
            row = db.get(WorkItemRow, item_id)
            if row is None:
                raise QueueError("Work item not found")
            if mission_id and row.mission_id != mission_id:
                raise QueueError("Work item does not belong to this mission")
            if row.status in {"completed", "failed"}:
                raise QueueError(f"Work item already {row.status}")
            if row.status != "claimed":
                raise QueueError("Only a claimed work item can report failure")
            if row.owner_id != owner_id:
                raise LeaseConflict("Only the claiming worker can fail a work item")
            now = utcnow()
            if row.expires_at is None or _aware(row.expires_at) <= now:
                raise LeaseConflict("Expired jobs must be reclaimed, not failed")
            if not row.lease_id:
                raise QueueError("Claimed work item is missing a lease")
            released_lease_id = row.lease_id
            self.leases.release_in_session(db, released_lease_id, owner_id)
            row.result = _dump_object(error)
            row.updated_at = now
            if retry_at is None:
                row.status = "failed"
                row.completed_at = now
                row.expires_at = now
                retry_scheduled = False
            else:
                row.status = "pending"
                row.owner_id = None
                row.lease_id = None
                row.available_at = _aware(retry_at)
                row.expires_at = None
                row.completed_at = None
                retry_scheduled = True
            db.flush()
            return FailedWork(
                item=_row_to_item(row),
                released_lease_id=released_lease_id,
                retry_scheduled=retry_scheduled,
            )

    def _select_row(self, db, *, item_id: str | None, mission_id: str | None,
                    owner_id: str, kinds: frozenset[str] | None,
                    now: datetime) -> WorkItemRow | None:
        if item_id:
            row = db.get(WorkItemRow, item_id)
            if row is None:
                raise QueueError("Work item not found")
            if mission_id and row.mission_id != mission_id:
                raise QueueError("Work item does not belong to this mission")
            if kinds is not None and row.kind not in kinds:
                raise QueueError("Work item kind is not accepted by this worker")
            if row.status in {"completed", "failed"}:
                raise QueueError(f"Work item already {row.status}")
            if row.status not in JOB_STATUSES:
                raise QueueError(f"Unsupported work item status: {row.status}")
            if _held(row, now) and row.owner_id != owner_id:
                raise LeaseConflict(f"job {item_id} is leased by another worker")
            if _held(row, now) or _available(row, now):
                return row
            raise LeaseConflict(f"job {item_id} is leased by another worker")
        query = select(WorkItemRow).where(WorkItemRow.status.in_(("pending", "claimed")))
        if mission_id:
            query = query.where(WorkItemRow.mission_id == mission_id)
        if kinds is not None:
            query = query.where(WorkItemRow.kind.in_(sorted(kinds)))
        rows = db.scalars(query.order_by(WorkItemRow.created_at, WorkItemRow.id)).all()
        for row in rows:
            if _available(row, now):
                return row
        return None
