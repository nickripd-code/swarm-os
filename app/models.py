from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MissionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
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


class MissionCreate(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    budget: float = Field(default=0, ge=0)
    live_payments: bool = False
    limits: MissionLimits = Field(default_factory=MissionLimits)


class PendingQuestion(BaseModel):
    question_id: str
    question: str
    reason: str | None = None


class MissionAnswer(BaseModel):
    question_id: str
    question: str
    answer: str
    answered_at: datetime = Field(default_factory=utcnow)


class Mission(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    goal: str
    status: MissionStatus = MissionStatus.PENDING
    budget: float = 0
    spent: float = 0
    live_payments: bool = False
    limits: MissionLimits = Field(default_factory=MissionLimits)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    result: dict[str, Any] | None = None
    pending_question: PendingQuestion | None = None
    answers: list[MissionAnswer] = Field(default_factory=list)


class AgentSpec(BaseModel):
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


class MissionEvent(BaseModel):
    id: int | None = None
    mission_id: UUID
    event_type: str
    actor_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
