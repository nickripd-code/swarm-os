"""WorkspaceProvider seam: isolated per-mission/per-agent filesystem sandboxes.

Default backend is a local directory under a configurable root. Path traversal,
symlink escapes, and deletes outside that root fail closed. Destroy and bounded
GC remove only those sandboxed trees. Docker/remote backends are later.
Never log or return credentials.
"""
from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .models import FailureClass, utcnow

META_NAME = ".swarm-workspace.json"
MAX_PATH_BYTES = 256
MAX_CONTENT_BYTES = 1_048_576
DEFAULT_ROOT_NAME = "swarm-workspaces"
# Retention for bounded local GC. Not a CPU/RAM/network quota and not Docker.
DEFAULT_WORKSPACE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_TERMINAL_RETENTION_SECONDS = 60 * 60
MAX_RETENTION_SECONDS = 366 * 24 * 60 * 60
MAX_GC_CANDIDATES = 200


class WorkspaceError(Exception):
    """Safe workspace failure. Messages must never contain credentials."""

    def __init__(self, message: str, failure_class: FailureClass = FailureClass.TOOL_FAILURE):
        super().__init__(message)
        self.failure_class = failure_class
        self.removed: list[UUID] = []


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


class WorkspaceGcResult(BaseModel):
    """Honest GC outcome. `removed` lists only directories that were deleted.

    `ok` is false when the sweep hit the candidate cap and left other children
    unexamined. A failed delete raises WorkspaceError instead of returning here.
    """

    removed: list[UUID] = Field(default_factory=list)
    retained: list[UUID] = Field(default_factory=list)
    truncated: bool = False
    ok: bool = True


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
    async def destroy(self, workspace_id: UUID) -> WorkspaceHandle:
        """Remove one sandbox directory. Missing is TOOL_MISSING."""
        raise NotImplementedError

    @abstractmethod
    async def destroy_mission(self, mission_id: UUID) -> list[UUID]:
        """Remove every sandbox whose metadata mission_id matches."""
        raise NotImplementedError

    @abstractmethod
    async def gc(
        self,
        *,
        now: datetime | None = None,
        ttl_seconds: float | None = None,
        terminal_missions: Mapping[UUID, datetime] | None = None,
        terminal_retention_seconds: float | None = None,
    ) -> WorkspaceGcResult:
        """Remove orphan and expired sandbox directories under the root."""
        raise NotImplementedError

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
    except (ValueError, OSError):
        return False


