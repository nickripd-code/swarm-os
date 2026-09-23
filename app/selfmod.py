"""Fail-closed self-modification sandbox behind ToolProvider.

Disabled by default (`SWARM_SELFMOD` unset). Propose + dry-run/diff only.
When opted in, propose/diff can use an isolated git worktree under
`SWARM_SELFMOD_WORKTREE_ROOT` (default: a temp directory outside the source
tree). That worktree is a local clone plus `git worktree add`; it is not
registered on the source repository and it does not receive proposal bytes
until `selfmod.apply`. Never writes production files unless
`SWARM_SELFMOD_WRITE` and `SWARM_SELFMOD_PRODUCTION_WRITE` are both set.
Tests inject a fake workspace or a temporary git repository.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
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


def _overlaps(child: Path, parent: Path) -> bool:
    return _contained(child, parent)


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

    def prepare(self) -> dict[str, Any]:
        """Materialize an isolated checkout when this workspace has one.

        The default is a no-op so in-memory and overlay fakes stay dry.
        Must not report success it did not create.
        """
        return {}


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


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GCM_INTERACTIVE"] = "Never"
    return env


def _run_git(args: list[str], *, cwd: Path, hooks: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", f"core.hooksPath={hooks}", *args],
        cwd=cwd,
        capture_output=True,
        timeout=60,
        check=False,
        env=_git_env(),
    )


class WorktreeWorkspace(SelfModWorkspace):
    """Isolated git worktree seeded from a local repository.

    `prepare` clones the source with `--local --no-hardlinks` under the
    configured root, then `git worktree add`s a new branch. The source
    repository's branch list and working tree are not updated. Propose/diff
    only read the worktree. Apply writes there only when explicitly enabled,
    and a root inside the source or production tree is refused unless
    production write is opted in.
    """

    def __init__(
        self,
        source_repo: Path | None = None,
        worktree_root: Path | None = None,
        *,
        production_write: bool | None = None,
    ):
        self._source_override = source_repo
        self._root_override = worktree_root
        self._production_write_override = production_write
        self._source_repo: Path | None = None
        self._parent: Path | None = None
        self._tree: Path | None = None
        self._branch: str | None = None

    def prepare(self) -> dict[str, Any]:
        if self._branch and self._tree is not None:
            return self._public()
        source = self._resolve_source()
        parent = self._resolve_parent()
        self._source_repo = source
        self._parent = parent
        if self.writes_production() and not self._production_allowed():
            raise ToolError(
                "Worktree root overlaps the source tree; production writes are disabled",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        if not (source / ".git").exists():
            raise ToolError(
                "Self-mod source is not a git repository",
                FailureClass.TOOL_FAILURE,
            )
        parent.mkdir(parents=True, exist_ok=True)
        slot = parent / f"slot-{uuid4().hex[:12]}"
        hooks = slot / "hooks"
        base = slot / "base"
        tree = slot / "tree"
        slot.mkdir()
        hooks.mkdir()
        cloned = _run_git(
            ["clone", "--local", "--no-hardlinks", "--", str(source), str(base)],
            cwd=parent,
            hooks=hooks,
        )
        if cloned.returncode != 0:
            raise ToolError(
                "Failed to create isolated self-mod repository",
                FailureClass.TOOL_FAILURE,
            )
        _run_git(["remote", "remove", "origin"], cwd=base, hooks=hooks)
        branch = f"swarm-selfmod-{uuid4().hex[:12]}"
        added = _run_git(
            ["worktree", "add", "-b", branch, str(tree), "HEAD"],
            cwd=base,
            hooks=hooks,
        )
        if added.returncode != 0 or not tree.is_dir():
            raise ToolError(
                "Failed to create isolated self-mod worktree",
                FailureClass.TOOL_FAILURE,
            )
        resolved = tree.resolve()
        if not _contained(resolved, slot.resolve()):
            raise ToolError("Worktree escaped its root", FailureClass.POLICY_REFUSAL)
        if _overlaps(resolved, source) or _overlaps(resolved, PRODUCTION_ROOT):
            if not self._production_allowed():
                raise ToolError(
                    "Worktree overlaps the source tree; production writes are disabled",
                    FailureClass.AUTHORIZATION_REQUIRED,
                )
        self._tree = resolved
        self._branch = branch
        return self._public()

    def read(self, path: str) -> str | None:
        self.prepare()
        target = self._resolve_in_worktree(path, writing=False)
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError("Binary content is not allowed", FailureClass.TOOL_FAILURE) from None

    def write(self, path: str, content: str) -> None:
        self.prepare()
        if self.writes_production() and not self._production_allowed():
            raise ToolError(
                "Production writes are disabled until SWARM_SELFMOD_PRODUCTION_WRITE is set",
                FailureClass.AUTHORIZATION_REQUIRED,
            )
        target = self._resolve_in_worktree(path, writing=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not _contained(target.parent.resolve(), self._require_tree()):
            raise ToolError("Path escaped the worktree", FailureClass.POLICY_REFUSAL)
        target.write_text(content, encoding="utf-8")

    def writes_production(self) -> bool:
        if self._production_write():
            return True
        source = self._source_repo
        parent = self._parent
        if source is not None and parent is not None and _overlaps(parent, source):
            return True
        if parent is not None and _overlaps(parent, PRODUCTION_ROOT):
            return True
        tree = self._tree
        if tree is not None and source is not None and _overlaps(tree, source):
            return True
        if tree is not None and _overlaps(tree, PRODUCTION_ROOT):
            return True
        return False

    def _production_write(self) -> bool:
        if self._production_write_override is None:
            return selfmod_production_write_opted_in()
        return self._production_write_override

    def _production_allowed(self) -> bool:
        return self._production_write() and selfmod_production_write_opted_in()

    def _public(self) -> dict[str, Any]:
        return {
            "isolation": "worktree",
            "worktree": True,
            "branch": self._branch,
        }

    def _resolve_source(self) -> Path:
        if self._source_override is not None:
            source = Path(self._source_override)
        else:
            raw = os.getenv("SWARM_SELFMOD_SOURCE", "").strip()
            source = Path(raw) if raw else PRODUCTION_ROOT
        if not source.is_absolute():
            raise ToolError(
                "Self-mod source must be an absolute repository path",
                FailureClass.POLICY_REFUSAL,
            )
        if "://" in source.as_posix():
            raise ToolError(
                "Self-mod source must be a local repository",
                FailureClass.POLICY_REFUSAL,
            )
        return source.resolve()

    def _resolve_parent(self) -> Path:
        if self._root_override is not None:
            parent = Path(self._root_override)
        else:
            raw = os.getenv("SWARM_SELFMOD_WORKTREE_ROOT", "").strip()
            if not raw:
                return Path(tempfile.mkdtemp(prefix="swarm-selfmod-wt-")).resolve()
            parent = Path(raw)
        if not parent.is_absolute():
            raise ToolError(
                "SWARM_SELFMOD_WORKTREE_ROOT must be an absolute path outside the source tree",
                FailureClass.POLICY_REFUSAL,
            )
        return parent.resolve()

    def _require_tree(self) -> Path:
        if self._tree is None:
            raise ToolError("Isolated worktree is not ready", FailureClass.TOOL_FAILURE)
        return self._tree

    def _resolve_in_worktree(self, relpath: str, *, writing: bool) -> Path:
        root = self._require_tree()
        normalized = normalize_relpath(relpath)
        if writing and path_is_protected(normalized):
            raise ToolError(
                "Protected core files cannot be applied",
                FailureClass.POLICY_REFUSAL,
            )
        current = root
        for part in normalized.split("/"):
            current = current / part
            if current.is_symlink():
                self._reject_symlink(current, root)
                current = current.resolve()
            elif current.exists():
                resolved = current.resolve()
                if not _contained(resolved, root):
                    raise ToolError("Path escaped the worktree", FailureClass.POLICY_REFUSAL)
        if not _contained(current, root):
            raise ToolError("Path escaped the worktree", FailureClass.POLICY_REFUSAL)
        if not current.exists():
            if not _contained(current.parent.resolve(), root):
                raise ToolError("Path escaped the worktree", FailureClass.POLICY_REFUSAL)
            return current
        resolved = current.resolve()
        if not _contained(resolved, root):
            raise ToolError("Path escaped the worktree", FailureClass.POLICY_REFUSAL)
        inside = resolved.relative_to(root.resolve()).as_posix()
        if path_is_protected(inside) and (writing or inside != normalized):
            raise ToolError(
                "Path escaped into protected core",
                FailureClass.POLICY_REFUSAL,
            )
        if self._points_at_protected_source(resolved):
            raise ToolError(
                "Path escaped into protected core",
                FailureClass.POLICY_REFUSAL,
            )
        return current

    def _reject_symlink(self, link: Path, root: Path) -> None:
        resolved = link.resolve()
        if not _contained(resolved, root):
            if self._points_at_protected_source(resolved):
                raise ToolError(
                    "Path escaped into protected core",
                    FailureClass.POLICY_REFUSAL,
                )
            raise ToolError("Path escaped the worktree", FailureClass.POLICY_REFUSAL)
        inside = resolved.relative_to(root.resolve()).as_posix()
        if path_is_protected(inside) or self._points_at_protected_source(resolved):
            raise ToolError(
                "Path escaped into protected core",
                FailureClass.POLICY_REFUSAL,
            )

    def _points_at_protected_source(self, resolved: Path) -> bool:
        bases = [PRODUCTION_ROOT]
        if self._source_repo is not None:
            bases.append(self._source_repo)
        for base in bases:
            try:
                relative = resolved.resolve().relative_to(base.resolve()).as_posix()
            except ValueError:
                continue
            if relative in ("", "."):
                continue
            if path_is_protected(relative):
                return True
        return False


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
            description="Propose a code or config change against an isolated worktree. Stores a dry-run proposal; does not write files.",
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
            description="Return a dry-run unified diff for a stored proposal against the isolated worktree. Does not write files.",
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
        source_repo: Path | None = None,
        worktree_root: Path | None = None,
    ):
        self._opted_in = selfmod_opted_in() if opted_in is None else opted_in
        self._write_enabled = (
            selfmod_write_opted_in() if write_enabled is None else write_enabled
        ) and self._opted_in
        self._workspace = workspace
        self._source_repo = source_repo
        self._worktree_root = worktree_root
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
        if selfmod_production_write_opted_in():
            detail = "Propose/diff enabled; production write flag is set"
        elif self._write_enabled:
            detail = "Propose/diff enabled; isolated worktree apply opted in"
        else:
            detail = "Propose/diff only against an isolated worktree; writes are disabled"
        return ToolHealth(
            provider=self.provider_id,
            status="healthy",
            detail=detail,
            tools=[spec.name for spec in self._specs],
        )

    def _require_workspace(self) -> SelfModWorkspace:
        if self._workspace is None:
            self._workspace = WorktreeWorkspace(
                source_repo=self._source_repo,
                worktree_root=self._worktree_root,
            )
        return self._workspace

    def _isolation_fields(self, prepared: dict[str, Any]) -> dict[str, Any]:
        return {
            key: prepared[key]
            for key in ("isolation", "worktree", "branch")
            if key in prepared
        }

    def _propose(self, arguments: dict[str, Any]) -> dict[str, Any]:
        reason = arguments.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ToolError("selfmod.propose requires a string reason", FailureClass.TOOL_FAILURE)
        changes = parse_changes(arguments.get("changes"))
        prepared = self._require_workspace().prepare()
        proposal_id = uuid4().hex[:12]
        self._proposals[proposal_id] = {
            "reason": reason.strip()[:MAX_REASON_CHARS],
            "changes": changes,
            "applied": False,
            "branch": prepared.get("branch"),
        }
        return {
            "proposal_id": proposal_id,
            "reason": reason.strip()[:MAX_REASON_CHARS],
            "applied": False,
            "mode": "proposal",
            "write_enabled": self._write_enabled,
            "files": [item["path"] for item in changes],
            "protected": [item["path"] for item in changes if item["protected"]],
            **self._isolation_fields(prepared),
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
        prepared = workspace.prepare()
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
            **self._isolation_fields(prepared),
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
            **self._isolation_fields(workspace.prepare()),
        }
