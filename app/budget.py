"""Observe-only per-mission token/cost accounting.

This is not ResourceScheduler. It does not approve, deny, or reallocate work.
It records estimated token usage per provider call and surfaces totals.
Missing meters fail closed only when require_meters is configured.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .models import FailureClass
from .policy import PolicyError
from .providers import ModelUsage

LOCAL_PROVIDERS = frozenset({"ollama", "vllm", "llamacpp"})
TOKEN_KEYS = ("input_tokens", "output_tokens", "reasoning_tokens")
REQUIRE_METERS_ENV = "SWARM_REQUIRE_TOKEN_METERS"
TOKEN_PRICES_ENV = "SWARM_TOKEN_PRICES"


class TokenPrices(BaseModel):
    input_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)


class BudgetCall(BaseModel):
    kind: str
    provider: str
    model: str
    metered: bool
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    cost_known: bool = False
    reason: str | None = None
    observe_only: bool = True

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens


def require_token_meters_from_env(raw: str | None = None) -> bool:
    value = raw if raw is not None else os.getenv(REQUIRE_METERS_ENV)
    if value is None or not str(value).strip():
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_non_negative_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"Token price '{field}' must be a non-negative number",
                          FailureClass.INVALID_OUTPUT)
    if value < 0:
        raise PolicyError(f"Token price '{field}' must be a non-negative number",
                          FailureClass.INVALID_OUTPUT)
    return float(value)


def parse_token_prices(raw: str | None) -> dict[str, TokenPrices]:
    if raw is None or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolicyError("SWARM_TOKEN_PRICES is not valid JSON",
                          FailureClass.INVALID_OUTPUT) from exc
    if not isinstance(data, dict):
        raise PolicyError("SWARM_TOKEN_PRICES must be a JSON object",
                          FailureClass.INVALID_OUTPUT)
    prices: dict[str, TokenPrices] = {}
    for key, value in data.items():
        name = str(key).strip()
        if not name:
            raise PolicyError("SWARM_TOKEN_PRICES keys must be non-empty",
                              FailureClass.INVALID_OUTPUT)
        if not isinstance(value, dict):
            raise PolicyError("SWARM_TOKEN_PRICES entries must be objects",
                              FailureClass.INVALID_OUTPUT)
        prices[name] = TokenPrices(
            input_per_million=_as_non_negative_number(
                value.get("input", value.get("input_per_million")), "input"),
            output_per_million=_as_non_negative_number(
                value.get("output", value.get("output_per_million")), "output"),
        )
    return prices


def token_prices_from_env() -> dict[str, TokenPrices]:
    return parse_token_prices(os.getenv(TOKEN_PRICES_ENV))


def budget_status(*, require_meters: bool | None = None) -> dict[str, Any]:
    """Health block. Never includes prices or credentials."""
    required = require_token_meters_from_env() if require_meters is None else require_meters
    return {
        "observe_only": True,
        "require_token_meters": required,
        "resource_scheduler": False,
    }


def _as_token_count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"Token meter '{field}' is not a non-negative integer",
                          FailureClass.INVALID_OUTPUT)
    if value < 0 or int(value) != value:
        raise PolicyError(f"Token meter '{field}' is not a non-negative integer",
                          FailureClass.INVALID_OUTPUT)
    return int(value)


def usage_from_meta(metadata: dict[str, Any] | None) -> tuple[ModelUsage | None, bool]:
    """Return (usage, metered). Metered means at least one token key was present."""
    if not isinstance(metadata, dict):
        return None, False
    present = [key for key in TOKEN_KEYS if key in metadata]
    if not present:
        return None, False
    return ModelUsage(
        input_tokens=_as_token_count(metadata.get("input_tokens", 0), "input_tokens"),
        output_tokens=_as_token_count(metadata.get("output_tokens", 0), "output_tokens"),
        reasoning_tokens=_as_token_count(metadata.get("reasoning_tokens", 0), "reasoning_tokens"),
    ), True


def lookup_prices(prices: dict[str, TokenPrices], provider: str, model: str) -> TokenPrices | None:
    for key in (f"{provider}:{model}", provider, model):
        if key in prices:
            return prices[key]
    return None


def estimate_call_cost(provider: str, usage: ModelUsage,
                       prices: TokenPrices | None) -> tuple[float | None, bool, str]:
    if provider in LOCAL_PROVIDERS:
        return 0.0, True, "Local inference is treated as zero billed cost"
    if prices is None:
        return None, False, "Pricing metadata is not configured for this model"
    billed_output = usage.output_tokens + usage.reasoning_tokens
    cost = (usage.input_tokens / 1_000_000) * prices.input_per_million
    cost += (billed_output / 1_000_000) * prices.output_per_million
    return round(cost, 10), True, "Estimated from configured per-million token prices"


def _usage_fields(usage: ModelUsage | None) -> dict[str, int]:
    usage = usage or ModelUsage()
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens + usage.reasoning_tokens,
    }


def _sum_calls(calls: list[BudgetCall], *, nest_providers: bool = True) -> dict[str, Any]:
    usage = ModelUsage()
    estimated = 0.0
    known_any = False
    complete = True
    unmetered = 0
    by_provider: dict[str, list[BudgetCall]] = defaultdict(list)
    for call in calls:
        by_provider[call.provider].append(call)
        if not call.metered:
            unmetered += 1
            complete = False
            continue
        usage = usage.plus(ModelUsage(
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            reasoning_tokens=call.reasoning_tokens,
        ))
        if call.cost_known and call.estimated_cost_usd is not None:
            estimated += call.estimated_cost_usd
            known_any = True
        else:
            complete = False
    snapshot = {
        "observe_only": True,
        "calls": len(calls),
        "unmetered_calls": unmetered,
        **_usage_fields(usage),
        "estimated_cost_usd": round(estimated, 10) if known_any else None,
        "cost_known": known_any,
        "cost_complete": complete and bool(calls) and unmetered == 0,
        "currency": "USD",
        "by_provider": {},
    }
    if nest_providers:
        providers: dict[str, Any] = {}
        for provider, group in by_provider.items():
            nested = _sum_calls(group, nest_providers=False)
            nested.pop("by_provider", None)
            nested.pop("observe_only", None)
            providers[provider] = nested
        snapshot["by_provider"] = providers
    return snapshot


class MissionBudget:
    """In-process per-mission token ledger. Observe-only; not a scheduler."""

    def __init__(self, *, require_meters: bool = False,
                 prices: dict[str, TokenPrices] | None = None):
        self.require_meters = require_meters
        self.prices = prices or {}
        self._calls: dict[UUID, list[BudgetCall]] = defaultdict(list)

    @classmethod
    def from_env(cls) -> "MissionBudget":
        return cls(
            require_meters=require_token_meters_from_env(),
            prices=token_prices_from_env(),
        )

    def calls(self, mission_id: UUID) -> list[BudgetCall]:
        return list(self._calls.get(mission_id, []))

    def snapshot(self, mission_id: UUID) -> dict[str, Any] | None:
        recorded = self._calls.get(mission_id)
        if not recorded:
            return None
        data = _sum_calls(recorded)
        data["require_meters"] = self.require_meters
        return data

    def record(self, mission_id: UUID, kind: str,
               metadata: dict[str, Any] | None) -> BudgetCall | None:
        usage, metered = usage_from_meta(metadata)
        if not metered:
            if self.require_meters:
                raise PolicyError(
                    "Token usage meters were missing for this model call",
                    FailureClass.RESOURCE_EXHAUSTED,
                )
            if not isinstance(metadata, dict):
                return None
        provider = "unknown"
        model = "unknown"
        if isinstance(metadata, dict):
            provider = str(metadata.get("provider") or "unknown")
            model = str(metadata.get("model") or "unknown")
        cost, cost_known, reason = (None, False, "Call was not metered")
        tokens = ModelUsage()
        if metered and usage is not None:
            tokens = usage
            cost, cost_known, reason = estimate_call_cost(
                provider, usage, lookup_prices(self.prices, provider, model),
            )
        call = BudgetCall(
            kind=kind,
            provider=provider,
            model=model,
            metered=metered,
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            reasoning_tokens=tokens.reasoning_tokens,
            estimated_cost_usd=cost,
            cost_known=cost_known,
            reason=reason,
            observe_only=True,
        )
        self._calls[mission_id].append(call)
        return call

    def event_payload(self, mission_id: UUID, call: BudgetCall) -> dict[str, Any]:
        payload = call.model_dump(mode="json")
        payload["totals"] = self.snapshot(mission_id)
        return payload

    def attach_to_result(self, mission) -> None:
        snapshot = self.snapshot(mission.id)
        if snapshot is None or mission.result is None:
            return
        result = dict(mission.result)
        result["token_budget"] = snapshot
        mission.result = result