def _require_uuid(value: UUID, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    raise WorkspaceError(f"{label} is invalid", FailureClass.POLICY_REFUSAL)


def _directory_id(name: str) -> UUID | None:
    try:
        parsed = UUID(name)
    except ValueError:
        return None
    if str(parsed) != name:
        return None
    return parsed


def _as_utc(value: datetime, *, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise WorkspaceError(f"{label} is invalid", FailureClass.POLICY_REFUSAL)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_created_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _retention_seconds(value: float | None, *, env_name: str, default: float, label: str) -> float:
    if value is None:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return float(default)
        try:
            value = float(raw)
        except ValueError as exc:
            raise WorkspaceError(f"{label} is invalid", FailureClass.POLICY_REFUSAL) from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkspaceError(f"{label} is invalid", FailureClass.POLICY_REFUSAL)
    if value <= 0 or value > MAX_RETENTION_SECONDS:
        raise WorkspaceError(f"{label} is invalid", FailureClass.POLICY_REFUSAL)
    return float(value)


def _terminal_index(value: Mapping[UUID, datetime] | None) -> dict[UUID, datetime]:
    if value is None:
        return {}
    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        raise WorkspaceError("Terminal mission ages are invalid", FailureClass.POLICY_REFUSAL)
    parsed: dict[UUID, datetime] = {}
    for key, stamp in value.items():
        if not isinstance(key, UUID):
            raise WorkspaceError("Terminal mission ages are invalid", FailureClass.POLICY_REFUSAL)
        parsed[key] = _as_utc(stamp, label="Terminal mission time")
    return parsed


def delete_sandbox_tree(directory: Path) -> None:
    """Remove a preflighted sandbox. Symlinks are refused and never followed."""
    if directory.is_symlink() or not directory.is_dir():
        raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
    for current, dirnames, filenames in os.walk(directory, topdown=False, followlinks=False):
        current_path = Path(current)
        if current_path.is_symlink():
            raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
        for name in filenames:
            entry = current_path / name
            if entry.is_symlink():
                raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
            entry.unlink()
        for name in dirnames:
            entry = current_path / name
            if entry.is_symlink():
                raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
            entry.rmdir()
    directory.rmdir()


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
        raw = root / str(workspace_id)
        if raw.is_symlink():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        try:
            target = raw.resolve()
        except OSError as exc:
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL) from exc
        if not _contained(target, root) or target == root:
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

    def _assert_recorded_path(self, payload: dict[str, Any], directory: Path, root: Path) -> None:
        recorded = payload.get("path")
        if not isinstance(recorded, str) or not recorded.strip():
            raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE)
        raw = Path(recorded)
        if not raw.is_absolute() or ".." in raw.parts:
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        try:
            resolved = raw.resolve()
        except OSError as exc:
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL) from exc
        if resolved != directory.resolve() or not _contained(resolved, root):
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)

    def _load_destroy_handle(self, directory: Path, root: Path) -> WorkspaceHandle:
        meta_path = directory / META_NAME
        if meta_path.is_symlink():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        if not meta_path.is_file():
            raise WorkspaceError("Workspace metadata is unreadable", FailureClass.TOOL_FAILURE)
        if not _contained(meta_path, directory):
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError("Workspace metadata is unreadable", FailureClass.TOOL_FAILURE) from exc
        if not isinstance(payload, dict):
            raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE)
        self._assert_recorded_path(payload, directory, root)
        if payload.get("id") != directory.name:
            raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE)
        payload = dict(payload)
        payload["path"] = str(directory)
        payload["provider"] = self.provider_id
        try:
            handle = WorkspaceHandle.model_validate(payload)
        except Exception as exc:
            raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE) from exc
        if handle.id != UUID(directory.name) or not _contained(directory, root):
            raise WorkspaceError("Workspace metadata is invalid", FailureClass.TOOL_FAILURE)
        return handle

    def _assert_tree_contained(self, directory: Path, root: Path) -> None:
        if directory.is_symlink() or not directory.is_dir():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        if not _contained(directory, root) or directory.resolve() == root.resolve():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        for current, dirnames, filenames in os.walk(directory, followlinks=False):
            current_path = Path(current)
            if current_path.is_symlink() or not _contained(current_path, directory):
                raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
            for name in dirnames:
                entry = current_path / name
                if entry.is_symlink() or not _contained(entry, directory):
                    raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
            for name in filenames:
                entry = current_path / name
                if entry.is_symlink():
                    raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)
                try:
                    resolved = entry.resolve()
                except OSError as exc:
                    raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL) from exc
                if not _contained(resolved, directory):
                    raise WorkspaceError("Path traversal is not allowed", FailureClass.POLICY_REFUSAL)

    def _destroy_directory(self, directory: Path, root: Path) -> None:
        self._assert_tree_contained(directory, root)
        try:
            delete_sandbox_tree(directory)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceError("Workspace could not be destroyed", FailureClass.TOOL_FAILURE) from exc
        if directory.exists() or directory.is_symlink():
            raise WorkspaceError("Workspace could not be destroyed", FailureClass.TOOL_FAILURE)

    def _bounded_children(self, root: Path) -> tuple[list[Path], bool]:
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise WorkspaceError("Workspace root is unavailable", FailureClass.PROVIDER_OUTAGE) from exc
        truncated = len(children) > MAX_GC_CANDIDATES
        return children[:MAX_GC_CANDIDATES], truncated

    def _metadata_present(self, directory: Path) -> bool:
        meta_path = directory / META_NAME
        if meta_path.is_symlink():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        return meta_path.exists()

    def _require_sandbox_dir(self, child: Path, root: Path) -> Path:
        if _directory_id(child.name) is None:
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        if child.is_symlink() or not child.is_dir():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        try:
            directory = child.resolve()
        except OSError as exc:
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL) from exc
        if directory.parent != root.resolve() or not _contained(directory, root) or directory == root.resolve():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        return directory

    def _mtime(self, directory: Path) -> datetime:
        try:
            stamped = directory.lstat().st_mtime
        except OSError as exc:
            raise WorkspaceError("Workspace metadata is unreadable", FailureClass.TOOL_FAILURE) from exc
        return datetime.fromtimestamp(stamped, tz=timezone.utc)

    def _is_expired(self, created: datetime, now: datetime, seconds: float) -> bool:
        return (now - created).total_seconds() >= seconds

    async def destroy(self, workspace_id: UUID) -> WorkspaceHandle:
        workspace_id = _require_uuid(workspace_id, "workspace_id")
        root = self._ensure_root()
        directory = self._workspace_dir(workspace_id)
        if not directory.exists():
            raise WorkspaceError("Workspace not found", FailureClass.TOOL_MISSING)
        if directory.is_symlink() or not directory.is_dir():
            raise WorkspaceError("Workspace path escaped the sandbox root", FailureClass.POLICY_REFUSAL)
        handle = self._load_destroy_handle(directory, root)
        self._destroy_directory(directory, root)
        return handle

    async def destroy_mission(self, mission_id: UUID) -> list[UUID]:
        mission_id = _require_uuid(mission_id, "mission_id")
        root = self._ensure_root()
        children, truncated = self._bounded_children(root)
        if truncated:
            raise WorkspaceError(
                "Workspace sweep is bounded; mission destroy was not applied",
                FailureClass.POLICY_REFUSAL,
            )
        matches: list[tuple[Path, UUID]] = []
        for child in children:
            if _directory_id(child.name) is None:
                continue
            directory = self._require_sandbox_dir(child, root)
            if not self._metadata_present(directory):
                continue
            handle = self._load_destroy_handle(directory, root)
            if handle.mission_id == mission_id:
                self._assert_tree_contained(directory, root)
                matches.append((directory, handle.id))
        removed: list[UUID] = []
        for directory, workspace_id in matches:
            try:
                self._destroy_directory(directory, root)
            except WorkspaceError as exc:
                exc.removed = list(removed)
                raise
            removed.append(workspace_id)
        return removed

    def _plan_gc(
        self,
        children: list[Path],
        root: Path,
        now: datetime,
        ttl: float,
        terminal: dict[UUID, datetime],
        retention: float,
    ) -> tuple[list[tuple[Path, UUID]], list[UUID]]:
        remove: list[tuple[Path, UUID]] = []
        retained: list[UUID] = []
        for child in children:
            if _directory_id(child.name) is None:
                continue
            directory = self._require_sandbox_dir(child, root)
            if not self._metadata_present(directory):
                workspace_id = UUID(directory.name)
                if self._is_expired(self._mtime(directory), now, ttl):
                    self._assert_tree_contained(directory, root)
                    remove.append((directory, workspace_id))
                else:
                    retained.append(workspace_id)
                continue
            handle = self._load_destroy_handle(directory, root)
            created = _parse_created_at(handle.created_at)
            ended = terminal.get(handle.mission_id)
            stale = self._is_expired(created, now, ttl) or (
                ended is not None and self._is_expired(ended, now, retention)
            )
            if stale:
                self._assert_tree_contained(directory, root)
                remove.append((directory, handle.id))
            else:
                retained.append(handle.id)
        return remove, retained

    async def gc(
        self,
        *,
        now: datetime | None = None,
        ttl_seconds: float | None = None,
        terminal_missions: Mapping[UUID, datetime] | None = None,
        terminal_retention_seconds: float | None = None,
    ) -> WorkspaceGcResult:
        moment = utcnow() if now is None else _as_utc(now, label="now")
        ttl = _retention_seconds(
            ttl_seconds,
            env_name="SWARM_WORKSPACE_TTL_SECONDS",
            default=DEFAULT_WORKSPACE_TTL_SECONDS,
            label="Workspace TTL",
        )
        retention = _retention_seconds(
            terminal_retention_seconds,
            env_name="SWARM_WORKSPACE_TERMINAL_RETENTION_SECONDS",
            default=DEFAULT_TERMINAL_RETENTION_SECONDS,
            label="Workspace terminal retention",
        )
        terminal = _terminal_index(terminal_missions)
        root = self._ensure_root()
        children, truncated = self._bounded_children(root)
        remove, retained = self._plan_gc(children, root, moment, ttl, terminal, retention)
        removed: list[UUID] = []
        for directory, workspace_id in remove:
            try:
                self._destroy_directory(directory, root)
            except WorkspaceError as exc:
                exc.removed = list(removed)
                raise
            removed.append(workspace_id)
        return WorkspaceGcResult(
            removed=removed,
            retained=retained,
            truncated=truncated,
            ok=not truncated,
        )

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
