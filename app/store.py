from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .events import (
    EventType, coerce_event_type, is_task_event, parse_event_type, task_status_from_event,
)
from .migrations import apply_migrations
from .models import AgentSpec, Mission, MissionEvent, Task, utcnow


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
