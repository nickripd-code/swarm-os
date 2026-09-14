from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .models import FailureClass
from .providers import (
    CostEstimate,
    ModelDescriptor,
    ModelProvider,
    ModelRequest,
    ProviderError,
    ProviderHealth,
)


CapabilityLevel = Literal["none", "low", "medium", "high"]
PrivacyRequirement = Literal["cloud_allowed", "local_only"]

_LEVEL_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


class ModelRequirements(BaseModel):
    """Hard constraints requested by an agent or organization designer."""

    reasoning: CapabilityLevel = "none"
    coding: CapabilityLevel = "none"
    vision: bool = False
    tool_use: bool = False
    structured_outputs: bool = False
    min_context_tokens: int | None = Field(default=None, ge=1)
    max_latency_ms: float | None = Field(default=None, gt=0)
    max_cost: float | None = Field(default=None, ge=0)
    privacy: PrivacyRequirement = "cloud_allowed"
    allowed_providers: set[str] | None = None
    preferred_providers: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RouteCandidate:
    provider: ModelProvider
    descriptor: ModelDescriptor
    health: ProviderHealth
    cost: CostEstimate
    score: float
    reasons: tuple[str, ...]

    def record(self) -> dict:
        """Serializable trace data; deliberately excludes the provider object and credentials."""
        return {
            "provider": self.descriptor.provider,
            "model": self.descriptor.model,
            "score": self.score,
            "health": self.health.status,
            "estimated_cost": self.cost.estimated_cost,
            "cost_currency": self.cost.currency,
            "cost_known": self.cost.known,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RejectedCandidate:
    provider: str
    model: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RoutingPlan:
    primary: RouteCandidate
    fallbacks: tuple[RouteCandidate, ...]
    rejected: tuple[RejectedCandidate, ...]

    @property
    def candidates(self) -> tuple[RouteCandidate, ...]:
        return (self.primary, *self.fallbacks)

    def trace(self) -> dict:
        return {
            "primary": self.primary.record(),
            "fallbacks": [candidate.record() for candidate in self.fallbacks],
            "rejected": [
                {"provider": item.provider, "model": item.model, "reasons": list(item.reasons)}
                for item in self.rejected
            ],
        }


class NoRouteError(ProviderError):
    def __init__(self, message: str, failure_class: FailureClass,
                 rejected: tuple[RejectedCandidate, ...]):
        super().__init__(message, failure_class)
        self.rejected = rejected


class ModelRegistry:
    """Replaceable provider inventory. A provider may advertise multiple models."""

    def __init__(self, providers: list[ModelProvider] | None = None):
        self._providers: list[ModelProvider] = []
        for provider in providers or []:
            self.register(provider)

    @property
    def providers(self) -> tuple[ModelProvider, ...]:
        return tuple(self._providers)

    def register(self, provider: ModelProvider) -> None:
        if provider in self._providers:
            return
        self._providers.append(provider)


class ModelRouter:
    """Filter on hard requirements, then rank every valid model deterministically."""

    def __init__(self, registry: ModelRegistry | list[ModelProvider]):
        self.registry = registry if isinstance(registry, ModelRegistry) else ModelRegistry(registry)

    async def route(self, requirements: ModelRequirements,
                    request: ModelRequest) -> RoutingPlan:
        accepted: list[RouteCandidate] = []
        rejected: list[RejectedCandidate] = []

        for provider in self.registry.providers:
            provider_id = getattr(provider, "provider_id", provider.__class__.__name__)
            try:
                health = await provider.health()
            except ProviderError as exc:
                rejected.append(RejectedCandidate(
                    provider_id, None,
                    (f"health check failed: {exc.failure_class}",),
                ))
                continue

            provider_reasons = self._provider_rejections(health)
            if provider_reasons:
                rejected.append(RejectedCandidate(provider_id, None, tuple(provider_reasons)))
                continue

            try:
                descriptors = await provider.list_models()
            except ProviderError as exc:
                rejected.append(RejectedCandidate(
                    provider_id, None,
                    (f"model discovery failed: {exc.failure_class}",),
                ))
                continue

            if not descriptors:
                rejected.append(RejectedCandidate(provider_id, None, ("provider advertised no models",)))
                continue

            for descriptor in descriptors:
                reasons = self._model_rejections(descriptor, requirements)
                if reasons:
                    rejected.append(RejectedCandidate(
                        descriptor.provider, descriptor.model, tuple(reasons),
                    ))
                    continue
                candidate_request = request.model_copy(update={"model": descriptor.model})
                try:
                    cost = provider.estimate_cost(candidate_request)
                except ProviderError as exc:
                    rejected.append(RejectedCandidate(
                        descriptor.provider, descriptor.model,
                        tuple([*reasons, f"cost estimation failed: {exc.failure_class}"]),
                    ))
                    continue
                if requirements.max_cost is not None:
                    if not cost.known or cost.estimated_cost is None:
                        reasons.append("cost is unknown under a hard max_cost")
                    elif cost.estimated_cost > requirements.max_cost:
                        reasons.append(
                            f"estimated cost {cost.estimated_cost:.6f} exceeds {requirements.max_cost:.6f}"
                        )
                if reasons:
                    rejected.append(RejectedCandidate(
                        descriptor.provider, descriptor.model, tuple(reasons),
                    ))
                    continue
                score, ranking_reasons = self._score(descriptor, health, cost, requirements)
                accepted.append(RouteCandidate(
                    provider, descriptor, health, cost, score, tuple(ranking_reasons),
                ))

        accepted.sort(key=lambda item: (
            -item.score,
            self._preference_rank(item.descriptor.provider, requirements),
            item.descriptor.provider,
            item.descriptor.model,
        ))
        if not accepted:
            rejected_tuple = tuple(rejected)
            failure_class = self._failure_class(rejected_tuple)
            raise NoRouteError("No model satisfies the requested capabilities and constraints",
                               failure_class, rejected_tuple)
        return RoutingPlan(accepted[0], tuple(accepted[1:]), tuple(rejected))

    @staticmethod
    def _provider_rejections(health: ProviderHealth) -> list[str]:
        reasons: list[str] = []
        if health.status in {"unconfigured", "unavailable"}:
            reasons.append(f"provider health is {health.status}")
        return reasons

    @staticmethod
    def _model_rejections(descriptor: ModelDescriptor,
                          requirements: ModelRequirements) -> list[str]:
        reasons: list[str] = []
        caps = descriptor.capabilities
        if (requirements.allowed_providers is not None and
                descriptor.provider not in requirements.allowed_providers):
            reasons.append("provider is outside allowed_providers")
        for name, required in (("reasoning", requirements.reasoning), ("coding", requirements.coding)):
            actual = getattr(caps, name)
            if required != "none" and (actual == "unknown" or _LEVEL_RANK.get(actual, -1) < _LEVEL_RANK[required]):
                reasons.append(f"{name}={actual} does not satisfy {required}")
        if requirements.vision and caps.vision is not True:
            reasons.append("vision capability is not confirmed")
        if requirements.tool_use and caps.tool_use is not True:
            reasons.append("tool use capability is not confirmed")
        if requirements.structured_outputs and caps.structured_outputs is not True:
            reasons.append("structured outputs capability is not confirmed")
        context = descriptor.context_limits.context_tokens
        if requirements.min_context_tokens is not None:
            if context is None or context < requirements.min_context_tokens:
                reasons.append(f"context={context or 'unknown'} is below {requirements.min_context_tokens}")
        if requirements.max_latency_ms is not None:
            if descriptor.latency_ms is None:
                reasons.append("latency is unknown under a hard max_latency_ms")
            elif descriptor.latency_ms > requirements.max_latency_ms:
                reasons.append(
                    f"latency {descriptor.latency_ms:.0f}ms exceeds {requirements.max_latency_ms:.0f}ms"
                )
        is_local = descriptor.local or descriptor.privacy == "local"
        if requirements.privacy == "local_only" and not is_local:
            reasons.append("model is not local")
        if descriptor.available is False:
            reasons.append("model is marked unavailable")
        return reasons

    def _score(self, descriptor: ModelDescriptor, health: ProviderHealth,
               cost: CostEstimate, requirements: ModelRequirements) -> tuple[float, list[str]]:
        score = 100.0
        reasons = ["meets every hard requirement"]
        if health.status == "healthy":
            score += 10
            reasons.append("provider health is healthy")
        elif health.status == "degraded":
            reasons.append("provider health is degraded")
        else:
            score -= 5
            reasons.append(f"provider health is {health.status}")
        preference = self._preference_rank(descriptor.provider, requirements)
        if preference < len(requirements.preferred_providers):
            bonus = 20 - min(preference, 19)
            score += bonus
            reasons.append(f"preferred provider rank {preference + 1}")
        if descriptor.reliability is not None:
            score += descriptor.reliability * 15
            reasons.append(f"reliability {descriptor.reliability:.2f}")
        if descriptor.latency_ms is not None:
            score += max(0.0, 10.0 - descriptor.latency_ms / 1000.0)
            reasons.append(f"latency {descriptor.latency_ms:.0f}ms")
        if cost.known and cost.estimated_cost is not None:
            score += max(0.0, 10.0 - cost.estimated_cost * 10.0)
            reasons.append(f"estimated cost {cost.estimated_cost:.6f} {cost.currency}")
        if descriptor.local or descriptor.privacy == "local":
            score += 2
            reasons.append("local execution")
        return score, reasons

    @staticmethod
    def _preference_rank(provider: str, requirements: ModelRequirements) -> int:
        try:
            return requirements.preferred_providers.index(provider)
        except ValueError:
            return len(requirements.preferred_providers)

    @staticmethod
    def _failure_class(rejected: tuple[RejectedCandidate, ...]) -> FailureClass:
        reasons = " ".join(reason for candidate in rejected for reason in candidate.reasons)
        if rejected and all("unconfigured" in " ".join(candidate.reasons) for candidate in rejected):
            return FailureClass.AUTHORIZATION_REQUIRED
        if "max_cost" in reasons or "estimated cost" in reasons:
            return FailureClass.RESOURCE_EXHAUSTED
        if rejected and all("unavailable" in " ".join(candidate.reasons) or
                            "health check failed" in " ".join(candidate.reasons)
                            for candidate in rejected):
            return FailureClass.PROVIDER_OUTAGE
        return FailureClass.CAPABILITY_MISMATCH
