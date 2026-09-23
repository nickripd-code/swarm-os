from __future__ import annotations

from typing import Any, Iterable, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .events import EventType
from .models import AgentSpec, AgentStatus, FailureClass, Mission, Task, TaskStatus
from .policy import PolicyError, PolicyGate, PolicyRequest

ORG_OPS = frozenset({"spawn", "replace", "reparent", "retire"})
CONTROLLER_ROLE = "mission_controller"
IN_FLIGHT = {TaskStatus.PENDING, TaskStatus.RUNNING}


class OrgChange(BaseModel):
    op: Literal["spawn", "replace", "reparent", "retire"]
    agent_id: str | None = None
    parent_id: str | None = None
    role: str | None = None
    purpose: str | None = None
    capabilities: list[str] = Field(default_factory=list)


def is_org_action(action: str | None) -> bool:
    return action in ORG_OPS


def topology_snapshot(agents: Iterable[AgentSpec]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(agent.id),
            "parent_id": str(agent.parent_id) if agent.parent_id else None,
            "role": agent.role,
            "status": str(agent.status),
            "depth": agent.depth,
        }
        for agent in agents
    ]


def _optional_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find(agents: Iterable[AgentSpec], agent_id: str | UUID | None) -> AgentSpec | None:
    target = _optional_id(agent_id)
    if not target:
        return None
    return next((agent for agent in agents if str(agent.id) == target), None)


def _is_controller(agent: AgentSpec) -> bool:
    return agent.parent_id is None or agent.role == CONTROLLER_ROLE


def _controller(agents: list[AgentSpec]) -> AgentSpec | None:
    return next((agent for agent in agents if agent.parent_id is None), None) or (
        next((agent for agent in agents if agent.role == CONTROLLER_ROLE), None)
    )


def _children_map(agents: list[AgentSpec]) -> dict[UUID | None, list[AgentSpec]]:
    grouped: dict[UUID | None, list[AgentSpec]] = {}
    for agent in agents:
        grouped.setdefault(agent.parent_id, []).append(agent)
    return grouped


def _descendants(agents: list[AgentSpec], root: AgentSpec) -> list[AgentSpec]:
    grouped = _children_map(agents)
    found: list[AgentSpec] = []
    stack = list(grouped.get(root.id, []))
    while stack:
        node = stack.pop()
        found.append(node)
        stack.extend(grouped.get(node.id, []))
    return found


def _height(agent: AgentSpec, grouped: dict[UUID | None, list[AgentSpec]]) -> int:
    kids = grouped.get(agent.id, [])
    if not kids:
        return 0
    return 1 + max(_height(child, grouped) for child in kids)


def _in_flight(tasks: list[Task], agent: AgentSpec) -> list[Task]:
    return [task for task in tasks if task.agent_id == agent.id and task.status in IN_FLIGHT]


