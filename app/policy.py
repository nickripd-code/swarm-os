from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import FailureClass, Mission

PolicyAction = Literal["spawn", "finish", "tool_use"]
PrivacyMode = Literal["cloud_allowed", "local_only"]

SAFE_SPECIALIST_CAPABILITIES = frozenset({"reason", "write", "review"})
CONTROLLER_CAPABILITIES = frozenset({"spawn", "coordinate", "reason"})
DEMO_CAPABILITIES = frozenset({"project_work", "report"})

# Deny-by-default classes. No ToolProvider is connected; these stay refused even if listed.
DANGEROUS_TOOLS = frozenset({
    "shell", "bash", "sh", "exec", "code_exec", "code_execution",
    "filesystem", "write_file", "read_file", "fs.write",
    "browser", "playwright", "computer_use",
    "network", "http", "fetch", "web.search",
    "payment", "wallet", "stripe", "live_payment",
    "credential", "secrets",
    "self_modify", "deploy", "ssh",
})
DANGEROUS_PREFIXES = (
    "shell.", "bash.", "fs.", "file.", "browser.", "http.", "net.",
    "pay.", "wallet.", "secret.", "deploy.", "ssh.",
)
CLOUD_EXFIL_TOOLS = frozenset({
    "browser", "playwright", "computer_use", "network", "http", "fetch",
    "web.search", "payment", "wallet", "stripe", "live_payment",
})


class PolicyError(Exception):
    def __init__(self, message: str, failure_class: FailureClass = FailureClass.POLICY_REFUSAL):
        super().__init__(message)
        self.failure_class = failure_class


@dataclass(frozen=True)
class PolicyRequest:
    action: PolicyAction
    mission: Mission
    agent_count: int = 0
    depth: int = 0
    tool_calls_used: int = 0
    in_flight_tasks: int = 0
    capabilities: tuple[str, ...] = ()
    tool: str | None = None
    summary: str | None = None
    mode: str = "openai"
    parent_ok: bool = True


def mission_privacy(mission: Mission) -> PrivacyMode:
    privacy = getattr(mission, "privacy", "cloud_allowed")
    return "local_only" if privacy == "local_only" else "cloud_allowed"


def privacy_from_state(state: dict | None) -> PrivacyMode:
    if (state or {}).get("privacy") == "local_only":
        return "local_only"
    return "cloud_allowed"


def tool_is_dangerous(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in DANGEROUS_TOOLS:
        return True
    return any(lowered.startswith(prefix) for prefix in DANGEROUS_PREFIXES)


def tool_exfiltrates(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in CLOUD_EXFIL_TOOLS:
        return True
    return any(lowered.startswith(prefix) for prefix in ("browser.", "http.", "net.", "pay.", "wallet."))


class PolicyGate:
    """Authorization outside the LLM. Unknown or dangerous acts fail closed."""

    def authorize(self, request: PolicyRequest) -> None:
        if request.action == "spawn":
            self._authorize_spawn(request)
            return
        if request.action == "finish":
            self._authorize_finish(request)
            return
        if request.action == "tool_use":
            self._authorize_tool(request)
            return
        raise PolicyError(f"Unknown policy action: {request.action}", FailureClass.POLICY_REFUSAL)

    def check_tool_budget(self, mission: Mission, used: int) -> None:
        if used >= mission.limits.max_tool_calls:
            raise PolicyError("Tool call limit reached", FailureClass.RESOURCE_EXHAUSTED)

    def _authorize_spawn(self, request: PolicyRequest) -> None:
        if not request.parent_ok:
            raise PolicyError("Parent must belong to this mission")
        limits = request.mission.limits
        if request.depth > limits.max_depth or request.agent_count >= limits.max_agents:
            raise PolicyError("Agent spawning limit reached", FailureClass.RESOURCE_EXHAUSTED)
        allowed = set(SAFE_SPECIALIST_CAPABILITIES) | set(CONTROLLER_CAPABILITIES)
        if request.mode == "demo":
            allowed |= set(DEMO_CAPABILITIES)
        unknown = set(request.capabilities) - allowed
        if unknown:
            raise PolicyError("Model requested an unavailable capability", FailureClass.CAPABILITY_MISMATCH)

    def _authorize_finish(self, request: PolicyRequest) -> None:
        if request.in_flight_tasks:
            raise PolicyError("Cannot finish while tasks are active", FailureClass.INVALID_OUTPUT)
        if not (request.summary or "").strip():
            raise PolicyError("Model omitted the final deliverable", FailureClass.INVALID_OUTPUT)

    def _authorize_tool(self, request: PolicyRequest) -> None:
        self.check_tool_budget(request.mission, request.tool_calls_used)
        name = (request.tool or "").strip()
        if not name:
            raise PolicyError("Tool use omitted a tool name", FailureClass.POLICY_REFUSAL)
        if mission_privacy(request.mission) == "local_only" and tool_exfiltrates(name):
            raise PolicyError("local_only policy forbids cloud or network tools", FailureClass.POLICY_REFUSAL)
        if tool_is_dangerous(name):
            raise PolicyError(f"Tool '{name}' is denied by default", FailureClass.POLICY_REFUSAL)
