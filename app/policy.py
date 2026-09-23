from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

from .models import FailureClass, Mission

PolicyAction = Literal["spawn", "finish", "tool_use", "org_change", "live_payment"]
PrivacyMode = Literal["cloud_allowed", "local_only"]
ApprovalVerdict = Literal["approve", "deny"]

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
    "pay.", "wallet.", "secret.", "deploy.", "ssh.", "selfmod.", "self_modify.",
    "composio.",
)
CLOUD_EXFIL_TOOLS = frozenset({
    "browser", "playwright", "computer_use", "network", "http", "fetch",
    "web.search", "payment", "wallet", "stripe", "live_payment",
})
# Operator-opted Playwright tools. Still denied unless SWARM_BROWSER is set.
OPTED_IN_BROWSER_TOOLS = frozenset({
    "browser.navigate", "browser.snapshot", "browser.click",
})
# Operator-opted self-mod tools. Propose/diff need SWARM_SELFMOD; apply also needs WRITE.
OPTED_IN_SELFMOD_DIFF_TOOLS = frozenset({"selfmod.propose", "selfmod.diff"})
OPTED_IN_SELFMOD_WRITE_TOOLS = frozenset({"selfmod.apply"})
TRUE_ENV = frozenset({"1", "true", "yes", "on"})
IRREVERSIBLE_ORG_OPS = frozenset({"replace", "reparent", "retire"})
APPROVE_TOKENS = frozenset({"approve", "approved", "yes", "allow"})
DENY_TOKENS = frozenset({"deny", "denied", "no", "reject", "refuse"})
_APPROVAL_TOKEN_RE = re.compile(r"[^a-z]+")


class PolicyError(Exception):
    def __init__(self, message: str, failure_class: FailureClass = FailureClass.POLICY_REFUSAL):
        super().__init__(message)
        self.failure_class = failure_class


@dataclass(frozen=True)
class ApprovalRequirement:
    """PolicyGate mark that the runtime must park WAITING until a matching approve/deny."""

    action: PolicyAction
    question: str
    reason: str
    org_op: str | None = None
    scope: str | None = None


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
    org_op: str | None = None


def parse_approval_answer(text: str) -> ApprovalVerdict | None:
    """Map a human answer to approve/deny. Anything else is undecided (fail closed)."""
    token = _APPROVAL_TOKEN_RE.split((text or "").strip().lower(), maxsplit=1)[0]
    if token in APPROVE_TOKENS:
        return "approve"
    if token in DENY_TOKENS:
        return "deny"
    return None


def interpret_approval(text: str) -> None:
    """Resume only after an explicit approve. Deny and ambiguous answers fail closed."""
    verdict = parse_approval_answer(text)
    if verdict == "approve":
        return
    if verdict == "deny":
        raise PolicyError("Human denied the action", FailureClass.POLICY_REFUSAL)
    raise PolicyError(
        "Human approval is required; answer must be approve or deny",
        FailureClass.AUTHORIZATION_REQUIRED,
    )


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
    return any(lowered.startswith(prefix) for prefix in (
        "browser.", "http.", "net.", "pay.", "wallet.", "composio.",
    ))


def browser_capability_enabled() -> bool:
    return os.getenv("SWARM_BROWSER", "").strip().lower() in TRUE_ENV


def tool_is_opted_in_browser(name: str) -> bool:
    return name.strip().lower() in OPTED_IN_BROWSER_TOOLS and browser_capability_enabled()


def selfmod_capability_enabled() -> bool:
    return os.getenv("SWARM_SELFMOD", "").strip().lower() in TRUE_ENV


def selfmod_write_enabled() -> bool:
    return selfmod_capability_enabled() and os.getenv("SWARM_SELFMOD_WRITE", "").strip().lower() in TRUE_ENV


