from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .events import (
    EventType, coerce_event_type, is_task_event, parse_event_type, task_status_from_event,
)
from .migrations import apply_migrations
from .models import (
    AgentSpec, Mission, MissionAnswer, MissionEvent, MissionInject, MissionStatus, Task, utcnow,
)


class AnswerStateError(RuntimeError):
    """A durable mission cannot accept or consume the requested answer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_ANSWERABLE_STATUSES = frozenset({MissionStatus.WAITING, MissionStatus.PAUSED})
_INJECTABLE_STATUSES = frozenset({MissionStatus.RUNNING, MissionStatus.WAITING})
_TERMINAL_MISSION_STATUSES = frozenset({
    MissionStatus.BLOCKED, MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.STOPPED,
})
MAX_MISSION_INJECTS = 32


def _merge_injects(local: list[MissionInject], durable: list[MissionInject]) -> list[MissionInject]:
    """Union injects. A consumed copy wins so a later save cannot un-consume one."""
    merged: dict[str, MissionInject] = {}
    order: list[str] = []
    for item in [*local, *durable]:
        current = merged.get(item.inject_id)
        if current is None:
            merged[item.inject_id] = item
            order.append(item.inject_id)
            continue
        if current.consumed_at is None and item.consumed_at is not None:
            merged[item.inject_id] = item
    return [merged[key] for key in order]


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "mission_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MissionRow(Base):
    __tablename__ = "missions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRow(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkerLeaseRow(Base):
    __tablename__ = "worker_leases"
    __table_args__ = (UniqueConstraint("scope", "scope_id", name="uq_worker_lease_scope"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32))
    scope_id: Mapped[str] = mapped_column(String(36))
    mission_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(32), default="claimed")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("mission_id", "key", name="uq_idempotency_mission_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(String(36), index=True)
    key: Mapped[str] = mapped_column(String(200))
    step: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkItemRow(Base):
    __tablename__ = "work_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    mission_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    lease_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemoryNoteRow(Base):
    __tablename__ = "memory_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Store:
    def __init__(self, path: str = "swarm.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        apply_migrations(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def save_mission(self, mission: Mission) -> None:
        with self.sessions.begin() as db:
            row = db.get(MissionRow, str(mission.id))
            payload = mission.model_dump_json()
            if row:
                row.payload, row.updated_at = payload, mission.updated_at
            else:
                db.add(MissionRow(id=str(mission.id), payload=payload, updated_at=mission.updated_at))

    def get_mission(self, mission_id: UUID) -> Mission | None:
        with self.sessions() as db:
            row = db.get(MissionRow, str(mission_id))
            return Mission.model_validate_json(row.payload) if row else None

    def list_missions(self) -> list[Mission]:
        with self.sessions() as db:
            rows = db.scalars(select(MissionRow).order_by(MissionRow.updated_at.desc())).all()
            return [Mission.model_validate_json(row.payload) for row in rows]

    def accept_answer(self, mission_id: UUID, question_id: str, answer: str,
                      *, attempts: int = 3) -> tuple[Mission, MissionAnswer]:
        """Atomically consume the open question with compare-and-swap persistence."""
        for _ in range(attempts):
            with self.sessions.begin() as db:
                row = db.get(MissionRow, str(mission_id))
                if row is None:
                    raise AnswerStateError("not_found", "Mission not found")
                original = row.payload
                mission = Mission.model_validate_json(original)
                if any(item.question_id == question_id for item in mission.answers):
                    raise AnswerStateError("duplicate", "This question was already answered")
                if mission.status in {
                    MissionStatus.BLOCKED, MissionStatus.COMPLETED,
                    MissionStatus.FAILED, MissionStatus.STOPPED,
                }:
                    raise AnswerStateError("terminal", "Mission is no longer accepting answers")
                pending = mission.pending_question
                if pending is None:
                    raise AnswerStateError("missing", "No question is awaiting an answer")
                if mission.status not in _ANSWERABLE_STATUSES:
                    raise AnswerStateError("status", "Mission is not accepting answers in its current state")
                if pending.question_id != question_id:
                    raise AnswerStateError("mismatch", "Answer does not match the open question")
                record = MissionAnswer(
                    question_id=question_id,
                    question=pending.question,
                    answer=answer,
                    kind=pending.kind,
                    approval_action=pending.approval_action,
                )
                mission.answers.append(record)
                mission.pending_question = None
                mission.updated_at = utcnow()
                changed = db.execute(
                    update(MissionRow)
                    .where(MissionRow.id == str(mission_id), MissionRow.payload == original)
                    .values(payload=mission.model_dump_json(), updated_at=mission.updated_at)
                )
                if getattr(changed, "rowcount", 0) == 1:
                    return mission, record
        raise AnswerStateError("conflict", "Mission changed while the answer was being accepted")

    def mark_answer_consumed(self, mission_id: UUID, question_id: str,
                             *, attempts: int = 3) -> tuple[Mission, MissionAnswer, bool]:
        """Persist controller consumption before a truthful consumption event is emitted."""
        for _ in range(attempts):
            with self.sessions.begin() as db:
                row = db.get(MissionRow, str(mission_id))
                if row is None:
                    raise AnswerStateError("not_found", "Mission not found")
                original = row.payload
                mission = Mission.model_validate_json(original)
                record = next((item for item in mission.answers if item.question_id == question_id), None)
                if record is None:
                    raise AnswerStateError("missing", "The matching human answer is not persisted")
                if record.consumed_at is not None:
                    return mission, record, False
                record.consumed_at = utcnow()
                mission.updated_at = record.consumed_at
                changed = db.execute(
                    update(MissionRow)
                    .where(MissionRow.id == str(mission_id), MissionRow.payload == original)
                    .values(payload=mission.model_dump_json(), updated_at=mission.updated_at)
                )
                if getattr(changed, "rowcount", 0) == 1:
                    return mission, record, True
        raise AnswerStateError("conflict", "Mission changed while the answer was being consumed")

    def accept_inject(self, mission_id: UUID, text: str, data: dict | None,
                      *, attempts: int = 3) -> tuple[Mission, MissionInject]:
        """Append one server-identified inject. Only a live RUNNING or WAITING mission accepts it."""
        for _ in range(attempts):
            with self.sessions.begin() as db:
                row = db.get(MissionRow, str(mission_id))
                if row is None:
                    raise AnswerStateError("not_found", "Mission not found")
                original = row.payload
                mission = Mission.model_validate_json(original)
                if mission.status in _TERMINAL_MISSION_STATUSES:
                    raise AnswerStateError("terminal", "Mission is no longer accepting injects")
                if mission.status not in _INJECTABLE_STATUSES:
                    raise AnswerStateError("status", "Mission is not live")
                if len(mission.injects) >= MAX_MISSION_INJECTS:
                    raise AnswerStateError("status", "Inject limit reached")
                record = MissionInject(inject_id=str(uuid4()), text=text, data=data)
                mission.injects.append(record)
                mission.updated_at = utcnow()
                changed = db.execute(
                    update(MissionRow)
                    .where(MissionRow.id == str(mission_id), MissionRow.payload == original)
                    .values(payload=mission.model_dump_json(), updated_at=mission.updated_at)
                )
                if getattr(changed, "rowcount", 0) == 1:
                    return mission, record
        raise AnswerStateError("conflict", "Mission changed while the inject was being accepted")

    def mark_inject_consumed(self, mission_id: UUID, inject_id: str,
                             *, attempts: int = 3) -> tuple[Mission, MissionInject, bool]:
        """Persist controller/worker consumption before a truthful consumption event is emitted."""
        for _ in range(attempts):
            with self.sessions.begin() as db:
                row = db.get(MissionRow, str(mission_id))
                if row is None:
                    raise AnswerStateError("not_found", "Mission not found")
                original = row.payload
                mission = Mission.model_validate_json(original)
                record = next((item for item in mission.injects if item.inject_id == inject_id), None)
                if record is None:
                    raise AnswerStateError("missing", "The matching inject is not persisted")
                if record.consumed_at is not None:
                    return mission, record, False
                record.consumed_at = utcnow()
                mission.updated_at = record.consumed_at
                changed = db.execute(
                    update(MissionRow)
                    .where(MissionRow.id == str(mission_id), MissionRow.payload == original)
                    .values(payload=mission.model_dump_json(), updated_at=mission.updated_at)
                )
                if getattr(changed, "rowcount", 0) == 1:
                    return mission, record, True
        raise AnswerStateError("conflict", "Mission changed while the inject was being consumed")

    def save_mission_with_injects(self, mission: Mission, *, attempts: int = 3) -> None:
        """Save runtime mission state without dropping an inject accepted in another transaction."""
        for _ in range(attempts):
            with self.sessions.begin() as db:
                row = db.get(MissionRow, str(mission.id))
                if row is None:
                    db.add(MissionRow(id=str(mission.id), payload=mission.model_dump_json(),
                                      updated_at=mission.updated_at))
                    return
                original = row.payload
                saved = Mission.model_validate_json(original)
                mission.injects = _merge_injects(mission.injects, saved.injects)
                changed = db.execute(
                    update(MissionRow)
                    .where(MissionRow.id == str(mission.id), MissionRow.payload == original)
                    .values(payload=mission.model_dump_json(), updated_at=mission.updated_at)
                )
                if getattr(changed, "rowcount", 0) == 1:
                    return
        raise AnswerStateError("conflict", "Mission changed while injects were being preserved")

    def save_agent(self, agent: AgentSpec) -> None:
        with self.sessions.begin() as db:
            row = db.get(AgentRow, str(agent.id))
            payload = agent.model_dump_json()
            now = utcnow()
            if row:
                row.payload, row.updated_at = payload, now
            else:
                db.add(AgentRow(id=str(agent.id), mission_id=str(agent.mission_id), payload=payload,
                                created_at=agent.created_at, updated_at=now))

    def save_task(self, task: Task) -> None:
        with self.sessions.begin() as db:
            row = db.get(TaskRow, str(task.id))
            payload = task.model_dump_json()
            now = utcnow()
            if row:
                row.payload, row.updated_at = payload, now
            else:
                db.add(TaskRow(id=str(task.id), mission_id=str(task.mission_id), payload=payload,
                               created_at=now, updated_at=now))

    def load_agents(self, mission_id: UUID) -> list[AgentSpec]:
        with self.sessions() as db:
            rows = db.scalars(select(AgentRow).where(AgentRow.mission_id == str(mission_id))
                              .order_by(AgentRow.created_at, AgentRow.id)).all()
            return [AgentSpec.model_validate_json(row.payload) for row in rows]

    def load_tasks(self, mission_id: UUID) -> list[Task]:
        with self.sessions() as db:
            rows = db.scalars(select(TaskRow).where(TaskRow.mission_id == str(mission_id))
                              .order_by(TaskRow.created_at, TaskRow.id)).all()
            return [Task.model_validate_json(row.payload) for row in rows]

    def project(self, mission_id: UUID) -> dict:
        agents = {str(agent.id): agent.model_dump(mode="json")
                  for agent in self.load_agents(mission_id)}
        tasks = {str(task.id): task.model_dump(mode="json")
                 for task in self.load_tasks(mission_id)}
        projected = self.project_events(mission_id)
        for item in projected["agents"]:
            key = str(item["id"])
            agents.setdefault(key, item)
        for item in projected["tasks"]:
            key = str(item["id"])
            tasks.setdefault(key, item)
        return {"agents": list(agents.values()), "tasks": list(tasks.values())}

    def project_events(self, mission_id: UUID) -> dict:
        agents, tasks = {}, {}
        for event in self.events(mission_id):
            p = event.payload
            if event.event_type in {EventType.AGENT_SPAWNED, EventType.AGENT_UPDATED}:
                agents[p["id"]] = {**agents.get(p["id"], {}), **p}
            elif event.event_type == EventType.AGENT_REPARENTED:
                key = p.get("id") or p.get("agent_id")
                if key:
                    update = {**agents.get(key, {}), "id": key}
                    if "parent_id" in p:
                        update["parent_id"] = p["parent_id"]
                    if "depth" in p:
                        update["depth"] = p["depth"]
                    agents[key] = update
            elif event.event_type == EventType.AGENT_RETIRED:
                key = p.get("id") or p.get("agent_id")
                if key:
                    agents[key] = {**agents.get(key, {}), "id": key,
                                   "status": p.get("status") or "stopped"}
            elif event.event_type == EventType.AGENT_KILLED:
                key = str(p.get("id") or p.get("agent_id") or "")
                if key:
                    agents[key] = {**agents.get(key, {}), **p, "id": key,
                                   "status": p.get("status") or "stopped"}
            elif is_task_event(event.event_type):
                tid = p.get("id") or p.get("task_id")
                if tid:
                    status = task_status_from_event(event.event_type)
                    tasks[tid] = {**tasks.get(tid, {}), **p, "id": tid, "status": status}
            elif event.event_type in {EventType.MISSION_STOPPED, EventType.MISSION_FAILED}:
                for agent in agents.values():
                    if agent["status"] in {"created", "running"}:
                        agent["status"] = task_status_from_event(event.event_type)
        return {"agents": list(agents.values()), "tasks": list(tasks.values())}

    def append(self, event: MissionEvent) -> MissionEvent:
        event.event_type = parse_event_type(event.event_type).value
        with self.sessions.begin() as db:
            row = EventRow(mission_id=str(event.mission_id), event_type=event.event_type,
                           actor_id=str(event.actor_id) if event.actor_id else None,
                           payload=json.dumps(event.payload, default=str), created_at=event.created_at)
            db.add(row)
            db.flush()
            event.id = row.id
        return event

    def events(self, mission_id: UUID) -> list[MissionEvent]:
        with self.sessions() as db:
            rows = db.scalars(select(EventRow).where(EventRow.mission_id == str(mission_id)).order_by(EventRow.id)).all()
            return [MissionEvent(id=r.id, mission_id=UUID(r.mission_id), event_type=coerce_event_type(r.event_type),
                                 actor_id=UUID(r.actor_id) if r.actor_id else None,
                                 payload=json.loads(r.payload),
                                 created_at=(r.created_at.replace(tzinfo=timezone.utc)
                                             if r.created_at.tzinfo is None else r.created_at))
                    for r in rows]
