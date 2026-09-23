"""Token-cost accounting seed. Separate from payment WalletAdapter.

Estimates USD cost from usage already emitted on provider responses / llm.completed.
Unknown listed prices fall back to conservative env defaults; if those are also
absent the estimate is unknown (never invented as $0). Enforcement is fail-closed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from .models import AgentTokenCost, FailureClass, Mission
from .policy import PolicyError, PolicyGate
from .providers import ModelUsage

MILLION = 1_000_000
COST_PLACES = 8

DEFAULT_TOKEN_BUDGET = 3.0
DEFAULT_TOKEN_BUDGET_HARD_CAP = 10.0
DEFAULT_INPUT_PRICE_PER_MILLION = 15.0
DEFAULT_OUTPUT_PRICE_PER_MILLION = 60.0
DEFAULT_COST_MARKUP = 1.25
DEFAULT_WARNING_FRACTION = 0.8

UnknownPricePolicy = Literal["fail", "skip"]


def _env_float(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if stripped == "":
        return None
    try:
        value = float(stripped)
    except ValueError:
        return default
    if value < 0:
        return default
    return value


def _env_unknown_price_policy() -> UnknownPricePolicy:
    raw = (os.getenv("SWARM_TOKEN_UNKNOWN_PRICE") or "fail").strip().lower()
    return "skip" if raw == "skip" else "fail"


def round_cost(value: float) -> float:
    return round(value, COST_PLACES)


@dataclass(frozen=True)
class TokenPrices:
    input_per_million: float
    output_per_million: float
    reasoning_per_million: float | None = None
    source: str = "listed"

    @property
    def reasoning_rate(self) -> float:
        if self.reasoning_per_million is None:
            return self.output_per_million
        return self.reasoning_per_million


@dataclass(frozen=True)
class TokenCostSettings:
    default_budget: float = DEFAULT_TOKEN_BUDGET
    hard_cap: float = DEFAULT_TOKEN_BUDGET_HARD_CAP
    default_input_per_million: float | None = DEFAULT_INPUT_PRICE_PER_MILLION
    default_output_per_million: float | None = DEFAULT_OUTPUT_PRICE_PER_MILLION
    markup: float = DEFAULT_COST_MARKUP
    warning_fraction: float = DEFAULT_WARNING_FRACTION
    unknown_price: UnknownPricePolicy = "fail"

    @classmethod
    def from_env(cls) -> "TokenCostSettings":
        default_budget = _env_float("SWARM_DEFAULT_TOKEN_BUDGET", DEFAULT_TOKEN_BUDGET)
        hard_cap = _env_float("SWARM_TOKEN_BUDGET_HARD_CAP", DEFAULT_TOKEN_BUDGET_HARD_CAP)
        markup = _env_float("SWARM_TOKEN_COST_MARKUP", DEFAULT_COST_MARKUP)
        warning = _env_float("SWARM_TOKEN_BUDGET_WARNING_FRACTION", DEFAULT_WARNING_FRACTION)
        if default_budget is None:
            default_budget = DEFAULT_TOKEN_BUDGET
        if hard_cap is None or hard_cap <= 0:
            hard_cap = DEFAULT_TOKEN_BUDGET_HARD_CAP
        if markup is None or markup <= 0:
            markup = DEFAULT_COST_MARKUP
        if warning is None or warning <= 0 or warning >= 1:
            warning = DEFAULT_WARNING_FRACTION
        return cls(
            default_budget=min(default_budget, hard_cap),
            hard_cap=hard_cap,
            default_input_per_million=_env_float(
                "SWARM_TOKEN_PRICE_INPUT_PER_MILLION", DEFAULT_INPUT_PRICE_PER_MILLION,
            ),
            default_output_per_million=_env_float(
                "SWARM_TOKEN_PRICE_OUTPUT_PER_MILLION", DEFAULT_OUTPUT_PRICE_PER_MILLION,
            ),
            markup=markup,
            warning_fraction=warning,
            unknown_price=_env_unknown_price_policy(),
        )

    def default_prices(self) -> TokenPrices | None:
        if self.default_input_per_million is None or self.default_output_per_million is None:
            return None
        return TokenPrices(
            input_per_million=self.default_input_per_million,
            output_per_million=self.default_output_per_million,
            source="default",
        )


@dataclass(frozen=True)
class SpendOutcome:
    estimate: UsageCostEstimate
    warning_crossed: bool = False
    error: PolicyError | None = None


@dataclass(frozen=True)
class UsageCostEstimate:
    estimated_cost: float | None
    known: bool
    currency: str = "USD"
    reason: str | None = None
    source: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def as_payload(self) -> dict[str, Any]:
        return {
            "estimated_cost": self.estimated_cost,
            "known": self.known,
            "currency": self.currency,
            "reason": self.reason,
            "source": self.source,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


def usage_from_meta(meta: dict[str, Any] | None) -> ModelUsage | None:
    """Return usage when the provider actually reported token fields. Missing is not zero."""
    if not isinstance(meta, dict):
        return None
    if not any(key in meta for key in ("input_tokens", "output_tokens", "reasoning_tokens")):
        return None
    return ModelUsage(
        input_tokens=int(meta.get("input_tokens") or 0),
        output_tokens=int(meta.get("output_tokens") or 0),
        reasoning_tokens=int(meta.get("reasoning_tokens") or 0),
    )


def listed_prices_from_meta(meta: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not isinstance(meta, dict):
        return None, None
    return _optional_price(meta.get("price_input_per_million")), _optional_price(
        meta.get("price_output_per_million"),
    )


def _optional_price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    return price


def estimate_token_cost(
    usage: ModelUsage,
    prices: TokenPrices | None,
    markup: float = DEFAULT_COST_MARKUP,
) -> UsageCostEstimate:
    """Dollar estimate from tokens * listed/default USD per million, times conservative markup.

    Missing prices return known=False with estimated_cost=None. Never invents $0.
    """
    tokens = UsageCostEstimate(
        estimated_cost=None,
        known=False,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
    )
    if prices is None:
        return UsageCostEstimate(
            **{**tokens.__dict__, "reason": "missing price metadata", "source": "unknown"},
        )
    if markup <= 0:
        markup = DEFAULT_COST_MARKUP
    raw = (
        usage.input_tokens * prices.input_per_million
        + usage.output_tokens * prices.output_per_million
        + usage.reasoning_tokens * prices.reasoning_rate
    ) / MILLION
    return UsageCostEstimate(
        estimated_cost=round_cost(raw * markup),
        known=True,
        reason=None,
        source=prices.source,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
    )


class ResourceScheduler:
    """Mission-level token spend budget. Does not touch WalletAdapter payment spend."""

    def __init__(self, settings: TokenCostSettings | None = None, policy: PolicyGate | None = None):
        self.settings = settings or TokenCostSettings.from_env()
        self.policy = policy or PolicyGate()

    def budget_for(self, mission: Mission) -> float:
        listed = mission.limits.max_token_cost
        budget = self.settings.default_budget if listed is None else listed
        return round_cost(min(max(budget, 0.0), self.settings.hard_cap))

    def remaining(self, mission: Mission) -> float:
        return round_cost(self.budget_for(mission) - mission.token_spent)

    def warning_threshold(self, mission: Mission) -> float:
        return round_cost(self.budget_for(mission) * self.settings.warning_fraction)

    def resolve_prices(
        self,
        listed_input: float | None = None,
        listed_output: float | None = None,
    ) -> TokenPrices | None:
        if listed_input is not None and listed_output is not None:
            return TokenPrices(
                input_per_million=listed_input,
                output_per_million=listed_output,
                source="listed",
            )
        defaults = self.settings.default_prices()
        if listed_input is None and listed_output is None:
            return defaults
        if defaults is None:
            return None
        return TokenPrices(
            input_per_million=defaults.input_per_million if listed_input is None else listed_input,
            output_per_million=defaults.output_per_million if listed_output is None else listed_output,
            source="listed+default",
        )

    def estimate(
        self,
        usage: ModelUsage,
        listed_input: float | None = None,
        listed_output: float | None = None,
    ) -> UsageCostEstimate:
        return estimate_token_cost(
            usage, self.resolve_prices(listed_input, listed_output), self.settings.markup,
        )

    def known_agent_usd(self, mission: Mission) -> float:
        """Sum of priced per-agent estimates. None means that agent contributed no dollars."""
        total = 0.0
        for tally in mission.agent_token_costs.values():
            if tally.known_usd is not None:
                total += tally.known_usd
        return round_cost(total)

    def agent_breakdown(self, mission: Mission) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for agent_id, tally in mission.agent_token_costs.items():
            priced = tally.known_usd is not None
            partial = priced and tally.unknown_calls > 0
            rows.append({
                "agent_id": agent_id,
                "input_tokens": tally.input_tokens,
                "output_tokens": tally.output_tokens,
                "reasoning_tokens": tally.reasoning_tokens,
                "tokens": tally.input_tokens + tally.output_tokens + tally.reasoning_tokens,
                "known_usd": tally.known_usd,
                "known": priced and not partial,
                "partial": partial,
                "unknown_calls": tally.unknown_calls,
            })
        return rows

    def _attribute(
        self,
        mission: Mission,
        usage: ModelUsage,
        estimate: UsageCostEstimate,
        agent_id: Any,
    ) -> None:
        """Record tokens and known USD for the agent that spent them. Never stores $0 for an unknown price."""
        if agent_id is None:
            return
        key = str(agent_id).strip()
        if not key:
            return
        tokens = usage.input_tokens + usage.output_tokens + usage.reasoning_tokens
        priced = estimate.known and estimate.estimated_cost is not None
        if tokens <= 0 and not priced:
            return
        tally = mission.agent_token_costs.get(key) or AgentTokenCost()
        tally.input_tokens += max(usage.input_tokens, 0)
        tally.output_tokens += max(usage.output_tokens, 0)
        tally.reasoning_tokens += max(usage.reasoning_tokens, 0)
        if priced:
            assert estimate.estimated_cost is not None
            tally.known_usd = round_cost((tally.known_usd or 0.0) + estimate.estimated_cost)
        elif tokens > 0:
            tally.unknown_calls += 1
        mission.agent_token_costs[key] = tally

    def authorize_start(self, mission: Mission) -> None:
        """Fail closed before another model call when the token budget is already exhausted."""
        if mission.token_spent > 0 and self.remaining(mission) <= 0:
            raise PolicyError(
                "Token cost would exceed mission token budget",
                FailureClass.RESOURCE_EXHAUSTED,
            )

    def consume(
        self,
        mission: Mission,
        usage: ModelUsage,
        listed_input: float | None = None,
        listed_output: float | None = None,
        *,
        agent_id: Any = None,
    ) -> SpendOutcome:
        """Charge estimated USD when known. Over-budget still records spend, then marks exhausted.

        Unknown prices: fail closed (default) or skip-estimate honestly when configured.
        Skip does not invent a dollar amount and does not charge.
        When agent_id is present, tokens and known USD are attributed to that agent.
        """
        estimate = self.estimate(usage, listed_input, listed_output)
        has_tokens = (usage.input_tokens + usage.output_tokens + usage.reasoning_tokens) > 0
        if not estimate.known:
            self._attribute(mission, usage, estimate, agent_id)
            error = None
            if has_tokens and self.settings.unknown_price == "fail":
                error = PolicyError(
                    "Token cost cannot be estimated from available price metadata",
                    FailureClass.RESOURCE_EXHAUSTED,
                )
            return SpendOutcome(estimate=estimate, warning_crossed=False, error=error)
        assert estimate.estimated_cost is not None
        budget = self.budget_for(mission)
        previous = mission.token_spent
        mission.token_spent = round_cost(previous + estimate.estimated_cost)
        self._attribute(mission, usage, estimate, agent_id)
        crossed = previous < self.warning_threshold(mission) <= mission.token_spent
        error = None
        try:
            self.policy.check_token_budget(mission, previous, estimate.estimated_cost, budget)
        except PolicyError as exc:
            error = exc
        return SpendOutcome(estimate=estimate, warning_crossed=crossed, error=error)

    def snapshot(self, mission: Mission, estimate: UsageCostEstimate, **extra: Any) -> dict[str, Any]:
        budget = self.budget_for(mission)
        payload = {
            "token_spent": mission.token_spent,
            "token_budget": budget,
            "remaining": self.remaining(mission),
            "currency": "USD",
            "by_agent": self.agent_breakdown(mission),
            **estimate.as_payload(),
        }
        payload.update(extra)
        return payload
