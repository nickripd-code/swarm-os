"""Durable worker leases and side-effect idempotency records.

Execution is still in-process asyncio. These records let a restarted process
claim unfinished work without double-running a side-effecting step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import utcnow
from .store import IdempotencyRow, Store, WorkerLeaseRow

LEASE_SCOPES = frozenset({"mission", "task"})
DEFAULT_LEASE_TTL_SECONDS = 60.0


class LeaseError(Exception):
    pass


class LeaseConflict(LeaseError):
    """Another worker holds an unexpired lease on this scope."""


class IdempotencyError(Exception):
    """Side-effecting work is missing a key or has an unknown prior outcome."""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass(frozen=True)
class WorkerLease:
    id: str
    scope: str
    scope_id: str
    mission_id: str
    owner_id: str
    status: str
    expires_at: datetime
    heartbeat_at: datetime
    created_at: datetime

    def expired(self, now: datetime | None = None) -> bool:
        return self.status != "claimed" or _aware(self.expires_at) <= (now or utcnow())


@dataclass(frozen=True)
class ClaimOutcome:
    lease: WorkerLease
    reclaimed: bool


def _row_to_lease(row: WorkerLeaseRow) -> WorkerLease:
    return WorkerLease(
        id=row.id,
        scope=row.scope,
        scope_id=row.scope_id,
        mission_id=row.mission_id,
        owner_id=row.owner_id,
        status=row.status,
        expires_at=_aware(row.expires_at),
        heartbeat_at=_aware(row.heartbeat_at),
        created_at=_aware(row.created_at),
    )


class WorkerLeases:
    def __init__(self, store: Store, default_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS):
        self.store = store
        self.default_ttl_seconds = default_ttl_seconds

    def _ttl(self, ttl_seconds: float | None) -> float:
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise LeaseError("Lease TTL must be positive")
        return ttl

    def get(self, scope: str, scope_id: str) -> WorkerLease | None:
        with self.store.sessions() as db:
            row = db.scalar(
                select(WorkerLeaseRow).where(
                    WorkerLeaseRow.scope == scope,
                    WorkerLeaseRow.scope_id == scope_id,
                )
            )
            return _row_to_lease(row) if row else None

    def claim(
        self,
        *,
        scope: str,
        scope_id: str,
        mission_id: str,
        owner_id: str,
        ttl_seconds: float | None = None,
    ) -> ClaimOutcome:
        if scope not in LEASE_SCOPES:
            raise LeaseError(f"Unsupported lease scope: {scope}")
        if not owner_id:
            raise LeaseError("Lease owner is required")
        ttl = self._ttl(ttl_seconds)
        now = utcnow()
        expires = now + timedelta(seconds=ttl)
        try:
            with self.store.sessions.begin() as db:
                row = db.scalar(
                    select(WorkerLeaseRow).where(
                        WorkerLeaseRow.scope == scope,
                        WorkerLeaseRow.scope_id == scope_id,
                    )
                )
                if row is None:
                    row = WorkerLeaseRow(
                        id=str(uuid4()),
                        scope=scope,
                        scope_id=scope_id,
                        mission_id=mission_id,
                        owner_id=owner_id,
                        status="claimed",
                        expires_at=expires,
                        heartbeat_at=now,
                        created_at=now,
                    )
                    db.add(row)
                    db.flush()
                    return ClaimOutcome(lease=_row_to_lease(row), reclaimed=False)
                held = row.status == "claimed" and _aware(row.expires_at) > now
                if held and row.owner_id != owner_id:
                    raise LeaseConflict(f"{scope} {scope_id} is leased by another worker")
                reclaimed = not held and row.status == "claimed"
                row.mission_id = mission_id
                row.owner_id = owner_id
                row.status = "claimed"
                row.expires_at = expires
                row.heartbeat_at = now
                db.flush()
                return ClaimOutcome(lease=_row_to_lease(row), reclaimed=reclaimed)
        except IntegrityError as exc:
            existing = self.get(scope, scope_id)
            if existing and not existing.expired() and existing.owner_id != owner_id:
                raise LeaseConflict(f"{scope} {scope_id} is leased by another worker") from exc
            raise LeaseConflict(f"{scope} {scope_id} could not be claimed") from exc

    def renew(self, lease_id: str, owner_id: str, ttl_seconds: float | None = None) -> WorkerLease:
        ttl = self._ttl(ttl_seconds)
        now = utcnow()
        with self.store.sessions.begin() as db:
            row = db.get(WorkerLeaseRow, lease_id)
            if row is None:
                raise LeaseError("Lease not found")
            if row.owner_id != owner_id or row.status != "claimed":
                raise LeaseConflict("Only the claiming worker can renew a live lease")
            if _aware(row.expires_at) <= now:
                raise LeaseConflict("Expired leases must be reclaimed, not renewed")
            row.expires_at = now + timedelta(seconds=ttl)
            row.heartbeat_at = now
            db.flush()
            return _row_to_lease(row)

    def release(self, lease_id: str, owner_id: str) -> WorkerLease:
        now = utcnow()
        with self.store.sessions.begin() as db:
            row = db.get(WorkerLeaseRow, lease_id)
            if row is None:
                raise LeaseError("Lease not found")
            if row.owner_id != owner_id:
                raise LeaseConflict("Only the claiming worker can release a lease")
            row.status = "released"
            row.expires_at = now
            row.heartbeat_at = now
            db.flush()
            return _row_to_lease(row)


class IdempotencyGuard:
    """Fail-closed replay for side-effecting steps (including simulated ones)."""

    def __init__(self, store: Store):
        self.store = store

    def require_key(self, key: str | None) -> str:
        if not key or not str(key).strip():
            raise IdempotencyError("Side-effecting step requires an idempotency key")
        return str(key).strip()

    def lookup(self, mission_id: str, key: str) -> dict[str, Any] | None:
        with self.store.sessions() as db:
            row = db.scalar(
                select(IdempotencyRow).where(
                    IdempotencyRow.mission_id == mission_id,
                    IdempotencyRow.key == key,
                )
            )
            if row is None:
                return None
            return {"status": row.status, "step": row.step, "payload": _load_payload(row.payload)}

    def record(self, mission_id: str, key: str, step: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a completed outcome. Same key returns the first stored payload."""
        existing = self.lookup(mission_id, key)
        if existing is not None:
            if existing["status"] != "completed":
                raise IdempotencyError("Idempotency key has an unknown prior outcome")
            return existing["payload"]
        now = utcnow()
        try:
            with self.store.sessions.begin() as db:
                db.add(IdempotencyRow(
                    mission_id=mission_id,
                    key=key,
                    step=step,
                    status="completed",
                    payload=_dump_payload(payload),
                    created_at=now,
                ))
        except IntegrityError:
            existing = self.lookup(mission_id, key)
            if existing is None:
                raise
            if existing["status"] != "completed":
                raise IdempotencyError("Idempotency key has an unknown prior outcome")
            return existing["payload"]
        return payload


def _dump_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


def _load_payload(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise IdempotencyError("Stored idempotency payload is not an object")
    return data
