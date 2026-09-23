"""Human change-budget patch. Caps only — never derives USD from token counts."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from pydantic import ValidationError

from .models import LimitFieldPatch, MissionBudgetPatch, MissionLimits
from .resources import round_cost

# Floors and hard caps match MissionLimits Field bounds. max_token_cost's ceiling
# is TokenCostSettings.hard_cap, applied by the caller. max_payment_amount has a
# floor and no separate dollar ceiling in the model.
INT_LIMITS: dict[str, tuple[int, int]] = {
    "max_depth": (0, 20),
    "max_agents": (1, 500),
    "max_tasks": (1, 1000),
    "max_tool_calls": (1, 10000),
    "max_runtime_seconds": (1, 86400),
}
FLOAT_LIMITS: dict[str, tuple[float, float | None]] = {
    "max_payment_amount": (0.0, None),
}
TOKEN_LIMIT = "max_token_cost"
ALLOWLISTED_LIMITS = frozenset([*INT_LIMITS, *FLOAT_LIMITS, TOKEN_LIMIT])


class BudgetUpdateError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def same_timestamp(left: datetime, right: datetime) -> bool:
    return _aware(left) == _aware(right)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _provided(patch: LimitFieldPatch | None) -> dict[str, int | float]:
    if patch is None:
        return {}
    values: dict[str, int | float] = {}
    for name in patch.model_fields_set:
        if name not in ALLOWLISTED_LIMITS:
            raise BudgetUpdateError("invalid", f"Unknown limit field: {name}", 422)
        value = getattr(patch, name)
        if value is None:
            raise BudgetUpdateError("invalid", f"{name} cannot be null", 422)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BudgetUpdateError("invalid", f"{name} must be a number", 422)
        if isinstance(value, float) and not math.isfinite(value):
            raise BudgetUpdateError("invalid", f"{name} must be finite", 422)
        values[name] = value
    return values


def limit_patch_values(patch: MissionBudgetPatch) -> tuple[dict[str, int | float], dict[str, int | float]]:
    set_values = _provided(patch.set)
    delta_values = _provided(patch.delta)
    overlap = sorted(set(set_values) & set(delta_values))
    if overlap:
        raise BudgetUpdateError(
            "invalid",
            f"{overlap[0]} cannot be both set and delta",
            422,
        )
    if not set_values and not delta_values:
        raise BudgetUpdateError("empty", "Budget patch is empty", 409)
    return set_values, delta_values


def apply_limit_patch(
    limits: MissionLimits,
    set_values: dict[str, int | float],
    delta_values: dict[str, int | float],
    *,
    token_hard_cap: float,
    effective_token_budget: float,
) -> tuple[MissionLimits, dict[str, dict]]:
    """Return updated limits and a JSON-safe change map. Does not read token counts as USD."""
    data = limits.model_dump()
    changes: dict[str, dict] = {}
    for name, value in set_values.items():
        coerced = _coerce(name, value, token_hard_cap)
        changes[name] = {"from": data.get(name), "to": coerced, "mode": "set"}
        data[name] = coerced
    for name, delta in delta_values.items():
        current = data.get(name)
        used_effective = False
        base = current
        if name == TOKEN_LIMIT and current is None:
            base = effective_token_budget
            used_effective = True
        if isinstance(base, bool) or not isinstance(base, (int, float)):
            raise BudgetUpdateError("invalid", f"{name} has no numeric baseline to adjust", 422)
        coerced = _coerce(name, base + delta, token_hard_cap)
        change = {"from": current, "to": coerced, "mode": "delta"}
        if used_effective:
            change["from_effective"] = effective_token_budget
        changes[name] = change
        data[name] = coerced
    try:
        updated = MissionLimits.model_validate(data)
    except ValidationError as exc:
        raise BudgetUpdateError("invalid", "Limit patch is not a valid MissionLimits value", 422) from exc
    return updated, changes


def _coerce(name: str, value: int | float, token_hard_cap: float) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BudgetUpdateError("invalid", f"{name} must be a number", 422)
    if isinstance(value, float) and not math.isfinite(value):
        raise BudgetUpdateError("invalid", f"{name} must be finite", 422)
    if name in INT_LIMITS:
        if isinstance(value, float):
            if not value.is_integer():
                raise BudgetUpdateError("invalid", f"{name} must stay an integer", 422)
            value = int(value)
        if not isinstance(value, int):
            raise BudgetUpdateError("invalid", f"{name} must stay an integer", 422)
        floor, cap = INT_LIMITS[name]
        if value < floor:
            raise BudgetUpdateError("under_floor", f"{name} {value} is below the floor {floor}", 409)
        if value > cap:
            raise BudgetUpdateError("over_cap", f"{name} {value} exceeds the hard cap {cap}", 409)
        return value
    if name == "max_payment_amount":
        amount = float(value)
        floor, cap = FLOAT_LIMITS[name]
        if amount < floor:
            raise BudgetUpdateError("under_floor", f"{name} {amount} is below the floor {floor}", 409)
        if cap is not None and amount > cap:
            raise BudgetUpdateError("over_cap", f"{name} {amount} exceeds the hard cap {cap}", 409)
        return round_cost(amount)
    if name == TOKEN_LIMIT:
        amount = float(value)
        if amount < 0:
            raise BudgetUpdateError("under_floor", f"{name} {amount} is below the floor 0", 409)
        if amount > float(token_hard_cap):
            raise BudgetUpdateError(
                "over_cap",
                f"{name} {amount} exceeds the hard cap {token_hard_cap}",
                409,
            )
        return round_cost(amount)
    raise BudgetUpdateError("invalid", f"Unknown limit field: {name}", 422)