def tool_is_opted_in_selfmod(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in OPTED_IN_SELFMOD_DIFF_TOOLS:
        return selfmod_capability_enabled()
    if lowered in OPTED_IN_SELFMOD_WRITE_TOOLS:
        return selfmod_write_enabled()
    return False


def tool_is_opted_in_composio(name: str) -> bool:
    return name.strip().lower().startswith("composio.") and bool(os.getenv("COMPOSIO_API_KEY", "").strip())


_COMPOSIO_META_SLUGS = frozenset({"search_tools", "authorize"})
_COMPOSIO_READ_VERBS = frozenset({
    "GET", "LIST", "FETCH", "SEARCH", "FIND", "READ", "DOWNLOAD",
    "RETRIEVE", "CHECK", "COUNT", "VIEW", "DESCRIBE", "LOOKUP", "QUERY",
})
_COMPOSIO_WRITE_VERBS = frozenset({
    "CREATE", "UPDATE", "DELETE", "REMOVE", "ADD", "SEND", "POST",
    "PATCH", "PUT", "MERGE", "CLOSE", "REOPEN", "ARCHIVE", "UNARCHIVE",
    "INVITE", "ASSIGN", "SUBMIT", "PUBLISH", "UPLOAD", "WRITE", "EDIT",
    "MODIFY", "SET", "ENABLE", "DISABLE", "REVOKE", "APPROVE", "REJECT",
    "STAR", "UNSTAR", "FORK", "COMMENT", "REPLY", "LOCK", "UNLOCK",
    "PIN", "UNPIN", "TRANSFER", "RENAME", "MOVE", "COPY", "DUPLICATE",
    "TRIGGER", "EXECUTE", "RUN", "DEPLOY", "CANCEL", "ABORT", "INSERT",
    "UPSERT", "DESTROY", "DROP", "PURGE", "OPEN", "RESOLVE",
})
_COMPOSIO_TOOLKIT_RE = re.compile(r"^[a-z0-9_-]{1,80}$")
_COMPOSIO_SLUG_RE = re.compile(r"^[A-Z0-9_-]{1,200}$")


def parse_composio_write_allowlist(raw: str | None = None) -> frozenset[tuple[str, str]]:
    """Parse `toolkit:ACTION` grants. Malformed entries grant nothing."""
    if raw is None:
        raw = os.getenv("COMPOSIO_WRITE_ALLOWLIST", "")
    grants: set[tuple[str, str]] = set()
    for item in (raw or "").split(","):
        piece = item.strip()
        if not piece or ":" not in piece:
            continue
        toolkit, action = piece.split(":", 1)
        toolkit = toolkit.strip().lower()
        action = action.strip().upper()
        if _COMPOSIO_TOOLKIT_RE.fullmatch(toolkit) and _COMPOSIO_SLUG_RE.fullmatch(action):
            grants.add((toolkit, action))
    return frozenset(grants)


def composio_public_slug(name: str) -> str | None:
    text = (name or "").strip()
    prefix = "composio."
    if not text.lower().startswith(prefix):
        return None
    slug = text[len(prefix):]
    if not slug or slug.lower() in _COMPOSIO_META_SLUGS:
        return None
    return slug


def composio_slug_is_mutating(slug: str, *, toolkit: str = "") -> bool:
    """GitHub writes and known mutating verbs. A readOnlyHint claim cannot override this."""
    parts = (slug or "").upper().split("_")
    if len(parts) < 2:
        return False
    verb = parts[1]
    if verb in _COMPOSIO_WRITE_VERBS:
        return True
    toolkit_name = (toolkit or parts[0]).strip().lower()
    if toolkit_name == "github" and verb not in _COMPOSIO_READ_VERBS:
        return True
    return False


def composio_write_allowlisted(name: str, *, toolkit: str | None = None, raw: str | None = None) -> bool:
    slug = composio_public_slug(name)
    if slug is None:
        if (name or "").strip().lower().startswith("composio."):
            return False
        slug = (name or "").strip()
    if not slug:
        return False
    action = slug.upper()
    grants = parse_composio_write_allowlist(raw)
    if toolkit is not None:
        return (toolkit.strip().lower(), action) in grants
    prefix = action.split("_", 1)[0].lower()
    return (prefix, action) in grants


def composio_unlisted_write(name: str) -> bool:
    slug = composio_public_slug(name)
    if slug is None or not composio_slug_is_mutating(slug):
        return False
    return not composio_write_allowlisted(name)


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
        if request.action == "org_change":
            self._authorize_org_change(request)
            return
        if request.action == "live_payment":
            self._authorize_live_payment(request)
            return
        raise PolicyError(f"Unknown policy action: {request.action}", FailureClass.POLICY_REFUSAL)

    def approval_required(self, request: PolicyRequest) -> ApprovalRequirement | None:
        """Mark irreversible acts that must pause for an explicit human approve/deny.

        Never implies auto-approve. `authorize` still fail-closes invalid acts first.
        """
        if request.action == "finish" and request.mission.limits.require_finish_approval:
            return ApprovalRequirement(
                action="finish",
                question="Approve completing this mission? Reply approve or deny.",
                reason="Finish requires human approval",
            )
        if request.action == "live_payment":
            return ApprovalRequirement(
                action="live_payment",
                question="Approve this live payment? Reply approve or deny.",
                reason="Live payment requires human approval",
            )
        if request.action == "org_change" and (request.org_op or "") in IRREVERSIBLE_ORG_OPS:
            op = request.org_op or "org_change"
            return ApprovalRequirement(
                action="org_change",
                question=f"Approve organization change '{op}'? Reply approve or deny.",
                reason=f"Organization {op} requires human approval",
                org_op=op,
            )
        if request.action == "tool_use":
            tool_name = (request.tool or "").strip()
            if tool_is_opted_in_composio(tool_name) and composio_write_allowlisted(tool_name):
                return ApprovalRequirement(
                    action="tool_use",
                    question=f"Approve mutating Composio action '{tool_name}'? Reply approve or deny.",
                    reason="Allowlisted Composio write requires human approval",
                    scope=f"composio_write:{tool_name.lower()}",
                )
        return None

    def check_tool_budget(self, mission: Mission, used: int) -> None:
        if used >= mission.limits.max_tool_calls:
            raise PolicyError("Tool call limit reached", FailureClass.RESOURCE_EXHAUSTED)

    def check_token_budget(self, mission: Mission, spent: float, additional: float, budget: float) -> None:
        """Token USD budget is independent of WalletAdapter payment `spent`."""
        del mission
        if additional < 0:
            raise PolicyError("Token cost adjustment is invalid", FailureClass.INVALID_OUTPUT)
        if round(spent + additional, 8) > round(budget, 8):
            raise PolicyError("Token cost would exceed mission token budget", FailureClass.RESOURCE_EXHAUSTED)

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
        if (
            tool_is_dangerous(name)
            and not tool_is_opted_in_browser(name)
            and not tool_is_opted_in_selfmod(name)
            and not tool_is_opted_in_composio(name)
        ):
            raise PolicyError(f"Tool '{name}' is denied by default", FailureClass.POLICY_REFUSAL)
        if composio_unlisted_write(name):
            raise PolicyError(
                f"Composio write '{name}' is not allowlisted",
                FailureClass.POLICY_REFUSAL,
            )

    def _authorize_org_change(self, request: PolicyRequest) -> None:
        op = (request.org_op or "").strip()
        if op not in {"spawn", "replace", "reparent", "retire"}:
            raise PolicyError("Unknown organization operation", FailureClass.INVALID_OUTPUT)

    def _authorize_live_payment(self, request: PolicyRequest) -> None:
        if not request.mission.live_payments:
            raise PolicyError("Live payments are not enabled for this mission", FailureClass.POLICY_REFUSAL)
