from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import FailureClass
from .providers import (
    FAILOVER_FAILURE_CLASSES,
    FAILOVER_HEALTH_STATUSES,
    CostEstimate,
    FailoverModelProvider,
    ModelDescriptor,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderHealth,
    provider_configured,
)

LEVEL_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}

SCORE_REASONING_MATCH = 20.0
SCORE_REASONING_UNKNOWN = 8.0
SCORE_CODING_MATCH = 15.0
SCORE_CODING_UNKNOWN = 6.0
SCORE_TOOL_REQUIRED = 10.0
SCORE_STRUCTURED = 5.0
SCORE_HEALTHY = 5.0
SCORE_DEGRADED = 1.0
TIEBREAK_INDEX = 0.01


class CapabilityRequest(BaseModel):
    """What an agent/controller needs. Callers request this instead of a model id."""

    reasoning: Literal["none", "low", "medium", "high"] = "medium"
    coding: Literal["none", "low", "medium", "high"] = "none"
    vision: bool = False
    tool_use: Literal["none", "optional", "required"] = "none"
    min_context_tokens: int | None = Field(default=None, ge=1)
    max_cost: float | None = Field(default=None, ge=0)
    privacy: Literal["cloud_allowed", "local_only"] = "cloud_allowed"


class RouteCandidate(BaseModel):
    provider_id: str
    model: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    selected: RouteCandidate
    fallbacks: list[RouteCandidate] = Field(default_factory=list)
    request: CapabilityRequest

    @property
    def chain(self) -> list[RouteCandidate]:
        return [self.selected, *self.fallbacks]


def capability_request_for(*, kind: str, agent: dict[str, Any] | None = None) -> CapabilityRequest:
    """Map controller/worker work to a capability request. No model names."""
    if kind == "decision":
        return CapabilityRequest(reasoning="high", coding="low", tool_use="none")
    caps = set((agent or {}).get("capabilities") or [])
    reasoning: Literal["none", "low", "medium", "high"]
    coding: Literal["none", "low", "medium", "high"]
    if "review" in caps:
        reasoning, coding = "high", "medium"
    elif "write" in caps:
        reasoning = "high" if "reason" in caps else "medium"
        coding = "high"
    elif "reason" in caps:
        reasoning, coding = "high", "none"
    else:
        reasoning, coding = "medium", "none"
    return CapabilityRequest(reasoning=reasoning, coding=coding, tool_use="none")


def _level_ok(have: str, want: str) -> bool:
    if have == "unknown":
        return True
    return LEVEL_RANK.get(have, 0) >= LEVEL_RANK.get(want, 0)


def _hard_reject(descriptor: ModelDescriptor, request: CapabilityRequest,
                 estimate: CostEstimate, health: str) -> str | None:
    if request.privacy == "local_only" and not descriptor.local:
        return "privacy requires a local model"
    caps = descriptor.capabilities
    if request.vision and caps.vision is False:
        return "vision is not available"
    if request.tool_use == "required" and caps.tool_use is False:
        return "tool use is not available"
    if caps.structured_outputs is False:
        return "structured outputs are not available"
    if not _level_ok(caps.reasoning, request.reasoning):
        return "reasoning capability is below the request"
    if not _level_ok(caps.coding, request.coding):
        return "coding capability is below the request"
    context_tokens = descriptor.context_limits.context_tokens
    if request.min_context_tokens is not None:
        if context_tokens is None or context_tokens < request.min_context_tokens:
            return "context window is unknown or below the request"
    if request.max_cost is not None:
        if not estimate.known or estimate.estimated_cost is None or estimate.estimated_cost > request.max_cost:
            return "cost is unknown or above the request"
    if health == "unconfigured":
        return "provider is not configured"
    return None


def score_model(descriptor: ModelDescriptor, request: CapabilityRequest, *,
                health: str = "healthy", index: int = 0,
                estimate: CostEstimate | None = None) -> tuple[float, list[str]] | None:
    """Return (score, reasons) or None when the model is ineligible."""
    estimate = estimate or CostEstimate(
        provider=descriptor.provider, model=descriptor.model, known=False,
    )
    rejected = _hard_reject(descriptor, request, estimate, health)
    if rejected:
        return None
    caps = descriptor.capabilities
    score = 0.0
    reasons: list[str] = []

    if caps.reasoning == "unknown":
        score += SCORE_REASONING_UNKNOWN
        reasons.append("reasoning unknown")
    else:
        score += SCORE_REASONING_MATCH + LEVEL_RANK.get(caps.reasoning, 0)
        reasons.append(f"reasoning {caps.reasoning}")

    if request.coding != "none":
        if caps.coding == "unknown":
            score += SCORE_CODING_UNKNOWN
            reasons.append("coding unknown")
        else:
            score += SCORE_CODING_MATCH + LEVEL_RANK.get(caps.coding, 0)
            reasons.append(f"coding {caps.coding}")

    if request.tool_use == "required" and caps.tool_use:
        score += SCORE_TOOL_REQUIRED
        reasons.append("tools available")
    if caps.structured_outputs:
        score += SCORE_STRUCTURED
        reasons.append("structured outputs")
    if health == "healthy":
        score += SCORE_HEALTHY
        reasons.append("healthy")
    elif health == "degraded":
        score += SCORE_DEGRADED
        reasons.append("degraded")

    if descriptor.price_output_per_million is not None:
        score -= descriptor.price_output_per_million * 0.001
        reasons.append("listed output price")
    elif estimate.known and estimate.estimated_cost is not None:
        score -= estimate.estimated_cost
        reasons.append("estimated cost")

    score -= index * TIEBREAK_INDEX
    return score, reasons


