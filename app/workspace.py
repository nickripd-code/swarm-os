"""WorkspaceProvider seam: isolated per-mission/per-agent filesystem sandboxes.

Default backend is a local directory under a configurable root. Path traversal
and writes outside that root fail closed. Docker/remote backends are later.
Never log or return credentials.
"""
from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .models import FailureClass, utcnow

META_NAME = ".swarm-workspace.json"
MAX_PATH_BYTES = 256
MAX_CONTENT_BYTES = 1_048_576
MAX_HAND_FILES = 32
DEFAULT_ROOT_NAME = "swarm-workspaces"


class WorkspaceError(Exception):
    """Safe workspace failure. Messages must never contain credentials."""

    def __init__(self, message: str, failure_class: FailureClass = FailureClass.TOOL_FAILURE):
        super().__init__(message)
        self.failure_class = failure_class


class WorkspaceHandle(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    mission_id: UUID
    agent_id: UUID | None = None
    path: str
    provider: str
    created_at: str | None = None


class WorkspaceHealth(BaseModel):
    provider: str
    status: Literal["healthy", "unconfigured", "unavailable"]
    backend: str = "filesystem"
    root: str | None = None
    detail: str | None = None


class WorkspaceProvider(ABC):
    """Provider-neutral isolated workspace API owned by Swarm OS.

    Future Docker / remote / Kubernetes adapters implement this contract.
    This slice is a local filesystem sandbox only.
    """

    provider_id: str

    @abstractmethod
    async def create(self, *, mission_id: UUID, agent_id: UUID | None = None) -> WorkspaceHandle:
        raise NotImplementedError

    @abstractmethod
    async def get(self, workspace_id: UUID) -> WorkspaceHandle:
        raise NotImplementedError

    @abstractmethod
    def path(self, workspace_id: UUID, relative: str = ".") -> Path:
        raise NotImplementedError

    @abstractmethod
    async def write_file(self, workspace_id: UUID, relative: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read_file(self, workspace_id: UUID, relative: str) -> str:
        raise NotImplementedError

    async def hand_files(self, source_id: UUID, dest_id: UUID, relatives: list[str]) -> list[str]:
        """Copy explicit files between workspaces. Default providers fail closed."""
        raise WorkspaceError(
            "Workspace handoff is not supported by this provider",
            FailureClass.TOOL_MISSING,
        )

    async def health(self) -> WorkspaceHealth:
        return WorkspaceHealth(
            provider=self.provider_id,
            status="unconfigured",
            detail="Workspace provider is not configured",
        )


def default_workspace_root() -> Path:
    env = os.getenv("SWARM_WORKSPACE_ROOT", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(tempfile.gettempdir()) / DEFAULT_ROOT_NAME


def normalize_relpath(value: Any, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        if allow_dot:
            return "."
        raise WorkspaceError("Workspace path must be a relative file path", FailureClass.TOOL_FAILURE)
    raw = value.strip().replace("\\", "/")
    if "\x00" in raw:
        raise WorkspaceError("Path is invalid", FailureClass.POLICY_REFUSAL)
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        raise WorkspaceError("Path exceeds the size limit", FailureClass.TOOL_FAILURE)
    if raw.startswith("/") or raw.startswith("~") or (len(raw) >= 2 and raw[1] == ":"):
        raise WorkspaceError("Absolute or drive paths are not allowed", FailureClass.POLICY_REFUSAL)
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
    if not parts:
        if allow_dot:
            return "."
        raise WorkspaceError("Workspace path must be a relative file path", FailureClass.TOOL_FAILURE)
    return "/".join(parts)


def _contained(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


class LocalFilesystemWorkspaceProvider(WorkspaceProvider):
    """Isolated directories under a single root. Fail closed outside that root."""

    provider_id = "local"

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else default_workspace_root()
        self.root = self.root.expanduser()

    def _ensure_root(self) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            resolved = self.root.resolve()
        except OSError as exc:
            raise WorkspaceError("Workspace root is unavailable", FailureClass.PROVIDER_OUTAGE) from exc
        self.root = resolved
        return resolved

    def _workspace_dir(self, workspace_id: UUID) -> Path:
        root = self._ensure_root()
        target = (root / str(workspace_id)).resolve()
        if not _contained(target, root):
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        return target

    def _read_handle(self, workspace_id: UUID) -> WorkspaceHandle:
        directory = self._workspace_dir(workspace_id)
        meta_path = directory / META_NAME
        if not directory.is_dir() or not meta_path.is_file():
            raise WorkspaceError("Workspace not found", FailureClass.TOOL_MISSING)
        if not _contained(directory, self.root) or not _contained(meta_path, directory):
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError("Workspace metadata is unreadable", FailureClass.TOOL_FAILURE) from exc
        payload["path"] = str(directory)
        payload["provider"] = self.provider_id
        try:
            return WorkspaceHandle.model_validate(payload)
        except Exception as exc:
            raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE) from exc

    def _safe_join(self, workspace_id: UUID, relative: str, *, allow_dot: bool = False) -> Path:
        handle = self._read_handle(workspace_id)
        directory = Path(handle.path).resolve()
        rel = normalize_relpath(relative, allow_dot=allow_dot)
        raw_target = directory if rel == "." else directory.joinpath(*rel.split("/"))
        if raw_target.is_symlink():
            raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
        resolved = raw_target.resolve()
        if not _contained(resolved, directory) or resolved.is_symlink():
            raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
        return resolved

    async def create(self, *, mission_id: UUID, agent_id: UUID | None = None) -> WorkspaceHandle:
        workspace_id = uuid4()
        directory = self._workspace_dir(workspace_id)
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise WorkspaceError("Workspace already exists", FailureClass.TOOL_FAILURE) from exc
        except OSError as exc:
            raise WorkspaceError("Workspace directory could not be created", FailureClass.PROVIDER_OUTAGE) from exc
        handle = WorkspaceHandle(
            id=workspace_id,
            mission_id=mission_id,
            agent_id=agent_id,
            path=str(directory),
            provider=self.provider_id,
            created_at=utcnow().isoformat(),
        )
        meta = handle.model_dump(mode="json")
        (directory / META_NAME).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return handle

    async def get(self, workspace_id: UUID) -> WorkspaceHandle:
        return self._read_handle(workspace_id)

    def path(self, workspace_id: UUID, relative: str = ".") -> Path:
        return self._safe_join(workspace_id, relative, allow_dot=True)

    async def write_file(self, workspace_id: UUID, relative: str, content: str) -> None:
        if not isinstance(content, str):
            raise WorkspaceError("Workspace writes require string content", FailureClass.TOOL_FAILURE)
        if "\x00" in content:
            raise WorkspaceError("Binary content is not allowed", FailureClass.TOOL_FAILURE)
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise WorkspaceError("File content exceeds the size limit", FailureClass.TOOL_FAILURE)
        rel = normalize_relpath(relative)
        if rel == META_NAME or rel.endswith("/" + META_NAME) or Path(rel).name == META_NAME:
            raise WorkspaceError("Workspace metadata is reserved", FailureClass.POLICY_REFUSAL)
        target = self._safe_join(workspace_id, rel)
        parent = target.parent
        handle = self._read_handle(workspace_id)
        directory = Path(handle.path)
        if not _contained(parent.resolve(), directory):
            raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
        try:
            parent.mkdir(parents=True, exist_ok=True)
            if not _contained(parent.resolve(), directory):
                raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
            target.write_text(content, encoding="utf-8")
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceError("Workspace file could not be written", FailureClass.TOOL_FAILURE) from exc
        if not _contained(target.resolve(), directory):
            try:
                target.unlink()
            except OSError:
                pass
            raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)

    async def read_file(self, workspace_id: UUID, relative: str) -> str:
        target = self._safe_join(workspace_id, relative)
        if not target.is_file():
            raise WorkspaceError("File not found", FailureClass.TOOL_FAILURE)
        try:
            return target.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceError("Workspace file could not be read", FailureClass.TOOL_FAILURE) from exc

    async def hand_files(self, source_id: UUID, dest_id: UUID, relatives: list[str]) -> list[str]:
        """Copy explicit regular files to another workspace in the same mission.

        The source is left in place. Symlinks, metadata, cross-mission copies,
        and a hand into the same workspace fail closed. Organization replace
        does not call this.
        """
        if source_id == dest_id:
            raise WorkspaceError("A workspace cannot hand files to itself", FailureClass.POLICY_REFUSAL)
        source = await self.get(source_id)
        dest = await self.get(dest_id)
        if source.mission_id != dest.mission_id:
            raise WorkspaceError(
                "Code mission hand refuses a different mission",
                FailureClass.POLICY_REFUSAL,
            )
        if not isinstance(relatives, list) or not relatives:
            raise WorkspaceError("Code mission hand requires explicit file paths", FailureClass.TOOL_FAILURE)
        if len(relatives) > MAX_HAND_FILES:
            raise WorkspaceError("Too many files in one handoff", FailureClass.TOOL_FAILURE)
        staged: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw in relatives:
            rel = normalize_relpath(raw)
            if rel in seen:
                raise WorkspaceError("Duplicate path in handoff", FailureClass.TOOL_FAILURE)
            if Path(rel).name == META_NAME:
                raise WorkspaceError("Workspace metadata is reserved", FailureClass.POLICY_REFUSAL)
            seen.add(rel)
            staged.append((rel, await self.read_file(source_id, rel)))
        copied: list[str] = []
        for rel, content in staged:
            await self.write_file(dest_id, rel, content)
            copied.append(rel)
        return copied

    async def health(self) -> WorkspaceHealth:
        try:
            root = self._ensure_root()
        except WorkspaceError as exc:
            return WorkspaceHealth(
                provider=self.provider_id,
                status="unavailable",
                backend="filesystem",
                detail=str(exc),
            )
        writable = os.access(root, os.W_OK)
        return WorkspaceHealth(
            provider=self.provider_id,
            status="healthy" if writable else "unavailable",
            backend="filesystem",
            root=str(root),
            detail="Local filesystem sandbox" if writable else "Workspace root is not writable",
        )


def build_workspace_provider(root: Path | str | None = None) -> WorkspaceProvider:
    """Production factory. Local filesystem only in this slice — no Docker."""
    return LocalFilesystemWorkspaceProvider(root=root)
