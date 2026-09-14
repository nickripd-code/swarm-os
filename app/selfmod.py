"""Fail-closed self-modification sandbox behind ToolProvider.

Disabled by default (`SWARM_SELFMOD` unset). Propose + dry-run/diff only.
Never writes production files unless `SWARM_SELFMOD_WRITE` and
`SWARM_SELFMOD_PRODUCTION_WRITE` are both set. Tests inject a fake workspace.
"""
from __future__ import annotations

import difflib
import os
import re
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import FailureClass
from .tools import (
    ToolCall, ToolError, ToolHealth, ToolProvider, ToolResult, ToolSpec,
    public_tool_data, require_arguments,
)

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
PROPOSE_DIFF_TOOLS = ("selfmod.propose", "selfmod.diff")
APPLY_TOOL = "selfmod.apply"
SELFMOD_TOOL_NAMES = (*PROPOSE_DIFF_TOOLS, APPLY_TOOL)
OPTED_IN_SELFMOD_DIFF_TOOLS = frozenset(PROPOSE_DIFF_TOOLS)
OPTED_IN_SELFMOD_WRITE_TOOLS = frozenset({APPLY_TOOL})

PROTECTED_PATHS = frozenset({
    "app/policy.py",
    "app/credentials.py",
    "app/payments.py",
    "app/selfmod.py",
    "app/leases.py",
})
PROTECTED_PREFIXES = (".env", "secrets/", "credentials/")
MAX_CHANGES = 20
MAX_PATH_BYTES = 256
MAX_CONTENT_BYTES = 32_768
MAX_DIFF_CHARS = 20_000
MAX_REASON_CHARS = 500
_SECRET_LINE = re.compile(
    r"(?i)(api[_-]?key|authorization|password|secret|token|private[_-]?key|access[_-]?token)\s*[=:]",
)
PRODUCTION_ROOT = Path(__file__).resolve().parent.parent


def env_flag(name: str, raw: str | None = None) -> bool:
    text = (raw if raw is not None else os.getenv(name, "")).strip().lower()
    return text in TRUE_VALUES


def selfmod_opted_in(raw: str | None = None) -> bool:
    return env_flag("SWARM_SELFMOD", raw)


def selfmod_write_opted_in(raw: str | None = None) -> bool:
    return selfmod_opted_in() and env_flag("SWARM_SELFMOD_WRITE", raw)


def selfmod_production_write_opted_in() -> bool:
    return selfmod_write_opted_in() and env_flag("SWARM_SELFMOD_PRODUCTION_WRITE")


