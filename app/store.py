from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .models import Mission, MissionEvent


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


class Store:
    def __init__(self, path: str = "swarm.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
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

    def project(self, mission_id: UUID) -> dict:
        agents, tasks = {}, {}
        for event in self.events(mission_id):
            p = event.payload
            if event.event_type in {"agent.spawned", "agent.updated"}:
                agents[p["id"]] = {**agents.get(p["id"], {}), **p}
            elif event.event_type.startswith("task."):
                tid = p.get("id") or p.get("task_id")
                if tid:
                    status = event.event_type.split(".")[1]
                    status = "running" if status == "started" else status
                    tasks[tid] = {**tasks.get(tid, {}), **p, "id": tid, "status": status}
            elif event.event_type in {"mission.stopped", "mission.failed"}:
                for agent in agents.values():
                    if agent["status"] in {"created", "running"}:
                        agent["status"] = event.event_type.split(".")[1]
        return {"agents": list(agents.values()), "tasks": list(tasks.values())}

    def append(self, event: MissionEvent) -> MissionEvent:
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
            return [MissionEvent(id=r.id, mission_id=UUID(r.mission_id), event_type=r.event_type,
                                 actor_id=UUID(r.actor_id) if r.actor_id else None,
                                 payload=json.loads(r.payload), created_at=r.created_at) for r in rows]
