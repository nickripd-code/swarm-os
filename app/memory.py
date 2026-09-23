"""Scoped MemoryProvider seed.

Stores short notes per mission (and optionally per agent) in SQLite via Store.
Recall is bounded by a character cap used as a conservative token proxy.
Oversize or corrupt notes fail closed. Empty storage returns no notes — never invent.

Summarization is an opt-in deterministic extractive seed. It does not call a model.
When one mission or agent scope exceeds an explicit character bound, older notes in
that scope are collapsed into one note whose body is the ``[summary]`` marker plus
a prefix of the existing note text. The summary counts toward the recall cap.
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
# Extractive marker only. The remainder of a summary is source note text.
SUMMARY_MARKER = "[summary]\n"


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

    def summarize(
        self,
        mission_id: UUID,
        *,
        agent_id: UUID | None = None,
        max_chars: int | None = None,
    ) -> MemoryNote | None:
        """Collapse older notes in one scope. Default providers must opt in."""
        raise MemoryError(
            "Memory summarization is opt-in; set summarize_over_chars or pass max_chars",
            FailureClass.INVALID_OUTPUT,
        )


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


def _extractive_summary(bodies: list[str], max_chars: int) -> str:
    """Marker plus a prefix of the joined source bodies. Adds no facts."""
    if max_chars < len(SUMMARY_MARKER) + 1:
        raise MemoryError(
            "Memory summarization bound is smaller than the summary marker",
            FailureClass.CONTEXT_LIMIT,
        )
    joined = "\n".join(bodies)
    if not joined.strip():
        raise MemoryError("Memory summary source is empty", FailureClass.INVALID_OUTPUT)
    excerpt = joined[: max_chars - len(SUMMARY_MARKER)]
    if not excerpt.strip():
        raise MemoryError("Memory summary source is empty", FailureClass.INVALID_OUTPUT)
    return SUMMARY_MARKER + excerpt


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
        summarize_over_chars: int | None = None,
    ):
        if max_note_chars <= 0 or max_recall_chars <= 0:
            raise MemoryError("Memory size caps must be positive", FailureClass.CONTEXT_LIMIT)
        if summarize_over_chars is not None and summarize_over_chars < len(SUMMARY_MARKER) + 1:
            raise MemoryError(
                "Memory summarization bound is smaller than the summary marker",
                FailureClass.CONTEXT_LIMIT,
            )
        self.store = store
        self.max_note_chars = max_note_chars
        self.max_recall_chars = max_recall_chars
        self.summarize_over_chars = summarize_over_chars

    def health(self) -> MemoryHealth:
        return MemoryHealth(
            provider=self.provider_id,
            status="healthy",
            configured=True,
            detail="SQLite scoped notes; recall is size-capped; extractive summary is opt-in",
        )

    def remember(self, mission_id: UUID, body: str, *, agent_id: UUID | None = None) -> MemoryNote:
        text = _normalize_body(body)
        if len(text) > self.max_note_chars:
            raise MemoryError("Memory note exceeds the per-note size cap", FailureClass.CONTEXT_LIMIT)
        if self.summarize_over_chars is not None and len(text) > self.summarize_over_chars:
            raise MemoryError("Memory note exceeds the summarization bound", FailureClass.CONTEXT_LIMIT)
        note = MemoryNote(mission_id=mission_id, agent_id=agent_id, body=text)
        with self.store.sessions.begin() as db:
            if self.summarize_over_chars is not None:
                existing = self._load_exact(db, mission_id, agent_id)
                plan = self._plan_summary(existing + [note], self.summarize_over_chars)
                if plan is not None and any(item.id == note.id for item in plan[0]):
                    raise MemoryError(
                        "Memory note does not fit the summarization bound",
                        FailureClass.CONTEXT_LIMIT,
                    )
            db.add(MemoryNoteRow(
                id=str(note.id),
                mission_id=str(note.mission_id),
                agent_id=str(note.agent_id) if note.agent_id else None,
                body=note.body,
                created_at=note.created_at,
            ))
            if self.summarize_over_chars is not None:
                db.flush()
                self._summarize_in_session(db, mission_id, agent_id, self.summarize_over_chars)
        return note

    def summarize(
        self,
        mission_id: UUID,
        *,
        agent_id: UUID | None = None,
        max_chars: int | None = None,
    ) -> MemoryNote | None:
        """Compress one scope with the extractive summarizer.

        ``max_chars`` overrides ``summarize_over_chars`` for this call. With neither
        set, this fails closed and writes nothing. An empty scope stays empty.
        """
        bound = self._summary_bound(max_chars)
        with self.store.sessions.begin() as db:
            return self._summarize_in_session(db, mission_id, agent_id, bound)

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

    def _summary_bound(self, max_chars: int | None) -> int:
        bound = self.summarize_over_chars if max_chars is None else max_chars
        if bound is None:
            raise MemoryError(
                "Memory summarization is opt-in; set summarize_over_chars or pass max_chars",
                FailureClass.INVALID_OUTPUT,
            )
        if bound < len(SUMMARY_MARKER) + 1:
            raise MemoryError(
                "Memory summarization bound is smaller than the summary marker",
                FailureClass.CONTEXT_LIMIT,
            )
        return bound

    def _summarize_in_session(self, db, mission_id: UUID, agent_id: UUID | None, bound: int) -> MemoryNote | None:
        notes = self._load_exact(db, mission_id, agent_id)
        plan = self._plan_summary(notes, bound)
        if plan is None:
            return None
        older, summary_body = plan
        return self._apply_summary(db, older, summary_body, mission_id, agent_id)

    def _plan_summary(
        self, notes: list[MemoryNote], bound: int,
    ) -> tuple[list[MemoryNote], str] | None:
        """Choose the smallest oldest prefix that must be collapsed.

        The summary is a marker plus a prefix of those notes' existing text.
        Newest notes stay intact when the summary still fits in the leftover budget.
        """
        if sum(len(note.body) for note in notes) <= bound:
            return None
        for split in range(1, len(notes) + 1):
            older = notes[:split]
            newer = notes[split:]
            newer_chars = sum(len(note.body) for note in newer)
            summary_cap = min(bound - newer_chars, self.max_note_chars)
            if summary_cap < len(SUMMARY_MARKER) + 1:
                continue
            body = _extractive_summary([note.body for note in older], summary_cap)
            if len(body) <= summary_cap and newer_chars + len(body) <= bound:
                return older, body
        raise MemoryError(
            "Scoped notes exceed the summarization bound and cannot be compressed",
            FailureClass.CONTEXT_LIMIT,
        )

    def _apply_summary(
        self,
        db,
        older: list[MemoryNote],
        summary_body: str,
        mission_id: UUID,
        agent_id: UUID | None,
    ) -> MemoryNote:
        oldest = older[0]
        row = db.get(MemoryNoteRow, str(oldest.id))
        self._assert_same_row(row, oldest, mission_id, agent_id)
        row.body = summary_body
        for note in older[1:]:
            extra = db.get(MemoryNoteRow, str(note.id))
            self._assert_same_row(extra, note, mission_id, agent_id)
            db.delete(extra)
        return MemoryNote(
            id=oldest.id,
            mission_id=mission_id,
            agent_id=agent_id,
            body=summary_body,
            created_at=oldest.created_at,
        )

    def _assert_same_row(self, row: MemoryNoteRow | None, note: MemoryNote, mission_id: UUID, agent_id: UUID | None) -> None:
        expected_agent = str(agent_id) if agent_id else None
        if (
            row is None
            or not isinstance(row.body, str)
            or row.body != note.body
            or str(row.mission_id) != str(mission_id)
            or row.agent_id != expected_agent
        ):
            raise MemoryError("Persisted memory note is corrupt", FailureClass.INVALID_OUTPUT)

    def _load_exact(self, db, mission_id: UUID, agent_id: UUID | None) -> list[MemoryNote]:
        stmt = select(MemoryNoteRow).where(MemoryNoteRow.mission_id == str(mission_id))
        if agent_id is None:
            stmt = stmt.where(MemoryNoteRow.agent_id.is_(None))
        else:
            stmt = stmt.where(MemoryNoteRow.agent_id == str(agent_id))
        stmt = stmt.order_by(MemoryNoteRow.created_at, MemoryNoteRow.id)
        return [self._row_to_note(row) for row in db.scalars(stmt).all()]

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