def normalize_relpath(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("selfmod requires a relative file path", FailureClass.TOOL_FAILURE)
    raw = value.strip().replace("\\", "/")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        raise ToolError("Path exceeds the size limit", FailureClass.TOOL_FAILURE)
    if raw.startswith("/") or raw.startswith("~") or ":" in raw:
        raise ToolError("Absolute or drive paths are not allowed", FailureClass.TOOL_FAILURE)
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ToolError("Path traversal is not allowed", FailureClass.TOOL_FAILURE)
    return "/".join(parts)


def path_is_protected(path: str) -> bool:
    lowered = path.lower()
    if lowered in {item.lower() for item in PROTECTED_PATHS}:
        return True
    name = lowered.rsplit("/", 1)[-1]
    if name.startswith(".env"):
        return True
    return any(lowered.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def redact_text(text: str) -> str:
    lines = []
    for line in text.splitlines(keepends=True):
        if _SECRET_LINE.search(line):
            ending = "\n" if line.endswith("\n") else ""
            lines.append(f"# [redacted]{ending}")
        else:
            lines.append(line)
    return "".join(lines)


def _contained(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


class SelfModWorkspace(ABC):
    """Read originals and optionally write applied files. Fakes must not invent success."""

    @abstractmethod
    def read(self, path: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def write(self, path: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def writes_production(self) -> bool:
        raise NotImplementedError


class MemoryWorkspace(SelfModWorkspace):
    """In-memory originals + recorded writes. Used by tests."""

    def __init__(self, files: dict[str, str] | None = None, *, production: bool = False):
        self.files = dict(files or {})
        self.written: list[tuple[str, str]] = []
        self._production = production

    def read(self, path: str) -> str | None:
        return self.files.get(path)

    def write(self, path: str, content: str) -> None:
        if self._production:
            raise ToolError(
                "Production writes are disabled",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        self.written.append((path, content))
        self.files[path] = content

    def writes_production(self) -> bool:
        return self._production


class SandboxWorkspace(SelfModWorkspace):
    """Read-only source tree + isolated sandbox writes. Production writes stay opt-in."""

    def __init__(
        self,
        source_root: Path | None = None,
        sandbox_root: Path | None = None,
        *,
        production_write: bool | None = None,
    ):
        self.source_root = (source_root or PRODUCTION_ROOT).resolve()
        if sandbox_root is None:
            env_root = os.getenv("SWARM_SELFMOD_SANDBOX", "").strip()
            sandbox_root = Path(env_root) if env_root else Path(tempfile.mkdtemp(prefix="swarm-selfmod-"))
        self.sandbox_root = Path(sandbox_root).resolve()
        self.production_write = (
            selfmod_production_write_opted_in() if production_write is None else production_write
        )

    def read(self, path: str) -> str | None:
        target = self._safe_join(self.source_root, path)
        if target.is_file():
            return target.read_text(encoding="utf-8")
        overlay = self._safe_join(self.sandbox_root, path)
        if overlay.is_file():
            return overlay.read_text(encoding="utf-8")
        return None

    def write(self, path: str, content: str) -> None:
        if self.writes_production() and not self.production_write:
            raise ToolError(
                "Production writes are disabled until SWARM_SELFMOD_PRODUCTION_WRITE is set",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        root = self.source_root if self.production_write else self.sandbox_root
        target = self._safe_join(root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def writes_production(self) -> bool:
        if self.production_write:
            return True
        return _contained(self.sandbox_root, self.source_root)

    def _safe_join(self, root: Path, relpath: str) -> Path:
        target = (root / relpath).resolve()
        if not _contained(target, root):
            raise ToolError("Path escaped the sandbox", FailureClass.POLICY_REFUSAL)
        return target


def parse_changes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ToolError("selfmod.propose requires a non-empty changes list", FailureClass.TOOL_FAILURE)
    if len(raw) > MAX_CHANGES:
        raise ToolError("Too many files in one proposal", FailureClass.TOOL_FAILURE)
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolError("Each change must be an object with path and content", FailureClass.TOOL_FAILURE)
        path = normalize_relpath(item.get("path"))
        if path in seen:
            raise ToolError("Duplicate path in proposal", FailureClass.TOOL_FAILURE)
        content = item.get("content")
        if not isinstance(content, str):
            raise ToolError("Each change requires string content", FailureClass.TOOL_FAILURE)
        if "\x00" in content:
            raise ToolError("Binary content is not allowed", FailureClass.TOOL_FAILURE)
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ToolError("File content exceeds the size limit", FailureClass.TOOL_FAILURE)
        seen.add(path)
        parsed.append({
            "path": path,
            "content": content,
            "protected": path_is_protected(path),
        })
    return parsed


def unified_diff(path: str, original: str | None, proposed: str) -> str:
    before = (original or "").splitlines(keepends=True)
    after = proposed.splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(
        before,
        after,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    ))
    if not diff:
        diff = f"--- a/{path}\n+++ b/{path}\n"
    return redact_text(diff)[:MAX_DIFF_CHARS]


def _selfmod_specs(include_apply: bool) -> list[ToolSpec]:
    specs = [
        ToolSpec(
            name="selfmod.propose",
            description="Propose a code or config change. Stores a dry-run proposal; does not write files.",
            provider="selfmod",
            permissions=["selfmod"],
            risk_class="selfmod",
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                    },
                },
                "required": ["reason", "changes"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "applied": {"type": "boolean"},
                    "mode": {"type": "string"},
                    "files": {"type": "array"},
                },
                "required": ["proposal_id", "applied"],
            },
            environment=["SWARM_SELFMOD"],
        ),
        ToolSpec(
            name="selfmod.diff",
            description="Return a dry-run unified diff for a stored proposal. Does not write files.",
            provider="selfmod",
            permissions=["selfmod"],
            risk_class="selfmod",
            input_schema={
                "type": "object",
                "properties": {"proposal_id": {"type": "string"}},
                "required": ["proposal_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "applied": {"type": "boolean"},
                    "diffs": {"type": "array"},
                },
                "required": ["proposal_id", "applied"],
            },
            environment=["SWARM_SELFMOD"],
        ),
    ]
    if include_apply:
        specs.append(ToolSpec(
            name="selfmod.apply",
            description="Apply a stored proposal to the sandbox. Production writes require a second env flag.",
            provider="selfmod",
            permissions=["selfmod", "write"],
            risk_class="selfmod",
            input_schema={
                "type": "object",
                "properties": {"proposal_id": {"type": "string"}},
                "required": ["proposal_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "applied": {"type": "boolean"},
                    "sandbox": {"type": "boolean"},
                },
                "required": ["proposal_id", "applied"],
            },
            environment=["SWARM_SELFMOD", "SWARM_SELFMOD_WRITE"],
        ))
    return specs


class SelfModToolProvider(ToolProvider):
    """Opt-in propose/diff sandbox. Unconfigured until SWARM_SELFMOD is set."""

    provider_id = "selfmod"

    def __init__(
        self,
        *,
        opted_in: bool | None = None,
        write_enabled: bool | None = None,
        workspace: SelfModWorkspace | None = None,
    ):
        self._opted_in = selfmod_opted_in() if opted_in is None else opted_in
        self._write_enabled = (
            selfmod_write_opted_in() if write_enabled is None else write_enabled
        ) and self._opted_in
        self._workspace = workspace
        self._proposals: dict[str, dict[str, Any]] = {}
        self._specs = _selfmod_specs(self._write_enabled) if self._opted_in else []

    def configured(self) -> bool:
        return self._opted_in

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    async def invoke(self, call: ToolCall) -> ToolResult:
        if not self._opted_in:
            raise ToolError("Self-modification tools are disabled", FailureClass.TOOL_MISSING)
        if call.name not in SELFMOD_TOOL_NAMES:
            raise ToolError(f"Unknown tool: {call.name}", FailureClass.TOOL_MISSING)
        if call.name == APPLY_TOOL and not self._write_enabled:
            raise ToolError(
                "selfmod.apply is disabled until SWARM_SELFMOD_WRITE is set",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        arguments = require_arguments(call.arguments)
        try:
            if call.name == "selfmod.propose":
                output = self._propose(arguments)
            elif call.name == "selfmod.diff":
                output = self._diff(arguments)
            else:
                output = self._apply(arguments)
        except ToolError:
            raise
        except Exception:
            raise ToolError("Self-modification sandbox failed", FailureClass.TOOL_FAILURE) from None
        return ToolResult(
            name=call.name,
            call_id=call.call_id,
            ok=True,
            output=public_tool_data(output),
            provider=self.provider_id,
        )

    async def health(self) -> ToolHealth:
        if not self._opted_in:
            return ToolHealth(
                provider=self.provider_id,
                status="unconfigured",
                detail="Self-modification is disabled until SWARM_SELFMOD is set",
            )
        if self._write_enabled:
            detail = "Propose/diff enabled; sandbox apply opted in"
        else:
            detail = "Propose/diff only; writes are disabled"
        return ToolHealth(
            provider=self.provider_id,
            status="healthy",
            detail=detail,
            tools=[spec.name for spec in self._specs],
        )

    def _require_workspace(self) -> SelfModWorkspace:
        if self._workspace is None:
            self._workspace = SandboxWorkspace()
        return self._workspace

    def _propose(self, arguments: dict[str, Any]) -> dict[str, Any]:
        reason = arguments.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ToolError("selfmod.propose requires a string reason", FailureClass.TOOL_FAILURE)
        changes = parse_changes(arguments.get("changes"))
        proposal_id = uuid4().hex[:12]
        self._proposals[proposal_id] = {
            "reason": reason.strip()[:MAX_REASON_CHARS],
            "changes": changes,
            "applied": False,
        }
        return {
            "proposal_id": proposal_id,
            "reason": reason.strip()[:MAX_REASON_CHARS],
            "applied": False,
            "mode": "proposal",
            "write_enabled": self._write_enabled,
            "files": [item["path"] for item in changes],
            "protected": [item["path"] for item in changes if item["protected"]],
        }

    def _get_proposal(self, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        proposal_id = arguments.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise ToolError("proposal_id is required", FailureClass.TOOL_FAILURE)
        proposal = self._proposals.get(proposal_id.strip())
        if proposal is None:
            raise ToolError("Unknown proposal_id", FailureClass.TOOL_FAILURE)
        return proposal_id.strip(), proposal

    def _diff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        proposal_id, proposal = self._get_proposal(arguments)
        workspace = self._require_workspace()
        diffs = []
        for change in proposal["changes"]:
            original = workspace.read(change["path"])
            diffs.append({
                "path": change["path"],
                "protected": change["protected"],
                "diff": unified_diff(change["path"], original, change["content"]),
            })
        return {
            "proposal_id": proposal_id,
            "applied": False,
            "mode": "diff",
            "diffs": diffs,
        }

    def _apply(self, arguments: dict[str, Any]) -> dict[str, Any]:
        proposal_id, proposal = self._get_proposal(arguments)
        if proposal["applied"]:
            raise ToolError("Proposal was already applied", FailureClass.TOOL_FAILURE)
        protected = [item["path"] for item in proposal["changes"] if item["protected"]]
        if protected:
            raise ToolError(
                "Protected core files cannot be applied",
                FailureClass.POLICY_REFUSAL,
            )
        workspace = self._require_workspace()
        if workspace.writes_production() and not selfmod_production_write_opted_in():
            raise ToolError(
                "Production writes are disabled",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        written: list[str] = []
        for change in proposal["changes"]:
            workspace.write(change["path"], change["content"])
            written.append(change["path"])
        proposal["applied"] = True
        return {
            "proposal_id": proposal_id,
            "applied": True,
            "sandbox": not workspace.writes_production(),
            "files": written,
        }