class OrganizationDesigner:
    """Propose and apply org topology changes. Fail closed; never invents success."""

    def propose(self, decision: dict[str, Any], agents: list[AgentSpec] | None = None) -> OrgChange | None:
        del agents
        if not isinstance(decision, dict):
            raise PolicyError("Org decision must be an object", FailureClass.INVALID_OUTPUT)
        extra = decision.get("org_changes")
        if extra not in (None, [], ()):
            raise PolicyError(
                "org_changes batches are not applied in this seed; use action spawn, replace, reparent, or retire",
                FailureClass.INVALID_OUTPUT,
            )
        action = decision.get("action")
        if action not in ORG_OPS:
            return None
        change = OrgChange(
            op=action,
            agent_id=_optional_id(decision.get("agent_id")),
            parent_id=_optional_id(decision.get("parent_id")),
            role=(str(decision["role"]).strip() if decision.get("role") else None),
            purpose=(str(decision["purpose"]).strip() if decision.get("purpose") else None),
            capabilities=list(decision.get("capabilities") or []),
        )
        if change.op in {"replace", "reparent", "retire"} and not change.agent_id:
            raise PolicyError(f"{change.op} omitted agent_id", FailureClass.INVALID_OUTPUT)
        if change.op in {"spawn", "replace"} and (not change.role or not change.purpose):
            raise PolicyError("Model omitted the new agent's role or purpose", FailureClass.INVALID_OUTPUT)
        return change

    def validate(
        self,
        change: OrgChange,
        mission: Mission,
        agents: list[AgentSpec],
        tasks: list[Task],
        *,
        mode: str = "openai",
    ) -> AgentSpec | None:
        if change.op not in ORG_OPS:
            raise PolicyError("Unknown organization operation", FailureClass.INVALID_OUTPUT)
        if change.op == "spawn":
            parent = self._resolve_parent(agents, change.parent_id, required=False)
            self._authorize_spawn(mission, agents, parent, change.capabilities, mode=mode, vacated=0)
            return parent
        target = _find(agents, change.agent_id)
        if target is None:
            raise PolicyError("Model selected an unknown agent", FailureClass.INVALID_OUTPUT)
        if _is_controller(target):
            raise PolicyError("Cannot reorganize the mission controller", FailureClass.POLICY_REFUSAL)
        if change.op == "retire":
            self._validate_retire(target, agents, tasks)
            return target
        if change.op == "reparent":
            parent = self._resolve_parent(agents, change.parent_id, required=True)
            self._validate_reparent(mission, agents, target, parent)
            return parent
        parent = self._resolve_parent(agents, change.parent_id, required=False) or _find(
            agents, target.parent_id
        )
        if parent is None:
            raise PolicyError("Model selected an unknown parent agent", FailureClass.INVALID_OUTPUT)
        self._validate_retire(target, agents, tasks, allow_live_children=True)
        self._authorize_spawn(mission, agents, parent, change.capabilities, mode=mode, vacated=1)
        grouped = _children_map(agents)
        replacement_depth = parent.depth + 1
        child_height = _height(target, grouped)
        if child_height and replacement_depth + child_height > mission.limits.max_depth:
            raise PolicyError("Agent spawning limit reached", FailureClass.RESOURCE_EXHAUSTED)
        return parent

    async def apply(self, runtime: Any, mission: Mission, root: AgentSpec, change: OrgChange) -> AgentSpec | None:
        runtime.check_stopped(mission.id)
        agents = runtime.agents[mission.id]
        tasks = runtime.tasks[mission.id]
        mode = getattr(runtime.controller, "mode", "openai")
        parent = self.validate(change, mission, agents, tasks, mode=mode)
        await self._enforce_org_approval(runtime, mission, root, change, mode=mode)
        parent = self.validate(change, mission, agents, tasks, mode=mode)
        if change.op == "spawn":
            child = await self._spawn(runtime, mission, parent, change)
            await self._emit_changed(runtime, mission, root, change, agent=child, parent=parent)
            return child
        target = _find(agents, change.agent_id)
        if target is None:
            raise PolicyError("Model selected an unknown agent", FailureClass.INVALID_OUTPUT)
        if change.op == "retire":
            await self._retire(runtime, target)
            await self._emit_changed(runtime, mission, root, change, agent=target)
            return target
        if change.op == "reparent":
            if parent is None:
                raise PolicyError("Model selected an unknown parent agent", FailureClass.INVALID_OUTPUT)
            await self._reparent(runtime, agents, target, parent)
            await self._emit_changed(runtime, mission, root, change, agent=target, parent=parent)
            return target
        if parent is None:
            raise PolicyError("Model selected an unknown parent agent", FailureClass.INVALID_OUTPUT)
        children = [agent for agent in agents if agent.parent_id == target.id]
        await self._retire(runtime, target)
        replacement = await self._spawn(runtime, mission, parent, change)
        for child in children:
            await self._reparent(runtime, agents, child, replacement)
        await self._emit_changed(runtime, mission, root, change, agent=replacement, parent=parent,
                                 replaced_id=str(target.id))
        return replacement

    async def _enforce_org_approval(
        self,
        runtime: Any,
        mission: Mission,
        root: AgentSpec,
        change: OrgChange,
        *,
        mode: str,
    ) -> None:
        """Park replace/reparent/retire on the runtime approval path. Spawn is not gated."""
        gate = getattr(runtime, "policy", None) or PolicyGate()
        request = PolicyRequest(
            action="org_change",
            mission=mission,
            org_op=change.op,
            org_agent_id=change.agent_id,
            mode=mode,
        )
        gate.authorize(request)
        enforce = getattr(runtime, "_enforce_human_approval", None)
        if enforce is None:
            needed = gate.approval_required(request)
            if needed is not None:
                raise PolicyError(needed.reason, FailureClass.AUTHORIZATION_REQUIRED)
            return
        await enforce(mission, root, request)

    def _resolve_parent(self, agents: list[AgentSpec], parent_id: str | None, *, required: bool) -> AgentSpec | None:
        if not parent_id:
            parent = _controller(agents)
            if parent is None and required:
                raise PolicyError("Model selected an unknown parent agent", FailureClass.INVALID_OUTPUT)
            return parent
        parent = _find(agents, parent_id)
        if parent is None:
            raise PolicyError("Model selected an unknown parent agent", FailureClass.INVALID_OUTPUT)
        if parent.status == AgentStatus.STOPPED:
            raise PolicyError("Cannot attach a specialist to a retired agent", FailureClass.INVALID_OUTPUT)
        return parent

    def _authorize_spawn(
        self,
        mission: Mission,
        agents: list[AgentSpec],
        parent: AgentSpec | None,
        capabilities: list[str],
        *,
        mode: str,
        vacated: int,
    ) -> None:
        depth = parent.depth + 1 if parent else 0
        live = [agent for agent in agents if agent.status != AgentStatus.STOPPED]
        PolicyGate().authorize(PolicyRequest(
            action="spawn",
            mission=mission,
            agent_count=max(len(live) - vacated, 0),
            depth=depth,
            capabilities=tuple(capabilities or []),
            mode=mode,
            parent_ok=not parent or parent.mission_id == mission.id,
        ))

    def _validate_retire(
        self,
        target: AgentSpec,
        agents: list[AgentSpec],
        tasks: list[Task],
        *,
        allow_live_children: bool = False,
    ) -> None:
        if target.status == AgentStatus.STOPPED:
            raise PolicyError("Agent is already retired", FailureClass.INVALID_OUTPUT)
        if _in_flight(tasks, target):
            raise PolicyError("Cannot retire a specialist with in-flight work", FailureClass.INVALID_OUTPUT)
        if allow_live_children:
            return
        leftover = [agent for agent in _descendants(agents, target) if agent.status != AgentStatus.STOPPED]
        if leftover:
            raise PolicyError(
                "Cannot retire a specialist that still has live descendants; reparent them first",
                FailureClass.INVALID_OUTPUT,
            )

    def _validate_reparent(
        self,
        mission: Mission,
        agents: list[AgentSpec],
        target: AgentSpec,
        parent: AgentSpec,
    ) -> None:
        if str(parent.id) == str(target.id):
            raise PolicyError("Cannot reparent an agent to itself", FailureClass.INVALID_OUTPUT)
        if any(str(node.id) == str(parent.id) for node in _descendants(agents, target)):
            raise PolicyError("Reparent would create a cycle", FailureClass.INVALID_OUTPUT)
        grouped = _children_map(agents)
        new_depth = parent.depth + 1
        if new_depth + _height(target, grouped) > mission.limits.max_depth:
            raise PolicyError("Agent spawning limit reached", FailureClass.RESOURCE_EXHAUSTED)

    async def _spawn(self, runtime: Any, mission: Mission, parent: AgentSpec | None, change: OrgChange) -> AgentSpec:
        caps = list(change.capabilities) or ["reason"]
        return await runtime.spawn(mission, change.role, change.purpose, parent, caps)

    async def _retire(self, runtime: Any, agent: AgentSpec) -> None:
        await runtime.agent_status(agent, AgentStatus.STOPPED)
        payload = agent.model_dump(mode="json")
        payload["agent_id"] = str(agent.id)
        payload["reason"] = "retired"
        await runtime.emit(agent.mission_id, EventType.AGENT_RETIRED, payload, agent.id)

    async def _reparent(
        self,
        runtime: Any,
        agents: list[AgentSpec],
        agent: AgentSpec,
        parent: AgentSpec,
    ) -> None:
        previous = str(agent.parent_id) if agent.parent_id else None
        grouped = _children_map(agents)
        agent.parent_id = parent.id
        await self._apply_depth(runtime, agent, parent.depth + 1, grouped)
        payload = {
            "id": str(agent.id),
            "agent_id": str(agent.id),
            "parent_id": str(parent.id),
            "previous_parent_id": previous,
            "depth": agent.depth,
            "role": agent.role,
        }
        await runtime.emit(agent.mission_id, EventType.AGENT_REPARENTED, payload, agent.id)
        await runtime.agent_status(agent, agent.status)

    async def _apply_depth(
        self,
        runtime: Any,
        agent: AgentSpec,
        depth: int,
        grouped: dict[UUID | None, list[AgentSpec]],
    ) -> None:
        if agent.depth != depth:
            agent.depth = depth
            runtime.store.save_agent(agent)
        for child in grouped.get(agent.id, []):
            await self._apply_depth(runtime, child, depth + 1, grouped)
            await runtime.agent_status(child, child.status)

    async def _emit_changed(
        self,
        runtime: Any,
        mission: Mission,
        root: AgentSpec,
        change: OrgChange,
        *,
        agent: AgentSpec,
        parent: AgentSpec | None = None,
        replaced_id: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "op": change.op,
            "agent_id": str(agent.id),
            "parent_id": str(parent.id) if parent else (str(agent.parent_id) if agent.parent_id else None),
            "role": agent.role,
            "topology": topology_snapshot(runtime.agents[mission.id]),
        }
        if replaced_id:
            payload["replaced_id"] = replaced_id
        await runtime.emit(mission.id, EventType.ORG_CHANGED, payload, root.id)
