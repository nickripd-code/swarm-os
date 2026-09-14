"""Scoped MemoryProvider seed.

Stores short notes per mission (and optionally per agent) in SQLite via Store.
Recall is bounded by a character cap used as a conservative token proxy.
Oversize or corrupt notes fail closed. Empty storage returns no notes — never invent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from .models import FailureClass, utcnow
from .store import MemoryNoteRow, Store

# Conservative token proxy: 4 characters ≈ 1 token. Caps stay in characters.
CHARS_PER_TOKEN = 4
MAX_NOTE_CHARS = 1024
MAX_RECALL_CHARS = 4096  # ≈ 1024 tokens


class MemoryError(Exception):
    """Safe memory failure. Messages must never contain credentials or invented notes."""

    def __init__(self, message: str, failure_class: FailureClass = FailureClass.CONTEXT_LIMIT):
        super().__init__(message)
        self.failure_class = failure_class


class MemoryNote(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    agent_id: UUID | None = None
    body: str
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def scope(self) -> Literal["mission", "agent"]:
        return "agent" if self.agent_id is not None else "mission"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id) if self.agent_id else None,
            "scope": self.scope,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
        }


class MemoryHealth(BaseModel):
    provider: str
    status: Literal["healthy", "unconfigured", "unavailable"]
    configured: bool
    detail: str | None = None


class MemoryProvider(ABC):
    """Provider-neutral scoped notes. Do not invent memories."""

    provider_id: str

    @abstractmethod
    def remember(self, mission_id: UUID, body: str, *, agent_id: UUID | None = None) -> MemoryNote:
        raise NotImplementedError

    @abstractmethod
    def recall(
        self,
        mission_id: UUID,
        *,
        agent_id: UUID | None = None,
        max_chars: int | None = None,
    ) -> list[MemoryNote]:
        raise NotImplementedError

    def health(self) -> MemoryHealth:
        return MemoryHealth(provider=self.provider_id, status="healthy", configured=True)


def recall_char_cap(max_chars: int | None = None, *, max_tokens: int | None = None) -> int:
    """Resolve the recall size cap. Token limits convert at CHARS_PER_TOKEN."""
    if max_chars is not None and max_tokens is not None:
        raise MemoryError("Pass max_chars or max_tokens, not both", FailureClass.INVALID_OUTPUT)
    if max_tokens is not None:
        if max_tokens <= 0:
            raise MemoryError("Memory recall token cap must be positive", FailureClass.CONTEXT_LIMIT)
        return max_tokens * CHARS_PER_TOKEN
    if max_chars is None:
        return MAX_RECALL_CHARS
    if max_chars <= 0:
        raise MemoryError("Memory recall cap must be positive", FailureClass.CONTEXT_LIMIT)
    return max_chars


def _normalize_body(body: str) -> str:
    if not isinstance(body, str):
        raise MemoryError("Memory note body must be text", FailureClass.INVALID_OUTPUT)
    text = body.strip()
    if not text:
        raise MemoryError("Memory note body must not be empty", FailureClass.INVALID_OUTPUT)
    if len(text) > MAX_NOTE_CHARS:
        raise MemoryError("Memory note exceeds the per-note size cap", FailureClass.CONTEXT_LIMIT)
    return text


def _aware(value: datetime | None) -> datetime:
    if value is None:
        raise MemoryError("Persisted memory note is missing created_at", FailureClass.INVALID_OUTPUT)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class StoreMemoryProvider(MemoryProvider):
    """SQLite-backed notes using Store sessions. Production default."""

    provider_id = "sqlite"

    def __init__(
        self,
        store: Store,
        *,
        max_note_chars: int = MAX_NOTE_CHARS,
        max_recall_chars: int = MAX_RECALL_CHARS,
    ):
        if max_note_chars <= 0 or max_recall_chars <= 0:
            raise MemoryError("Memory size caps must be positive", FailureClass.CONTEXT_LIMIT)
        self.store = store
        self.max_note_chars = max_note_chars
        self.max_recall_chars = max_recall_chars

    def health(self) -> MemoryHealth:
        return MemoryHealth(
            provider=self.provider_id,
            status="healthy",
            configured=True,
            detail="SQLite scoped notes; recall is size-capped",
        )

    def remember(self, mission_id: UUID, body: str, *, agent_id: UUID | None = None) -> MemoryNote:
        text = _normalize_body(body)
        if len(text) > self.max_note_chars:
            raise MemoryError("Memory note exceeds the per-note size cap", FailureClass.CONTEXT_LIMIT)
        note = MemoryNote(mission_id=mission_id, agent_id=agent_id, body=text)
        with self.store.sessions.begin() as db:
            db.add(MemoryNoteRow(
                id=str(note.id),
                mission_id=str(note.mission_id),
                agent_id=str(note.agent_id) if note.agent_id else None,
                body=note.body,
                created_at=note.created_at,
            ))
        return note

    def recall(
        self,
        mission_id: UUID,
        *,
        agent_id: UUID | None = None,
        max_chars: int | None = None,
        max_tokens: int | None = None,
    ) -> list[MemoryNote]:
        cap = recall_char_cap(max_chars, max_tokens=max_tokens)
        if max_chars is None and max_tokens is None:
            cap = min(cap, self.max_recall_chars)
        notes = self._load_scoped(mission_id, agent_id)
        return self._bound(notes, cap)

    def _load_scoped(self, mission_id: UUID, agent_id: UUID | None) -> list[MemoryNote]:
        with self.store.sessions() as db:
            rows = db.scalars(
                select(MemoryNoteRow)
                .where(MemoryNoteRow.mission_id == str(mission_id))
                .order_by(MemoryNoteRow.created_at, MemoryNoteRow.id)
            ).all()
            notes = [self._row_to_note(row) for row in rows]
        scoped: list[MemoryNote] = []
        for note in notes:
            if note.agent_id is None:
                scoped.append(note)
            elif agent_id is not None and note.agent_id == agent_id:
                scoped.append(note)
        return scoped

    def _row_to_note(self, row: MemoryNoteRow) -> MemoryNote:
        if row.body is None or not isinstance(row.body, str) or not row.body.strip():
            raise MemoryError("Persisted memory note is corrupt", FailureClass.INVALID_OUTPUT)
        if len(row.body) > self.max_note_chars:
            raise MemoryError("Persisted memory note exceeds the per-note size cap", FailureClass.CONTEXT_LIMIT)
        try:
            return MemoryNote(
                id=UUID(str(row.id)),
                mission_id=UUID(str(row.mission_id)),
                agent_id=UUID(str(row.agent_id)) if row.agent_id else None,
                body=row.body,
                created_at=_aware(row.created_at),
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise MemoryError("Persisted memory note is corrupt", FailureClass.INVALID_OUTPUT) from exc

    def _bound(self, notes: list[MemoryNote], cap: int) -> list[MemoryNote]:
        selected: list[MemoryNote] = []
        used = 0
        for note in reversed(notes):
            size = len(note.body)
            if size > cap and not selected:
                raise MemoryError(
                    "Memory note exceeds the recall size cap",
                    FailureClass.CONTEXT_LIMIT,
                )
            if used + size > cap:
                break
            selected.append(note)
            used += size
        selected.reverse()
        return selected
