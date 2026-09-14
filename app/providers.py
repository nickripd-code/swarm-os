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
