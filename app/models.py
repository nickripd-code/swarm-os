from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MissionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class FailureClass(StrEnum):
    """Structured failure taxonomy. Do not treat all failures identically."""

    MODEL_FAILURE = "MODEL_FAILURE"
    PROVIDER_OUTAGE = "PROVIDER_OUTAGE"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    CONTEXT_LIMIT = "CONTEXT_LIMIT"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    TOOL_MISSING = "TOOL_MISSING"
    TOOL_FAILURE = "TOOL_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    POLICY_REFUSAL = "POLICY_REFUSAL"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class AgentStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    BLOCKED = "blocked"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    BLOCKED = "blocked"


class MissionLimits(BaseModel):
    max_depth: int = Field(default=4, ge=0, le=20)
    max_agents: int = Field(default=20, ge=1, le=500)
    max_tasks: int = Field(default=100, ge=1, le=1000)
    max_tool_calls: int = Field(default=200, ge=1, le=10000)
    max_runtime_seconds: int = Field(default=300, ge=1, le=86400)
    max_payment_amount: float = Field(default=0, ge=0)
    max_token_cost: float | None = Field(default=None, ge=0)
    require_finish_approval: bool = False


class MissionCreate(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    budget: float = Field(default=0, ge=0)
    live_payments: bool = False
    privacy: Literal["cloud_allowed", "local_only"] = "cloud_allowed"
    limits: MissionLimits = Field(default_factory=MissionLimits)


class PendingQuestion(BaseModel):
    question_id: str
    question: str
    reason: str | None = None
    kind: Literal["question", "approval"] = "question"
    approval_action: str | None = None


class MissionAnswer(BaseModel):
    question_id: str
    question: str
    answer: str
    answered_at: datetime = Field(default_factory=utcnow)
    consumed_at: datetime | None = None
    kind: Literal["question", "approval"] = "question"
    approval_action: str | None = None


class Mission(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    goal: str
    status: MissionStatus = MissionStatus.PENDING
    budget: float = 0
    spent: float = 0
    token_spent: float = Field(default=0, ge=0)
    live_payments: bool = False
    privacy: Literal["cloud_allowed", "local_only"] = "cloud_allowed"
    limits: MissionLimits = Field(default_factory=MissionLimits)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    result: dict[str, Any] | None = None
    pending_question: PendingQuestion | None = None
    answers: list[MissionAnswer] = Field(default_factory=list)
    paused_at: datetime | None = None
    paused_seconds: float = Field(default=0, ge=0)


# Optional AgentSpec hints live in the existing agents.payload JSON column.
# None means unspecified. Do not treat these as routing, tool, or TTL enforcement.
MAX_AGENT_TOKEN_COST = 1_000_000.0
MAX_AGENT_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_AGENT_TOOL_ALLOWLIST = 64
MAX_AGENT_MODEL_ID_LENGTH = 200
MAX_AGENT_TOOL_NAME_LENGTH = 128


class AgentSpec(BaseModel):
    """Durable agent row. Optional north-star hints are stored, not enforced.

    `preferred_model`, `max_token_cost`, `tool_allowlist`, and `ttl_seconds`
    round-trip through `agents.payload` and agent spawn/update event dumps.
    Omitted fields stay None so existing spawn paths keep the same behavior.
    `tool_allowlist` of None or [] means unspecified, not deny-all.
    """

    id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    parent_id: UUID | None = None
    role: str
    purpose: str
    capabilities: list[str] = Field(default_factory=list)
    depth: int = 0
    status: AgentStatus = AgentStatus.CREATED
    output: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    preferred_model: str | None = Field(default=None, min_length=1, max_length=MAX_AGENT_MODEL_ID_LENGTH)
    max_token_cost: float | None = Field(default=None, ge=0, le=MAX_AGENT_TOKEN_COST)
    tool_allowlist: list[str] | None = Field(default=None, max_length=MAX_AGENT_TOOL_ALLOWLIST)
    ttl_seconds: int | None = Field(default=None, gt=0, le=MAX_AGENT_TTL_SECONDS)

    @field_validator("preferred_model", mode="before")
    @classmethod
    def _preferred_model(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("preferred_model must be a string model id when set")
        stripped = value.strip()
        if not stripped:
            raise ValueError("preferred_model must be a non-empty model id when set")
        return stripped

    @field_validator("max_token_cost", mode="before")
    @classmethod
    def _max_token_cost(cls, value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("max_token_cost must be a finite non-negative number")
        return float(value)

    @field_validator("tool_allowlist", mode="before")
    @classmethod
    def _tool_allowlist(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str) or not isinstance(value, list):
            raise ValueError("tool_allowlist must be a list of strings when set")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("tool_allowlist entries must be strings")
            name = item.strip()
            if not name:
                raise ValueError("tool_allowlist entries must be non-empty when set")
            if len(name) > MAX_AGENT_TOOL_NAME_LENGTH:
                raise ValueError("tool_allowlist entry is too long")
            cleaned.append(name)
        return cleaned

    @field_validator("ttl_seconds", mode="before")
    @classmethod
    def _ttl_seconds(cls, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("ttl_seconds must be a positive integer when set")
        return value


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    agent_id: UUID
    title: str
    description: str
    dependencies: list[UUID] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    output: dict[str, Any] | None = None


class PaymentIntent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    recipient: str
    asset: str = "USDC"
    chain: str = "evm-mainnet"
    amount: float = Field(gt=0)
    reason: str
    status: str = "simulated"
    transaction_hash: str | None = None
    idempotency_key: str | None = None


class MissionEvent(BaseModel):
    """Append-only mission event. `event_type` is the historical dotted name from EventType."""

    id: int | None = None
    mission_id: UUID
    event_type: str
    actor_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
