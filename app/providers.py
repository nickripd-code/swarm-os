from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import FailureClass


class ProviderError(RuntimeError):
    """Safe provider failure. Messages must never contain response bodies or credentials."""

    def __init__(self, message: str, failure_class: FailureClass = FailureClass.UNKNOWN_FAILURE):
        super().__init__(message)
        self.failure_class = failure_class


class ModelCapabilities(BaseModel):
    reasoning: Literal["none", "low", "medium", "high", "unknown"] = "unknown"
    coding: Literal["none", "low", "medium", "high", "unknown"] = "unknown"
    vision: bool | None = None
    tool_use: bool | None = None
    structured_outputs: bool | None = None
    streaming: bool | None = None


class ContextLimits(BaseModel):
    context_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelDescriptor(BaseModel):
    provider: str
    model: str
    local: bool = False
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    context_limits: ContextLimits = Field(default_factory=ContextLimits)
    price_input_per_million: float | None = Field(default=None, ge=0)
    price_output_per_million: float | None = Field(default=None, ge=0)


class ModelRequest(BaseModel):
    model: str
    instructions: str
    input: dict[str, Any] | list[Any] | str
    response_format: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)

    def plus(self, other: "ModelUsage") -> "ModelUsage":
        return ModelUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


class ModelResponse(BaseModel):
    provider: str
    model: str
    output: dict[str, Any] | str
    response_id: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    failover_from: str | None = None
    failover_reason: str | None = None


class ProviderHealth(BaseModel):
    provider: str
    status: Literal["healthy", "degraded", "unavailable", "unconfigured", "unknown"]
    detail: str | None = None


class CostEstimate(BaseModel):
    provider: str
    model: str
    estimated_cost: float | None = Field(default=None, ge=0)
    currency: str = "USD"
    known: bool = False
    reason: str | None = None


class ModelProvider(ABC):
    """Provider-neutral low-level model API owned by Swarm OS."""

    provider_id: str

    @abstractmethod
    async def list_models(self) -> list[ModelDescriptor]:
        raise NotImplementedError

    @abstractmethod
    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        del request
        raise ProviderError(
            f"{self.provider_id} streaming is not implemented",
            FailureClass.CAPABILITY_MISMATCH,
        )
        yield ""  # pragma: no cover - keeps this an async generator

    @abstractmethod
    def capabilities(self, model: str) -> ModelCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    def estimate_cost(self, request: ModelRequest) -> CostEstimate:
        raise NotImplementedError

    @abstractmethod
    def usage(self) -> ModelUsage:
        raise NotImplementedError

    @abstractmethod
    def context_limits(self, model: str) -> ContextLimits:
        raise NotImplementedError


# PROVIDER_OUTAGE (and an unconfigured/unavailable primary) may use a configured secondary.
# Auth, policy, invalid output, rate limits, and timeouts stay on the provider that raised them.
FAILOVER_FAILURE_CLASSES = frozenset({FailureClass.PROVIDER_OUTAGE})
FAILOVER_HEALTH_STATUSES = frozenset({"unconfigured", "unavailable"})


def provider_configured(provider: ModelProvider) -> bool:
    configured = getattr(provider, "configured", None)
    return bool(configured()) if callable(configured) else True


class FailoverModelProvider(ModelProvider):
    """Try the primary ModelProvider; on outage/unavailability use a configured secondary."""

    provider_id = "failover"

    def __init__(self, primary: ModelProvider, secondary: ModelProvider):
        self.primary = primary
        self.secondary = secondary

    def configured(self) -> bool:
        return provider_configured(self.primary) or provider_configured(self.secondary)

    def _target_model(self, provider: ModelProvider, request: ModelRequest) -> str:
        configured_model = getattr(provider, "model", None)
        return configured_model or request.model

    def _request_for(self, provider: ModelProvider, request: ModelRequest) -> ModelRequest:
        model = self._target_model(provider, request)
        return request if model == request.model else request.model_copy(update={"model": model})

    async def _primary_skip_reason(self) -> str | None:
        if not provider_configured(self.primary):
            return "unconfigured"
        health = await self.primary.health()
        if health.status in FAILOVER_HEALTH_STATUSES:
            return health.status
        return None

    async def complete(self, request: ModelRequest) -> ModelResponse:
        primary_error: ProviderError | None = None
        skip_reason = await self._primary_skip_reason()
        if skip_reason is None:
            try:
                return await self.primary.complete(self._request_for(self.primary, request))
            except ProviderError as exc:
                if exc.failure_class not in FAILOVER_FAILURE_CLASSES or not provider_configured(self.secondary):
                    raise
                primary_error = exc
        elif not provider_configured(self.secondary):
            raise ProviderError("No model provider is configured", FailureClass.AUTHORIZATION_REQUIRED)

        reason = str(primary_error.failure_class) if primary_error else skip_reason
        response = await self.secondary.complete(self._request_for(self.secondary, request))
        return response.model_copy(update={
            "failover_from": self.primary.provider_id,
            "failover_reason": reason,
        })

    async def list_models(self) -> list[ModelDescriptor]:
        models: list[ModelDescriptor] = []
        if provider_configured(self.primary):
            models.extend(await self.primary.list_models())
        if provider_configured(self.secondary):
            models.extend(await self.secondary.list_models())
        return models

    def _delegate(self) -> ModelProvider:
        return self.primary if provider_configured(self.primary) else self.secondary

    def capabilities(self, model: str) -> ModelCapabilities:
        return self._delegate().capabilities(model)

    def context_limits(self, model: str) -> ContextLimits:
        return self._delegate().context_limits(model)

    def estimate_cost(self, request: ModelRequest) -> CostEstimate:
        return self._delegate().estimate_cost(request)

    def usage(self) -> ModelUsage:
        primary_usage = self.primary.usage() if hasattr(self.primary, "usage") else ModelUsage()
        secondary_usage = self.secondary.usage() if hasattr(self.secondary, "usage") else ModelUsage()
        return primary_usage.plus(secondary_usage)

    async def health(self) -> ProviderHealth:
        primary = await self.primary.health()
        secondary = await self.secondary.health()
        statuses = {primary.status, secondary.status}
        status: Literal["healthy", "degraded", "unavailable", "unconfigured", "unknown"]
        if statuses == {"healthy"}:
            status = "healthy"
        elif "healthy" in statuses:
            status = "degraded"
        elif statuses <= {"unconfigured"}:
            status = "unconfigured"
        elif statuses <= {"unavailable", "unconfigured"}:
            status = "unavailable"
        else:
            status = "unknown"
        return ProviderHealth(
            provider=self.provider_id,
            status=status,
            detail=f"primary={primary.status}; secondary={secondary.status}",
        )