def registered_providers(provider: ModelProvider) -> list[ModelProvider]:
    """Flatten FailoverModelProvider so the router can score each adapter."""
    if isinstance(provider, FailoverModelProvider):
        return [provider.primary, provider.secondary]
    return [provider]


class ModelRouter:
    """Select a model from registered ModelProviders by capability, then fall back on outage."""

    def __init__(self, providers: list[ModelProvider]):
        if not providers:
            raise ValueError("ModelRouter requires at least one ModelProvider")
        self.providers = list(providers)
        self.last_decision: RouteDecision | None = None

    @classmethod
    def wrap(cls, provider: ModelProvider) -> "ModelRouter":
        return cls(registered_providers(provider))

    def configured(self) -> bool:
        return any(provider_configured(provider) for provider in self.providers)

    def _provider(self, provider_id: str) -> ModelProvider | None:
        for provider in self.providers:
            if provider.provider_id == provider_id:
                return provider
        return None

    async def _health(self, provider: ModelProvider) -> ProviderHealth:
        try:
            return await provider.health()
        except ProviderError:
            return ProviderHealth(provider=provider.provider_id, status="unknown",
                                  detail="health check failed")

    def _synthetic_descriptor(self, provider: ModelProvider) -> ModelDescriptor | None:
        model = getattr(provider, "model", None)
        if not model:
            return None
        return ModelDescriptor(
            provider=provider.provider_id,
            model=model,
            capabilities=provider.capabilities(model),
            context_limits=provider.context_limits(model),
        )

    async def catalog(self) -> list[tuple[ModelProvider, ModelDescriptor, str]]:
        catalog: list[tuple[ModelProvider, ModelDescriptor, str]] = []
        for provider in self.providers:
            if not provider_configured(provider):
                continue
            health = await self._health(provider)
            models = await provider.list_models()
            if not models:
                synthetic = self._synthetic_descriptor(provider)
                models = [synthetic] if synthetic else []
            for descriptor in models:
                catalog.append((provider, descriptor, health.status))
        return catalog

    async def select(self, request: CapabilityRequest) -> RouteDecision:
        if not self.configured():
            raise ProviderError("No model provider is configured", FailureClass.AUTHORIZATION_REQUIRED)
        ranked: list[RouteCandidate] = []
        for index, (provider, descriptor, health) in enumerate(await self.catalog()):
            probe = ModelRequest(model=descriptor.model, instructions="route", input="")
            estimate = provider.estimate_cost(probe)
            scored = score_model(descriptor, request, health=health, index=index, estimate=estimate)
            if scored is None:
                continue
            score, reasons = scored
            ranked.append(RouteCandidate(
                provider_id=provider.provider_id, model=descriptor.model,
                score=score, reasons=reasons,
            ))
        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        if not ranked:
            raise ProviderError(
                "No registered model satisfies the requested capabilities",
                FailureClass.CAPABILITY_MISMATCH,
            )
        decision = RouteDecision(selected=ranked[0], fallbacks=ranked[1:], request=request)
        self.last_decision = decision
        return decision

    async def _skip_reason(self, provider: ModelProvider) -> str | None:
        if not provider_configured(provider):
            return "unconfigured"
        health = await self._health(provider)
        if health.status in FAILOVER_HEALTH_STATUSES:
            return health.status
        return None

    async def complete(self, capability: CapabilityRequest, request: ModelRequest) -> ModelResponse:
        """Pick by capability, then walk the fallback chain on PROVIDER_OUTAGE only."""
        decision = await self.select(capability)
        primary = decision.selected
        last_error: ProviderError | None = None
        failover_reason: str | None = None
        for candidate in decision.chain:
            provider = self._provider(candidate.provider_id)
            if provider is None:
                continue
            skip_reason = await self._skip_reason(provider)
            if skip_reason is not None:
                failover_reason = skip_reason
                continue
            try:
                targeted = request if request.model == candidate.model else request.model_copy(
                    update={"model": candidate.model},
                )
                response = await provider.complete(targeted)
            except ProviderError as exc:
                if exc.failure_class not in FAILOVER_FAILURE_CLASSES:
                    raise
                last_error = exc
                failover_reason = str(exc.failure_class)
                continue
            if candidate.provider_id != primary.provider_id or candidate.model != primary.model:
                return response.model_copy(update={
                    "failover_from": primary.provider_id,
                    "failover_reason": failover_reason,
                })
            return response
        if last_error is not None:
            raise last_error
        if not self.configured():
            raise ProviderError("No model provider is configured", FailureClass.AUTHORIZATION_REQUIRED)
        raise ProviderError(
            "No registered model provider was available",
            FailureClass.PROVIDER_OUTAGE,
        )
