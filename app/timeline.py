"""Read-only recent-event timeline projected from the durable mission log."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
_SUMMARY_KEYS = ("failure_class", "action", "role", "tool", "kind", "status", "question_id")
_MAX_SUMMARY = 80


def _summary(payload: Any) -> str | None:
    """One short stored field. Free-form payload text is not turned into a story."""
    if not isinstance(payload, dict):
        return None
    for key in _SUMMARY_KEYS:
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        text = " ".join(value.split())
        if text:
            return text[:_MAX_SUMMARY]
    return None


def recent_events(events: list[Any], *, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Last `limit` rows, oldest first. Rows without an event type are dropped."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit must be between 1 and 50")
    rows: list[dict[str, Any]] = []
    for event in list(events)[-limit:]:
        event_type = getattr(event, "event_type", None)
        if not isinstance(event_type, str) or not event_type.strip():
            continue
        created = getattr(event, "created_at", None)
        actor = getattr(event, "actor_id", None)
        rows.append({
            "id": getattr(event, "id", None),
            "event_type": event_type,
            "created_at": created.isoformat() if isinstance(created, datetime) else None,
            "actor_id": str(actor) if actor else None,
            "summary": _summary(getattr(event, "payload", None)),
        })
    return rows


def mission_timeline(store: Any, mission_id: UUID, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Fail closed: missing missions and empty logs produce no events."""
    if store.get_mission(mission_id) is None:
        return {"available": False, "state": "no_mission", "events": []}
    rows = recent_events(store.events(mission_id), limit=limit)
    if not rows:
        return {"available": True, "state": "empty", "events": []}
    return {"available": True, "state": "ok", "events": rows}
