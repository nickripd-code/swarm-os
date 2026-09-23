"""Read-only mission spend summary.

Replays recorded ``llm.completed`` token counts and ``budget.updated`` estimates.
Does not price tokens, call providers, or settle payments. Missing facts stay null.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .models import Mission, MissionEvent

ESTIMATE_UNAVAILABLE = "estimate unavailable"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _finite_nonneg(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _token_count(value: Any) -> int | None:
    number = _finite_nonneg(value)
    if number is None:
        return None
    return math.trunc(number)


def _payload(event: MissionEvent | Any) -> dict[str, Any]:
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, dict) else {}


def summarize_mission_spend(
    mission: Mission | None,
    events: list[Any],
    *,
    providers_configured: bool,
    live_spend_enabled: bool,
) -> dict[str, Any]:
    """Build a fail-closed summary. Dollars appear only from known budget events."""
    input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    tokens_recorded = False
    token_estimate: float | None = None
    token_estimate_known = False
    token_budget: float | None = None
    known_at: datetime | None = None

    for event in events:
        event_mission = getattr(event, "mission_id", None)
        if mission is not None and event_mission is not None and event_mission != mission.id:
            continue
        event_type = getattr(event, "event_type", "")
        payload = _payload(event)
        if event_type == "llm.completed":
            counted = False
            for key, bucket in (
                ("input_tokens", "input"),
                ("output_tokens", "output"),
                ("reasoning_tokens", "reasoning"),
            ):
                if key not in payload:
                    continue
                count = _token_count(payload.get(key))
                if count is None:
                    continue
                counted = True
                if bucket == "input":
                    input_tokens += count
                elif bucket == "output":
                    output_tokens += count
                else:
                    reasoning_tokens += count
            if counted:
                tokens_recorded = True
        elif event_type == "budget.updated":
            budget = _finite_nonneg(payload.get("token_budget"))
            if budget is not None:
                token_budget = budget
            if payload.get("known") is True:
                spent = _finite_nonneg(payload.get("token_spent"))
                if spent is not None:
                    token_estimate = spent
                    token_estimate_known = True
                    created_at = getattr(event, "created_at", None)
                    if isinstance(created_at, datetime):
                        known_at = created_at

    burn_known = False
    burn_usd_per_hour: float | None = None
    elapsed_seconds: float | None = None
    if (
        token_estimate_known
        and token_estimate is not None
        and mission is not None
        and isinstance(known_at, datetime)
    ):
        elapsed = (_aware(known_at) - _aware(mission.created_at)).total_seconds()
        if elapsed > 0:
            burn_known = True
            elapsed_seconds = round(elapsed, 3)
            burn_usd_per_hour = round(token_estimate / (elapsed / 3600), 8)

    payment_known = False
    payment_spent: float | None = None
    payment_budget: float | None = None
    live_payments: bool | None = None
    if mission is not None:
        spent = _finite_nonneg(mission.spent)
        budget = _finite_nonneg(mission.budget)
        live_payments = bool(mission.live_payments)
        if spent is not None and budget is not None:
            payment_known = True
            payment_spent = spent
            payment_budget = budget

    if mission is None:
        reason = "no_mission"
    elif token_estimate_known:
        reason = "recorded"
    elif not providers_configured:
        reason = "providers_unset"
    else:
        reason = "no_cost_data"

    note_parts: list[str] = []
    if mission is None:
        note_parts.append("No mission selected.")
    if token_estimate_known:
        note_parts.append("Recorded token estimate. Not an invoice.")
    else:
        note_parts.append("No cost data.")
    if not providers_configured:
        note_parts.append("Model providers are unset.")
    if live_spend_enabled:
        note_parts.append("Live spend is enabled.")
    else:
        note_parts.append("Live spend is off.")
    if mission is not None and mission.live_payments and not live_spend_enabled:
        note_parts.append("This mission requested live payments; settlement stays disabled.")

    tokens = None
    if tokens_recorded:
        tokens = {
            "input": input_tokens,
            "output": output_tokens,
            "reasoning": reasoning_tokens,
            "total": input_tokens + output_tokens + reasoning_tokens,
        }

    return {
        "mission_id": str(mission.id) if mission is not None else None,
        "state": "recorded" if token_estimate_known else "unavailable",
        "reason": reason,
        "providers_configured": bool(providers_configured),
        "live_spend_enabled": bool(live_spend_enabled),
        "live_payments": live_payments,
        "token_estimate_known": token_estimate_known,
        "token_estimate": token_estimate,
        "token_budget": token_budget,
        "currency": "USD",
        "tokens": tokens,
        "tokens_recorded": tokens_recorded,
        "burn_known": burn_known,
        "burn_usd_per_hour": burn_usd_per_hour,
        "elapsed_seconds": elapsed_seconds,
        "payment_known": payment_known,
        "payment_spent": payment_spent,
        "payment_budget": payment_budget,
        "note": " ".join(note_parts),
        "label": ESTIMATE_UNAVAILABLE if not token_estimate_known else None,
    }
