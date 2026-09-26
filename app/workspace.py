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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .models import FailureClass, utcnow

META_NAME = ".swarm-workspace.json"
MAX_PATH_BYTES = 256
MAX_CONTENT_BYTES = 1_048_576
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
    destroy: bool = False
    gc: Literal["configured", "unconfigured"] = "unconfigured"
    ttl_seconds: int | None = None


class WorkspaceGcResult(BaseModel):
    """Result of an explicit GC pass. `configured` false means nothing was deleted."""

    configured: bool
    ttl_seconds: int | None = None
    destroyed: list[UUID] = Field(default_factory=list)
    kept: int = 0
    refused: int = 0


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

    @abstractmethod
    async def destroy(self, workspace_id: UUID) -> None:
        """Remove one sandbox. Must not touch paths outside the provider root."""
        raise NotImplementedError

    async def gc(self, *, ttl_seconds: int | None = None, now: datetime | None = None) -> WorkspaceGcResult:
        """TTL sweep. The base implementation never deletes."""
        return WorkspaceGcResult(configured=False)

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


def configured_workspace_ttl_seconds() -> int | None:
    """Positive TTL in seconds, or None when GC is off.

    Unset, blank, non-integer, and non-positive values leave GC unconfigured.
    Health reporting must not treat those as a license to delete.
    """
    raw = os.getenv("SWARM_WORKSPACE_TTL_SECONDS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _parse_created_at(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


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

    def _sandbox_dir(self, workspace_id: UUID) -> Path:
        """Direct child of the root named by the workspace id. Does not follow symlinks."""
        root = self._ensure_root()
        name = str(workspace_id)
        if name in {".", ".."} or Path(name).name != name:
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        return root / name

    def _scandir(self, directory: Path) -> list[os.DirEntry[str]]:
        try:
            with os.scandir(directory) as scan:
                return list(scan)
        except OSError as exc:
            raise WorkspaceError("Workspace could not be removed", FailureClass.TOOL_FAILURE) from exc

    def _assert_tree_contained(self, directory: Path, boundary: Path) -> None:
        """Refuse symlink escapes before any deletion. Does not mutate.

        Uses scandir so a symlink to a directory is visible. os.walk hides those
        when followlinks is false.
        """
        if directory.is_symlink() or not directory.is_dir() or not _contained(directory, boundary):
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        for entry in self._scandir(directory):
            path = Path(entry.path)
            try:
                is_link = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError as exc:
                raise WorkspaceError("Workspace could not be removed", FailureClass.TOOL_FAILURE) from exc
            if is_link:
                raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
            if not _contained(path.resolve(), boundary):
                raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
            if is_dir:
                self._assert_tree_contained(path.resolve(), boundary)
            elif not is_file:
                raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)

    def _purge_tree(self, directory: Path, boundary: Path) -> None:
        """Delete a real directory that was already proven to sit inside `boundary`."""
        if directory.is_symlink() or not _contained(directory, boundary):
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        for entry in self._scandir(directory):
            path = Path(entry.path)
            try:
                is_link = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                raise WorkspaceError("Workspace could not be removed", FailureClass.TOOL_FAILURE) from exc
            if is_link or not _contained(path.resolve(), boundary):
                raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
            if is_dir:
                self._purge_tree(path.resolve(), boundary)
                continue
            try:
                path.unlink()
            except OSError as exc:
                raise WorkspaceError("Workspace could not be removed", FailureClass.TOOL_FAILURE) from exc
        try:
            directory.rmdir()
        except OSError as exc:
            raise WorkspaceError("Workspace could not be removed", FailureClass.TOOL_FAILURE) from exc

    async def destroy(self, workspace_id: UUID) -> None:
        """Remove only `root/<workspace_id>`. Ignores the path stored in metadata."""
        root = self._ensure_root()
        directory = self._sandbox_dir(workspace_id)
        if directory.is_symlink():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        if not directory.exists() or not directory.is_dir():
            raise WorkspaceError("Workspace not found", FailureClass.TOOL_MISSING)
        resolved = directory.resolve()
        if resolved == root or not _contained(resolved, root):
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        meta = directory / META_NAME
        if meta.is_symlink():
            raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
        if not meta.is_file() or not _contained(meta.resolve(), resolved):
            raise WorkspaceError("Workspace not found", FailureClass.TOOL_MISSING)
        self._assert_tree_contained(resolved, resolved)
        self._purge_tree(resolved, resolved)

    async def gc(self, *, ttl_seconds: int | None = None, now: datetime | None = None) -> WorkspaceGcResult:
        """Delete expired sandboxes only when a positive TTL is configured.

        Unset or invalid `SWARM_WORKSPACE_TTL_SECONDS` (and a non-positive explicit
        TTL) returns immediately without listing or deleting. Unknown age is kept.
        Symlinks are refused and never followed.
        """
        if ttl_seconds is None:
            ttl = configured_workspace_ttl_seconds()
        elif isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            ttl = None
        else:
            ttl = ttl_seconds
        if ttl is None:
            return WorkspaceGcResult(configured=False)
        moment = now if now is not None else utcnow()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        cutoff = moment - timedelta(seconds=ttl)
        destroyed: list[UUID] = []
        kept = 0
        refused = 0
        root = self._ensure_root()
        try:
            children = list(root.iterdir())
        except OSError as exc:
            raise WorkspaceError("Workspace root is unavailable", FailureClass.PROVIDER_OUTAGE) from exc
        for child in children:
            if child.is_symlink():
                refused += 1
                continue
            if not child.is_dir():
                continue
            try:
                workspace_id = UUID(child.name)
            except ValueError:
                continue
            if child.name != str(workspace_id):
                refused += 1
                continue
            try:
                handle = self._read_handle(workspace_id)
            except WorkspaceError:
                refused += 1
                continue
            created = _parse_created_at(handle.created_at)
            if created is None or created > cutoff:
                kept += 1
                continue
            try:
                await self.destroy(workspace_id)
            except WorkspaceError:
                refused += 1
                continue
            destroyed.append(workspace_id)
        return WorkspaceGcResult(
            configured=True,
            ttl_seconds=ttl,
            destroyed=destroyed,
            kept=kept,
            refused=refused,
        )

    async def health(self) -> WorkspaceHealth:
        try:
            root = self._ensure_root()
        except WorkspaceError as exc:
            ttl = configured_workspace_ttl_seconds()
            return WorkspaceHealth(
                provider=self.provider_id,
                status="unavailable",
                backend="filesystem",
                detail=str(exc),
                destroy=True,
                gc="configured" if ttl is not None else "unconfigured",
                ttl_seconds=ttl,
            )
        writable = os.access(root, os.W_OK)
        ttl = configured_workspace_ttl_seconds()
        return WorkspaceHealth(
            provider=self.provider_id,
            status="healthy" if writable else "unavailable",
            backend="filesystem",
            root=str(root),
            detail="Local filesystem sandbox" if writable else "Workspace root is not writable",
            destroy=True,
            gc="configured" if ttl is not None else "unconfigured",
            ttl_seconds=ttl,
        )


def build_workspace_provider(root: Path | str | None = None) -> WorkspaceProvider:
    """Production factory. Local filesystem only in this slice — no Docker."""
    return LocalFilesystemWorkspaceProvider(root=root)
