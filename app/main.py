from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import AnswerRequest, Mission, MissionCreate, PaymentIntent, MissionStatus, utcnow
from .runtime import PolicyError, SwarmRuntime
from .store import Store
from .health import openai_status

BASE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app):
    for mission in store.list_missions():
        if mission.status in {MissionStatus.PENDING, MissionStatus.RUNNING, MissionStatus.WAITING}:
            mission.status, mission.updated_at = MissionStatus.STOPPED, utcnow()
            store.save_mission(mission)
            await runtime.emit(mission.id, "mission.stopped", {"reason": "Server restarted; execution was interrupted"})
    yield
    await runtime.stop_all()


app = FastAPI(title="Agent Swarm", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
store = Store(str(BASE.parent / "swarm.db"))
clients: dict[UUID, set[WebSocket]] = {}


async def broadcast(event):
    for ws in list(clients.get(event.mission_id, set())):
        try: await ws.send_json(event.model_dump(mode="json"))
        except Exception: clients[event.mission_id].discard(ws)


runtime = SwarmRuntime(store, broadcast)


@app.get("/", include_in_schema=False)
async def index(): return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
async def health():
    return {"ok": True, "openai": openai_status(), "active_missions": len(runtime.runs)}


@app.get("/api/missions")
async def list_missions():
    return store.list_missions()[:100]


@app.post("/api/stop-all")
async def stop_all():
    stopped = await runtime.stop_all()
    return {"status": "stopped", "mission_ids": stopped, "active_missions": len(runtime.runs)}


@app.post("/api/missions", response_model=Mission, status_code=201)
async def create_mission(request: MissionCreate):
    if not runtime.controller.configured():
        raise HTTPException(503, "OpenAI key is not configured. Set it on the server before launching.")
    mission = Mission(goal=request.goal, budget=request.budget, live_payments=request.live_payments, limits=request.limits)
    store.save_mission(mission)
    await runtime.start(mission)
    return mission


@app.get("/api/missions/{mission_id}", response_model=Mission)
async def get_mission(mission_id: UUID):
    mission = store.get_mission(mission_id)
    if not mission: raise HTTPException(404, "Mission not found")
    return mission


@app.get("/api/missions/{mission_id}/events")
async def get_events(mission_id: UUID): return [e.model_dump(mode="json") for e in store.events(mission_id)]


@app.get("/api/missions/{mission_id}/agents")
async def get_agents(mission_id: UUID):
    if not store.get_mission(mission_id): raise HTTPException(404, "Mission not found")
    return store.project(mission_id)["agents"]


@app.get("/api/missions/{mission_id}/tasks")
async def get_tasks(mission_id: UUID):
    if not store.get_mission(mission_id): raise HTTPException(404, "Mission not found")
    return store.project(mission_id)["tasks"]


@app.post("/api/missions/{mission_id}/payments", response_model=PaymentIntent)
async def create_payment(mission_id: UUID, intent: PaymentIntent):
    mission = store.get_mission(mission_id)
    if not mission: raise HTTPException(404, "Mission not found")
    if intent.mission_id != mission_id: raise HTTPException(400, "mission_id does not match URL")
    try:
        return await runtime.create_payment(mission, intent.recipient, intent.amount, intent.reason)
    except PolicyError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/missions/{mission_id}/stop")
async def stop_mission(mission_id: UUID):
    if not store.get_mission(mission_id): raise HTTPException(404, "Mission not found")
    mission = await runtime.stop(mission_id)
    return {"status": mission.status}


@app.post("/api/missions/{mission_id}/answers/{question_id}")
async def answer_question(mission_id: UUID, question_id: str, request: AnswerRequest):
    await runtime.emit(mission_id, "user.answered", {"question_id": question_id, "answer": request.answer})
    return {"accepted": True}


@app.websocket("/api/missions/{mission_id}/stream")
async def stream(websocket: WebSocket, mission_id: UUID):
    if not store.get_mission(mission_id):
        await websocket.close(code=1008)
        return
    await websocket.accept(); clients.setdefault(mission_id, set()).add(websocket)
    try:
        for event in store.events(mission_id): await websocket.send_json(event.model_dump(mode="json"))
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.get(mission_id, set()).discard(websocket)
