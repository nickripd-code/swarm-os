from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Awaitable, Callable
from uuid import UUID

from .models import (
    AgentSpec, AgentStatus, FailureClass, Mission, MissionEvent, MissionStatus,
    PaymentIntent, Task, TaskStatus, utcnow,
)
from .store import Store
from .llm import (
    DEFAULT_MAX_RETRIES, DEFAULT_RETRY_BASE_SECONDS, LLMProvider, build_controller,
    ProviderError, RETRYABLE_FAILURE_CLASSES, retry_delay_seconds,
)
from .verifier import public_verification, verification_accepted

TERMINAL = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.STOPPED, MissionStatus.BLOCKED}
RESUMABLE = {MissionStatus.PENDING, MissionStatus.RUNNING, MissionStatus.WAITING}


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
    def __init__(self, store: Store, sink: EventSink | None = None, controller: LLMProvider | None = None,
                 max_retries: int = DEFAULT_MAX_RETRIES, retry_base_seconds: float = DEFAULT_RETRY_BASE_SECONDS):
        self.store, self.sink = store, sink
        self.agents: dict[UUID, list[AgentSpec]] = defaultdict(list)
        self.tasks: dict[UUID, list[Task]] = defaultdict(list)
        self.stopped: set[UUID] = set()
        self.suspending: set[UUID] = set()
        self.started_at: dict[UUID, datetime] = {}
        self.runs: dict[UUID, asyncio.Task] = {}
        self.wallet = WalletAdapter()
        self.controller = controller or build_controller()
        self.lock = asyncio.Lock()
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self._tool_calls: dict[UUID, int] = {}
        self.external_tools: list[str] = []

    async def emit(self, mission_id: UUID, event_type: str, payload: dict[str, Any], actor_id: UUID | None = None):
        event = self.store.append(MissionEvent(mission_id=mission_id, event_type=event_type, actor_id=actor_id, payload=payload))
        if self.sink:
            await self.sink(event)

    async def _emit_planning(self, mission_id: UUID, actor_id: UUID | None):
        planning = getattr(self.controller, "last_planning", None)
        if not isinstance(planning, dict) or planning.get("mode") != "multi":
            return
        if planning.get("emitted"):
            return
        planning["emitted"] = True
        for proposal in planning.get("proposals") or []:
            await self.emit(mission_id, "planner.proposal", proposal, actor_id)
        judge = planning.get("judge")
        if judge:
            await self.emit(mission_id, "judge.decision", judge, actor_id)

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
        self.store.save_agent(agent)
        await self.emit(mission.id, "agent.spawned", agent.model_dump(mode="json"), agent.id)
        return agent

    async def agent_status(self, agent: AgentSpec, status: AgentStatus):
        agent.status = status
        self.store.save_agent(agent)
        await self.emit(agent.mission_id, "agent.updated", agent.model_dump(mode="json"), agent.id)

    def hydrate(self, mission_id: UUID) -> None:
        if self.agents[mission_id] or self.tasks[mission_id]:
            return
        projection = self.store.project(mission_id)
        agents = [AgentSpec.model_validate(item) for item in projection["agents"]]
        tasks = [Task.model_validate(item) for item in projection["tasks"]]
        for agent in agents:
            self.store.save_agent(agent)
        for task in tasks:
            self.store.save_task(task)
        self.agents[mission_id] = agents
        self.tasks[mission_id] = tasks

    async def resume_incomplete(self) -> list[UUID]:
        configured = getattr(self.controller, "configured", None)
        if callable(configured) and not configured():
            return []
        resumed: list[UUID] = []
        for mission in self.store.list_missions():
            if mission.status not in RESUMABLE:
                continue
            self.hydrate(mission.id)
            await self.start(mission)
            resumed.append(mission.id)
        return resumed

    async def start(self, mission: Mission):
        async with self.lock:
            if mission.id in self.runs:
                raise PolicyError("Mission is already running")
            job = asyncio.create_task(self.run(mission))
            self.runs[mission.id] = job
            job.add_done_callback(lambda done: self.runs.pop(mission.id, None) if self.runs.get(mission.id) is done else None)

    def remaining_runtime(self, mission: Mission) -> float:
        started = self.started_at.get(mission.id, mission.updated_at)
        return mission.limits.max_runtime_seconds - (utcnow() - started).total_seconds()

    def available_tools(self, mission: Mission | None = None) -> list[str]:
        _ = mission
        return list(self.external_tools)

    def tool_calls_used(self, mission_id: UUID) -> int:
        if mission_id not in self._tool_calls:
            self._tool_calls[mission_id] = sum(
                1 for event in self.store.events(mission_id) if event.event_type == "tool.started"
            )
        return self._tool_calls[mission_id]

    def consume_tool_call(self, mission: Mission) -> int:
        """Charge one tool-call against the mission budget. Fail closed when exhausted."""
        used = self.tool_calls_used(mission.id)
        limit = mission.limits.max_tool_calls
        if used >= limit:
            raise PolicyError("Tool call limit reached", FailureClass.RESOURCE_EXHAUSTED)
        used += 1
        self._tool_calls[mission.id] = used
        return used

    async def invoke_tool(self, mission: Mission, name: str, actor_id: UUID | None = None) -> int:
        """Enforce max_tool_calls before any tool use. No ToolProvider exists yet."""
        used = self.tool_calls_used(mission.id)
        limit = mission.limits.max_tool_calls
        available = self.available_tools(mission)
        if used >= limit:
            await self.emit(mission.id, "tool.failed", {
                "tool": name, "failure_class": str(FailureClass.RESOURCE_EXHAUSTED),
                "error": "Tool call limit reached", "used": used, "max": limit,
            }, actor_id)
            raise PolicyError("Tool call limit reached", FailureClass.RESOURCE_EXHAUSTED)
        if name not in available:
            error = "No tool provider is connected" if not available else f"Unknown tool: {name}"
            await self.emit(mission.id, "tool.failed", {
                "tool": name, "failure_class": str(FailureClass.TOOL_MISSING),
                "error": error, "used": used, "max": limit,
            }, actor_id)
            raise PolicyError(error, FailureClass.TOOL_MISSING)
        charged = self.consume_tool_call(mission)
        await self.emit(mission.id, "tool.started", {
            "tool": name, "used": charged, "max": limit,
        }, actor_id)
        return charged

    def _in_flight_tasks(self, mission: Mission) -> list[Task]:
        return [task for task in self.tasks[mission.id]
                if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}]

    async def _persist_status(self, mission: Mission, status: MissionStatus):
        mission.status, mission.updated_at = status, utcnow()
        self.store.save_mission(mission)

    async def _assign_unassigned_tasks(self, mission: Mission) -> list[Task]:
        assigned = {task.agent_id for task in self.tasks[mission.id]
                    if task.status not in {TaskStatus.STOPPED, TaskStatus.FAILED}}
        created: list[Task] = []
        for agent in list(self.agents[mission.id]):
            if agent.parent_id is None or agent.id in assigned:
                continue
            self.check_stopped(mission.id)
            if len(self.tasks[mission.id]) >= mission.limits.max_tasks:
                raise PolicyError("Task limit reached", FailureClass.RESOURCE_EXHAUSTED)
            task = Task(mission_id=mission.id, agent_id=agent.id, title=agent.role.replace("_", " ").title(),
                        description=agent.purpose, status=TaskStatus.PENDING)
            self.tasks[mission.id].append(task)
            self.store.save_task(task)
            await self.emit(mission.id, "task.pending", task.model_dump(mode="json"), agent.id)
            assigned.add(agent.id)
            created.append(task)
        return created

    async def _sleep(self, seconds: float):
        if seconds > 0:
            await asyncio.sleep(seconds)

    async def model_call(self, mission: Mission, actor: AgentSpec, kind: str, call):
        self.check_stopped(mission.id)
        model = getattr(self.controller, "model", "demo")
        await self.emit(mission.id, "llm.started", {"kind": kind, "model": model,
                        "reasoning_effort": getattr(self.controller, "reasoning", None)}, actor.id)
        attempts = self.max_retries + 1
        response = None
        for attempt in range(1, attempts + 1):
            self.check_stopped(mission.id)
            try:
                response = await call()
                break
            except ProviderError as exc:
                retryable = exc.failure_class in RETRYABLE_FAILURE_CLASSES and attempt < attempts
                delay = retry_delay_seconds(attempt, self.retry_base_seconds) if retryable else 0.0
                if retryable and self.remaining_runtime(mission) > delay:
                    await self.emit(mission.id, "llm.retry", {
                        "kind": kind, "model": model, "failure_class": str(exc.failure_class),
                        "error": str(exc), "attempt": attempt, "max_attempts": attempts,
                        "delay_seconds": delay,
                    }, actor.id)
                    await self._sleep(delay)
                    continue
                await self._emit_planning(mission.id, actor.id)
                await self.emit(mission.id, "llm.failed", {
                    "kind": kind, "model": model, "failure_class": str(exc.failure_class),
                    "error": str(exc), "attempt": attempt, "max_attempts": attempts,
                }, actor.id)
                raise
        self.check_stopped(mission.id)
        assert response is not None
        await self._emit_planning(mission.id, actor.id)
        metadata = response.pop("_meta", None)
        if metadata:
            if metadata.get("failover_from"):
                await self.emit(mission.id, "llm.failover", {
                    "kind": kind,
                    "from_provider": metadata["failover_from"],
                    "to_provider": metadata.get("provider"),
                    "reason": metadata.get("failover_reason"),
                    "model": metadata.get("model", model),
                }, actor.id)
            await self.emit(mission.id, "llm.completed", {"kind": kind, **metadata}, actor.id)
        return response

    async def run(self, mission: Mission):
        root = None
        suspended = False
        try:
            self.check_stopped(mission.id)
            self.hydrate(mission.id)
            existing = list(self.agents[mission.id])
            history = self.store.events(mission.id)
            started = next((event.created_at for event in history
                            if event.event_type in {"mission.started", "mission.resumed"}), None)
            execution_anchor = started or (mission.updated_at if existing else utcnow())
            mission.status, mission.updated_at = MissionStatus.RUNNING, utcnow()
            self.started_at[mission.id] = execution_anchor
            self.store.save_mission(mission)
            remaining = self.remaining_runtime(mission)
            if remaining <= 0:
                raise TimeoutError("Mission runtime limit reached before recovery")
            async with asyncio.timeout(remaining):
                if existing:
                    root = next((a for a in existing if a.parent_id is None), existing[0])
                    await self.emit(mission.id, "mission.resumed", {
                        "goal": mission.goal, "mode": self.controller.mode,
                        "agents": len(existing), "tasks": len(self.tasks[mission.id]),
                    })
                    interrupted_agents: set[UUID] = set()
                    for task in self.tasks[mission.id]:
                        if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                            continue
                        task.status = TaskStatus.STOPPED
                        self.store.save_task(task)
                        interrupted_agents.add(task.agent_id)
                        payload = task.model_dump(mode="json")
                        payload["reason"] = "Interrupted by process restart; a new safe attempt will be created"
                        await self.emit(mission.id, "task.stopped", payload, task.agent_id)
                    for agent in existing:
                        if agent.id in interrupted_agents:
                            agent.status = AgentStatus.CREATED
                            agent.output = None
                            await self.agent_status(agent, AgentStatus.CREATED)
                    if root.status in {AgentStatus.CREATED, AgentStatus.RUNNING, AgentStatus.BLOCKED}:
                        await self.agent_status(root, AgentStatus.RUNNING)
                    await self._run_tasks(mission)
                else:
                    await self.emit(mission.id, "mission.started", {"goal": mission.goal, "mode": self.controller.mode})
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
                        await self._assign_unassigned_tasks(mission)
                    elif action == "finish":
                        if self._in_flight_tasks(mission):
                            raise PolicyError("Cannot finish while tasks are active", FailureClass.INVALID_OUTPUT)
                        if not decision.get("summary"):
                            raise PolicyError("Model omitted the final deliverable", FailureClass.INVALID_OUTPUT)
                        claim = {"summary": decision["summary"], "mode": self.controller.mode,
                                 "outputs": [t.output for t in self.tasks[mission.id] if t.output]}
                        await self._verify_finish(mission, root, claim)
                        mission.result = claim
                        mission.status = MissionStatus.COMPLETED
                        break
                    elif action == "blocked":
                        mission.status = MissionStatus.BLOCKED
                        mission.result = {"reason": decision.get("reason") or "Required capability or information is unavailable"}
                        break
                    elif action == "wait":
                        await self._assign_unassigned_tasks(mission)
                        inflight = self._in_flight_tasks(mission)
                        if not inflight:
                            raise PolicyError("Controller requested a wait with no work in flight",
                                              FailureClass.INVALID_OUTPUT)
                        await self._persist_status(mission, MissionStatus.WAITING)
                        await self.emit(mission.id, "mission.waiting", {
                            "reason": decision.get("reason") or "Waiting for in-flight work",
                            "pending_tasks": [str(task.id) for task in inflight],
                        }, root.id)
                        await self._run_tasks(mission)
                        if mission.id in self.stopped or mission.id in self.suspending:
                            raise asyncio.CancelledError()
                        await self._persist_status(mission, MissionStatus.RUNNING)
                        await self.emit(mission.id, "mission.running", {
                            "reason": "In-flight work finished; controller will continue",
                        }, root.id)
                    else:
                        raise PolicyError("Model returned an unsupported controller action",
                                          FailureClass.INVALID_OUTPUT)
                else:
                    raise PolicyError("Controller iteration limit reached", FailureClass.RESOURCE_EXHAUSTED)
                if root:
                    await self.agent_status(root, AgentStatus.COMPLETED if mission.status == MissionStatus.COMPLETED else AgentStatus.BLOCKED)
        except asyncio.CancelledError:
            if mission.id in self.suspending:
                suspended = True
                mission.status = MissionStatus.RUNNING
                mission.result = None
            else:
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
            if suspended:
                self.store.save_mission(mission)
                await self.emit(mission.id, "mission.suspended", {
                    "reason": "Runtime is shutting down; unfinished work remains recoverable",
                    "mode": self.controller.mode,
                })
                self.suspending.discard(mission.id)
            else:
                for task in self.tasks[mission.id]:
                    if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                        task.status = TaskStatus.STOPPED if mission.status == MissionStatus.STOPPED else TaskStatus.FAILED
                        self.store.save_task(task)
                        await self.emit(mission.id, "task." + task.status, task.model_dump(mode="json"), task.agent_id)
                for agent in self.agents[mission.id]:
                    if agent.status in {AgentStatus.CREATED, AgentStatus.RUNNING}:
                        status = AgentStatus.STOPPED if mission.status == MissionStatus.STOPPED else AgentStatus.FAILED
                        await self.agent_status(agent, status)
                mission.updated_at = utcnow()
                self.store.save_mission(mission)
                await self.emit(mission.id, "mission." + mission.status, mission.result or {})

    async def _verify_finish(self, mission: Mission, root: AgentSpec, claim: dict[str, Any]):
        """Controller finish is a claim. Complete only after a real verifier accepts it."""
        await self.emit(mission.id, "verification.started", {
            "summary": str(claim.get("summary") or "")[:500],
            "outputs": len(claim.get("outputs") or []),
        }, root.id)
        try:
            result = await self.model_call(
                mission, root, "verification",
                lambda: self.controller.verify(self._state(mission), claim),
            )
        except (ProviderError, PolicyError) as exc:
            await self.emit(mission.id, "verification.failed", {
                "verdict": "inconclusive",
                "rationale": str(exc),
                "failure_class": str(exc.failure_class),
            }, root.id)
            if isinstance(exc, ProviderError) and exc.failure_class in {
                FailureClass.INVALID_OUTPUT, FailureClass.VERIFICATION_FAILURE,
            }:
                raise PolicyError(
                    "Verification was inconclusive; the claimed result was not accepted",
                    FailureClass.VERIFICATION_FAILURE,
                ) from exc
            raise
        public = public_verification(result)
        if not verification_accepted(public):
            await self.emit(mission.id, "verification.failed", {
                **public,
                "failure_class": str(FailureClass.VERIFICATION_FAILURE),
            }, root.id)
            raise PolicyError(
                public.get("rationale") or "Verification did not accept the claimed result",
                FailureClass.VERIFICATION_FAILURE,
            )
        await self.emit(mission.id, "verification.passed", public, root.id)

    def _state(self, mission: Mission) -> dict[str, Any]:
        used = self.tool_calls_used(mission.id)
        return {"goal": mission.goal, "status": mission.status,
                "agents": [a.model_dump(mode="json") for a in self.agents[mission.id]],
                "tasks": [t.model_dump(mode="json") for t in self.tasks[mission.id]],
                "limits": mission.limits.model_dump(mode="json"),
                "tool_calls": {"used": used, "max": mission.limits.max_tool_calls},
                "available_capabilities": ["reason", "write", "review"],
                "external_tools": self.available_tools(mission)}

    async def _execute_task(self, mission: Mission, task: Task, agent: AgentSpec):
        self.check_stopped(mission.id)
        task.status = TaskStatus.RUNNING
        self.store.save_task(task)
        await self.agent_status(agent, AgentStatus.RUNNING)
        await self.emit(mission.id, "task.started", task.model_dump(mode="json"), agent.id)
        result = await self.model_call(mission, agent, "work",
                   lambda: self.controller.work(self._state(mission), agent.model_dump(mode="json")))
        if result.get("status") not in {"completed", "blocked"} or not result.get("finding"):
            raise PolicyError("Worker did not return a valid result", FailureClass.INVALID_OUTPUT)
        task.output = result
        task.status = TaskStatus.COMPLETED if result["status"] == "completed" else TaskStatus.BLOCKED
        agent.output = result
        self.store.save_task(task)
        await self.agent_status(agent, AgentStatus.COMPLETED if task.status == TaskStatus.COMPLETED else AgentStatus.BLOCKED)
        await self.emit(mission.id, "task." + task.status, task.model_dump(mode="json"), agent.id)
        root = self.agents[mission.id][0]
        await self.emit(mission.id, "agent.message", {
            "from_id": str(agent.id), "to_id": str(root.id), "kind": "result",
            "text": result["finding"][:500]}, agent.id)

    async def _run_tasks(self, mission: Mission):
        await self._assign_unassigned_tasks(mission)
        by_id = {a.id: a for a in self.agents[mission.id]}
        for task in list(self.tasks[mission.id]):
            if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                continue
            agent = by_id.get(task.agent_id)
            if agent is None:
                raise PolicyError("Persisted task references an unknown agent", FailureClass.INVALID_OUTPUT)
            await self._execute_task(mission, task, agent)

    async def stop(self, mission_id: UUID):
        self.stopped.add(mission_id)
        job = self.runs.get(mission_id)
        if job and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            return self.store.get_mission(mission_id)
        self.hydrate(mission_id)
        for task in self.tasks[mission_id]:
            if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                task.status = TaskStatus.STOPPED
                self.store.save_task(task)
                await self.emit(mission_id, "task.stopped", task.model_dump(mode="json"), task.agent_id)
        for agent in self.agents[mission_id]:
            if agent.status in {AgentStatus.CREATED, AgentStatus.RUNNING}:
                await self.agent_status(agent, AgentStatus.STOPPED)
        mission = self.store.get_mission(mission_id)
        if mission and mission.status not in TERMINAL:
            mission.status, mission.updated_at = MissionStatus.STOPPED, utcnow()
            self.store.save_mission(mission)
            await self.emit(mission_id, "mission.stopped", {"reason": "Execution stopped"})
        return mission

    async def stop_all(self) -> list[UUID]:
        async with self.lock:
            ids = list(dict.fromkeys([
                *(mid for mid, job in self.runs.items() if not job.done()),
                *(mission.id for mission in self.store.list_missions()
                  if mission.status in RESUMABLE),
            ]))
            await asyncio.gather(*(self.stop(mid) for mid in ids))
        return ids

    async def suspend_all(self) -> list[UUID]:
        """Cancel local jobs during shutdown without turning a restart into user STOP."""
        async with self.lock:
            ids = [mid for mid, job in self.runs.items() if not job.done()]
            self.suspending.update(ids)
            jobs = [self.runs[mid] for mid in ids]
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
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
