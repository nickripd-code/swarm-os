from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable
from uuid import UUID

from .models import (
    AgentSpec, AgentStatus, FailureClass, Mission, MissionEvent, MissionStatus,
    PaymentIntent, Task, TaskStatus, utcnow,
)
from .store import Store
from .llm import LLMProvider, OpenAIProvider, ProviderError

TERMINAL = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.STOPPED, MissionStatus.BLOCKED}


class PolicyError(Exception):
    def __init__(self, message: str, failure_class: FailureClass = FailureClass.POLICY_REFUSAL):
        super().__init__(message)
        self.failure_class = failure_class


def failure_payload(error: str, failure_class: FailureClass) -> dict[str, Any]:
    return {"error": error, "failure_class": str(failure_class)}


class WalletAdapter:
    async def pay(self, intent: PaymentIntent, mission: Mission) -> PaymentIntent:
        if not mission.live_payments:
            intent.status = "simulated"
            intent.transaction_hash = None
            return intent
        raise PolicyError("Live wallet provider is not configured", FailureClass.AUTHORIZATION_REQUIRED)


EventSink = Callable[[MissionEvent], Awaitable[None]]


class SwarmRuntime:
    def __init__(self, store: Store, sink: EventSink | None = None, controller: LLMProvider | None = None):
        self.store, self.sink = store, sink
        self.agents: dict[UUID, list[AgentSpec]] = defaultdict(list)
        self.tasks: dict[UUID, list[Task]] = defaultdict(list)
        self.stopped: set[UUID] = set()
        self.runs: dict[UUID, asyncio.Task] = {}
        self.wallet = WalletAdapter()
        self.controller = controller or OpenAIProvider()
        self.lock = asyncio.Lock()

    async def emit(self, mission_id: UUID, event_type: str, payload: dict[str, Any], actor_id: UUID | None = None):
        event = self.store.append(MissionEvent(mission_id=mission_id, event_type=event_type, actor_id=actor_id, payload=payload))
        if self.sink:
            await self.sink(event)

    def check_stopped(self, mission_id: UUID):
        if mission_id in self.stopped:
            raise asyncio.CancelledError()

    async def spawn(self, mission: Mission, role: str, purpose: str, parent: AgentSpec | None = None,
                    capabilities: list[str] | None = None) -> AgentSpec:
        self.check_stopped(mission.id)
        current = self.agents[mission.id]
        depth = parent.depth + 1 if parent else 0
        if parent and parent.mission_id != mission.id:
            raise PolicyError("Parent must belong to this mission")
        if depth > mission.limits.max_depth or len(current) >= mission.limits.max_agents:
            raise PolicyError("Agent spawning limit reached", FailureClass.RESOURCE_EXHAUSTED)
        agent = AgentSpec(mission_id=mission.id, parent_id=parent.id if parent else None,
                          role=role, purpose=purpose, capabilities=capabilities or [], depth=depth)
        current.append(agent)
        await self.emit(mission.id, "agent.spawned", agent.model_dump(mode="json"), agent.id)
        return agent

    async def agent_status(self, agent: AgentSpec, status: AgentStatus):
        agent.status = status
        await self.emit(agent.mission_id, "agent.updated", agent.model_dump(mode="json"), agent.id)

    async def start(self, mission: Mission):
        async with self.lock:
            if mission.id in self.runs:
                raise PolicyError("Mission is already running")
            job = asyncio.create_task(self.run(mission))
            self.runs[mission.id] = job
            job.add_done_callback(lambda done: self.runs.pop(mission.id, None) if self.runs.get(mission.id) is done else None)

    async def model_call(self, mission: Mission, actor: AgentSpec, kind: str, call):
        self.check_stopped(mission.id)
        await self.emit(mission.id, "llm.started", {"kind": kind, "model": getattr(self.controller, "model", "demo"),
                        "reasoning_effort": getattr(self.controller, "reasoning", None)}, actor.id)
        try:
            response = await call()
        except ProviderError as exc:
            await self.emit(mission.id, "llm.failed", {
                "kind": kind, "model": getattr(self.controller, "model", "demo"),
                "failure_class": str(exc.failure_class), "error": str(exc),
            }, actor.id)
            raise
        self.check_stopped(mission.id)
        metadata = response.pop("_meta", None)
        if metadata:
            await self.emit(mission.id, "llm.completed", {"kind": kind, **metadata}, actor.id)
        return response

    async def run(self, mission: Mission):
        root = None
        try:
            self.check_stopped(mission.id)
            mission.status, mission.updated_at = MissionStatus.RUNNING, utcnow()
            self.store.save_mission(mission)
            await self.emit(mission.id, "mission.started", {"goal": mission.goal, "mode": self.controller.mode})
            async with asyncio.timeout(mission.limits.max_runtime_seconds):
                root = await self.spawn(mission, "mission_controller", "Delegate work, inspect results and deliver the mission.",
                                        capabilities=["spawn", "coordinate", "reason"])
                await self.agent_status(root, AgentStatus.RUNNING)
                for _ in range(mission.limits.max_agents * 2 + 2):
                    decision = await self.model_call(mission, root, "decision", lambda: self.controller.decide(self._state(mission)))
                    await self.emit(mission.id, "controller.decision", decision, root.id)
                    action = decision.get("action")
                    if action == "spawn":
                        if not decision.get("role") or not decision.get("purpose"):
                            raise PolicyError("Model omitted the new agent's role or purpose",
                                              FailureClass.INVALID_OUTPUT)
                        parent = root
                        if decision.get("parent_id"):
                            parent = next((a for a in self.agents[mission.id] if str(a.id) == decision["parent_id"]), None)
                            if parent is None:
                                raise PolicyError("Model selected an unknown parent agent",
                                                  FailureClass.INVALID_OUTPUT)
                        caps = decision.get("capabilities") or ["reason"]
                        if self.controller.mode != "demo" and set(caps) - {"reason", "write", "review"}:
                            raise PolicyError("Model requested an unavailable capability",
                                              FailureClass.CAPABILITY_MISMATCH)
                        child = await self.spawn(mission, decision["role"], decision["purpose"], parent, caps)
                        await self.emit(mission.id, "agent.message", {
                            "from_id": str(root.id), "to_id": str(child.id), "kind": "assignment",
                            "text": decision["purpose"]}, root.id)
                        await self._run_tasks(mission)
                    elif action == "finish":
                        if any(t.status in {TaskStatus.PENDING, TaskStatus.RUNNING} for t in self.tasks[mission.id]):
                            raise PolicyError("Cannot finish while tasks are active", FailureClass.INVALID_OUTPUT)
                        if not decision.get("summary"):
                            raise PolicyError("Model omitted the final deliverable", FailureClass.INVALID_OUTPUT)
                        mission.result = {"summary": decision["summary"], "mode": self.controller.mode,
                                          "outputs": [t.output for t in self.tasks[mission.id] if t.output]}
                        mission.status = MissionStatus.COMPLETED
                        break
                    elif action == "blocked":
                        mission.status = MissionStatus.BLOCKED
                        mission.result = {"reason": decision.get("reason") or "Required capability or information is unavailable"}
                        break
                    elif action == "wait":
                        raise PolicyError("Controller requested a wait with no work in flight",
                                          FailureClass.INVALID_OUTPUT)
                    else:
                        raise PolicyError("Model returned an unsupported controller action",
                                          FailureClass.INVALID_OUTPUT)
                else:
                    raise PolicyError("Controller iteration limit reached", FailureClass.RESOURCE_EXHAUSTED)
                if root:
                    await self.agent_status(root, AgentStatus.COMPLETED if mission.status == MissionStatus.COMPLETED else AgentStatus.BLOCKED)
        except asyncio.CancelledError:
            mission.status = MissionStatus.STOPPED
            mission.result = {"reason": "Execution stopped"}
        except TimeoutError:
            mission.status = MissionStatus.FAILED
            mission.result = failure_payload("Mission runtime limit reached", FailureClass.TIMEOUT)
        except (ProviderError, PolicyError) as exc:
            mission.status = MissionStatus.FAILED
            mission.result = failure_payload(str(exc), exc.failure_class)
        except Exception:
            mission.status = MissionStatus.FAILED
            mission.result = failure_payload("Unexpected runtime error", FailureClass.UNKNOWN_FAILURE)
        finally:
            for task in self.tasks[mission.id]:
                if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                    task.status = TaskStatus.STOPPED if mission.status == MissionStatus.STOPPED else TaskStatus.FAILED
                    await self.emit(mission.id, "task." + task.status, task.model_dump(mode="json"), task.agent_id)
            for agent in self.agents[mission.id]:
                if agent.status in {AgentStatus.CREATED, AgentStatus.RUNNING}:
                    status = AgentStatus.STOPPED if mission.status == MissionStatus.STOPPED else AgentStatus.FAILED
                    await self.agent_status(agent, status)
            mission.updated_at = utcnow()
            self.store.save_mission(mission)
            await self.emit(mission.id, "mission." + mission.status, mission.result or {})

    def _state(self, mission: Mission) -> dict[str, Any]:
        return {"goal": mission.goal, "status": mission.status,
                "agents": [a.model_dump(mode="json") for a in self.agents[mission.id]],
                "tasks": [t.model_dump(mode="json") for t in self.tasks[mission.id]],
                "limits": mission.limits.model_dump(mode="json"),
                "available_capabilities": ["reason", "write", "review"], "external_tools": []}

    async def _run_tasks(self, mission: Mission):
        assigned = {t.agent_id for t in self.tasks[mission.id]}
        for agent in list(self.agents[mission.id]):
            if agent.parent_id is None or agent.id in assigned:
                continue
            self.check_stopped(mission.id)
            if len(self.tasks[mission.id]) >= mission.limits.max_tasks:
                raise PolicyError("Task limit reached", FailureClass.RESOURCE_EXHAUSTED)
            task = Task(mission_id=mission.id, agent_id=agent.id, title=agent.role.replace("_", " ").title(),
                        description=agent.purpose, status=TaskStatus.RUNNING)
            self.tasks[mission.id].append(task)
            await self.agent_status(agent, AgentStatus.RUNNING)
            await self.emit(mission.id, "task.started", task.model_dump(mode="json"), agent.id)
            result = await self.model_call(mission, agent, "work",
                       lambda: self.controller.work(self._state(mission), agent.model_dump(mode="json")))
            if result.get("status") not in {"completed", "blocked"} or not result.get("finding"):
                raise PolicyError("Worker did not return a valid result", FailureClass.INVALID_OUTPUT)
            task.output = result
            task.status = TaskStatus.COMPLETED if result["status"] == "completed" else TaskStatus.BLOCKED
            agent.output = result
            await self.agent_status(agent, AgentStatus.COMPLETED if task.status == TaskStatus.COMPLETED else AgentStatus.BLOCKED)
            await self.emit(mission.id, "task." + task.status, task.model_dump(mode="json"), agent.id)
            root = self.agents[mission.id][0]
            await self.emit(mission.id, "agent.message", {
                "from_id": str(agent.id), "to_id": str(root.id), "kind": "result",
                "text": result["finding"][:500]}, agent.id)

    async def stop(self, mission_id: UUID):
        self.stopped.add(mission_id)
        job = self.runs.get(mission_id)
        if job and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        mission = self.store.get_mission(mission_id)
        if mission and mission.status not in TERMINAL:
            mission.status, mission.updated_at = MissionStatus.STOPPED, utcnow()
            self.store.save_mission(mission)
            await self.emit(mission_id, "mission.stopped", {"reason": "Execution stopped"})
        return mission

    async def stop_all(self) -> list[UUID]:
        async with self.lock:
            ids = list(self.runs)
            await asyncio.gather(*(self.stop(mid) for mid in ids))
        return ids

    async def create_payment(self, mission: Mission, recipient: str, amount: float, reason: str) -> PaymentIntent:
        if mission.id in self.stopped:
            raise PolicyError("Mission was stopped")
        if amount > mission.limits.max_payment_amount or mission.spent + amount > mission.budget:
            raise PolicyError("Payment exceeds mission budget or payment cap", FailureClass.RESOURCE_EXHAUSTED)
        intent = PaymentIntent(mission_id=mission.id, recipient=recipient, amount=amount, reason=reason)
        intent = await self.wallet.pay(intent, mission)
        mission.spent += amount
        mission.updated_at = utcnow()
        self.store.save_mission(mission)
        await self.emit(mission.id, "payment.created", intent.model_dump(mode="json"))
        return intent
