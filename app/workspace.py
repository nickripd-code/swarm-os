"""WorkspaceProvider seam: isolated per-mission/per-agent filesystem sandboxes.

Default backend is a local directory under a configurable root. Path traversal
and writes outside that root fail closed. An explicit ``SWARM_WORKSPACE_E2B``
opt-in selects a remote E2B sandbox instead; a missing key does not fall back
to the local disk. This module does not grant a host shell or destroy sandboxes.
Never log or return credentials.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field

from .models import FailureClass, utcnow

META_NAME = ".swarm-workspace.json"
MAX_PATH_BYTES = 256
MAX_CONTENT_BYTES = 1_048_576
DEFAULT_ROOT_NAME = "swarm-workspaces"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
E2B_API_BASE = "https://api.e2b.app"
E2B_SANDBOX_HOST = "https://sandbox.e2b.app"
E2B_ENVD_PORT = "49983"
E2B_SANDBOX_HOME = "/home/user"
E2B_TEMPLATE_DEFAULT = "base"
E2B_TTL_DEFAULT_SECONDS = 300
E2B_TTL_MIN_SECONDS = 15
E2B_TTL_MAX_SECONDS = 3600
E2B_HTTP_TIMEOUT = 20.0
_SANDBOX_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TEMPLATE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


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
    remote: bool = False
    ttl_seconds: int | None = None
    internet: bool | None = None


class WorkspaceProvider(ABC):
    """Provider-neutral isolated workspace API owned by Swarm OS.

    Local filesystem is the default. The E2B adapter is a separate opt-in.
    Destroy / GC is not part of this contract yet.
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


def workspace_e2b_opted_in(raw: str | None = None) -> bool:
    text = (raw if raw is not None else os.getenv("SWARM_WORKSPACE_E2B", "")).strip().lower()
    return text in TRUE_VALUES


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE_VALUES


def e2b_ttl_seconds() -> int:
    raw = os.getenv("SWARM_WORKSPACE_E2B_TTL_SECONDS", "").strip()
    if not raw:
        return E2B_TTL_DEFAULT_SECONDS
    if not raw.isdigit():
        raise WorkspaceError("E2B TTL is invalid", FailureClass.TOOL_FAILURE)
    value = int(raw)
    if value < E2B_TTL_MIN_SECONDS or value > E2B_TTL_MAX_SECONDS:
        raise WorkspaceError("E2B TTL is outside the allowed range", FailureClass.TOOL_FAILURE)
    return value


def e2b_template_id() -> str:
    raw = os.getenv("SWARM_WORKSPACE_E2B_TEMPLATE", E2B_TEMPLATE_DEFAULT).strip() or E2B_TEMPLATE_DEFAULT
    if not _TEMPLATE_RE.fullmatch(raw):
        raise WorkspaceError("E2B template id is invalid", FailureClass.TOOL_FAILURE)
    return raw


def e2b_allow_internet() -> bool:
    """Default deny. Internet egress is a separate explicit opt-in."""
    return _env_flag("SWARM_WORKSPACE_E2B_ALLOW_INTERNET")


def _logical_sandbox_path(sandbox_id: str, relative: str) -> Path:
    rel = normalize_relpath(relative, allow_dot=True)
    base = Path("e2b-sandbox") / sandbox_id / "home" / "user"
    if rel == ".":
        return base
    return base.joinpath(*rel.split("/"))


def _sandbox_file_path(relative: str) -> str:
    rel = normalize_relpath(relative)
    if Path(rel).name == META_NAME:
        raise WorkspaceError("Workspace metadata is reserved", FailureClass.POLICY_REFUSAL)
    return f"{E2B_SANDBOX_HOME}/{rel}"


def _classify_status(status: int, *, missing: str, missing_class: FailureClass) -> WorkspaceError:
    if status in {401, 403}:
        return WorkspaceError("E2B authorization failed", FailureClass.AUTHORIZATION_REQUIRED)
    if status == 404:
        return WorkspaceError(missing, missing_class)
    if status == 429:
        return WorkspaceError("E2B rate limit reached", FailureClass.RATE_LIMIT)
    if status in {408, 504}:
        return WorkspaceError("E2B request timed out", FailureClass.TIMEOUT)
    if status >= 500:
        return WorkspaceError("E2B is unavailable", FailureClass.PROVIDER_OUTAGE)
    return WorkspaceError("E2B request failed", FailureClass.TOOL_FAILURE)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise WorkspaceError("E2B returned invalid JSON", FailureClass.TOOL_FAILURE) from exc
    if not isinstance(payload, dict):
        raise WorkspaceError("E2B returned an invalid response", FailureClass.TOOL_FAILURE)
    return payload


def _metadata_strings(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise WorkspaceError("E2B sandbox metadata is missing", FailureClass.TOOL_FAILURE)
    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise WorkspaceError("E2B sandbox metadata is invalid", FailureClass.TOOL_FAILURE)
        cleaned[key] = item
    return cleaned


@dataclass
class E2BSandboxRecord:
    """In-process sandbox handle. The access token is never serialized."""

    sandbox_id: str
    metadata: dict[str, str]
    access_token: str | None = None
    state: str | None = None
    allow_internet_access: bool | None = None
    end_at: str | None = None

    def __repr__(self) -> str:
        return f"E2BSandboxRecord(sandbox_id={self.sandbox_id!r}, state={self.state!r})"


class E2BSandboxClient(ABC):
    """Thin E2B control-plane and envd file seam. Tests inject a fake."""

    @abstractmethod
    async def create_sandbox(
        self,
        *,
        metadata: dict[str, str],
        timeout_seconds: int,
        allow_internet_access: bool,
    ) -> E2BSandboxRecord:
        raise NotImplementedError

    @abstractmethod
    async def find_workspace(self, workspace_id: UUID) -> E2BSandboxRecord:
        raise NotImplementedError

    @abstractmethod
    async def write_text(self, record: E2BSandboxRecord, path: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read_text(self, record: E2BSandboxRecord, path: str) -> str:
        raise NotImplementedError


class HttpxE2BClient(E2BSandboxClient):
    """Real E2B HTTP client. Callers pass a transport in tests; production uses the network."""

    def __init__(
        self,
        api_key: str,
        *,
        template_id: str = E2B_TEMPLATE_DEFAULT,
        transport: httpx.AsyncBaseTransport | None = None,
        api_base: str = E2B_API_BASE,
        sandbox_host: str = E2B_SANDBOX_HOST,
    ):
        self._api_key = api_key
        self.template_id = template_id
        self._transport = transport
        self._api_base = api_base.rstrip("/")
        self._sandbox_host = sandbox_host.rstrip("/")

    def __repr__(self) -> str:
        return f"HttpxE2BClient(template_id={self.template_id!r})"

    async def create_sandbox(
        self,
        *,
        metadata: dict[str, str],
        timeout_seconds: int,
        allow_internet_access: bool,
    ) -> E2BSandboxRecord:
        body: dict[str, Any] = {
            "templateID": self.template_id,
            "timeout": timeout_seconds,
            "secure": True,
            "allow_internet_access": allow_internet_access,
            "metadata": metadata,
        }
        if any(self._api_key and self._api_key in value for value in metadata.values()):
            raise WorkspaceError("E2B sandbox metadata is invalid", FailureClass.TOOL_FAILURE)
        if not allow_internet_access:
            body["network"] = {"denyOut": ["0.0.0.0/0"]}
        response = await self._send("POST", f"{self._api_base}/sandboxes", json_body=body, api=True)
        if response.status_code != 201:
            raise _classify_status(response.status_code, missing="E2B sandbox was not found", missing_class=FailureClass.TOOL_MISSING)
        payload = _json_object(response)
        sandbox_id = payload.get("sandboxID")
        token = payload.get("envdAccessToken")
        if not isinstance(sandbox_id, str) or not _SANDBOX_ID_RE.fullmatch(sandbox_id):
            raise WorkspaceError("E2B returned an invalid sandbox id", FailureClass.TOOL_FAILURE)
        if not isinstance(token, str) or not token.strip():
            raise WorkspaceError("E2B sandbox access token is missing", FailureClass.AUTHORIZATION_REQUIRED)
        return E2BSandboxRecord(
            sandbox_id=sandbox_id,
            metadata=dict(metadata),
            access_token=token,
            state="running",
            allow_internet_access=allow_internet_access,
        )

    async def find_workspace(self, workspace_id: UUID) -> E2BSandboxRecord:
        wanted = str(workspace_id)
        response = await self._send(
            "GET",
            f"{self._api_base}/v2/sandboxes",
            params={"metadata": f"swarm_workspace_id={wanted}"},
            api=True,
        )
        if response.status_code != 200:
            raise _classify_status(
                response.status_code,
                missing="Workspace not found",
                missing_class=FailureClass.TOOL_MISSING,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkspaceError("E2B returned invalid JSON", FailureClass.TOOL_FAILURE) from exc
        if not isinstance(payload, list):
            raise WorkspaceError("E2B returned an invalid sandbox list", FailureClass.TOOL_FAILURE)
        matches = [
            item for item in payload
            if isinstance(item, dict) and isinstance(item.get("metadata"), dict)
            and item["metadata"].get("swarm_workspace_id") == wanted
        ]
        if not matches:
            if response.headers.get("X-Next-Token"):
                raise WorkspaceError("E2B sandbox list was incomplete", FailureClass.TOOL_FAILURE)
            raise WorkspaceError("Workspace not found", FailureClass.TOOL_MISSING)
        if len(matches) > 1:
            raise WorkspaceError("E2B returned more than one sandbox for this workspace", FailureClass.TOOL_FAILURE)
        sandbox_id = matches[0].get("sandboxID")
        if not isinstance(sandbox_id, str) or not _SANDBOX_ID_RE.fullmatch(sandbox_id):
            raise WorkspaceError("E2B returned an invalid sandbox id", FailureClass.TOOL_FAILURE)
        detail = await self._send("GET", f"{self._api_base}/sandboxes/{sandbox_id}", api=True)
        if detail.status_code != 200:
            raise _classify_status(
                detail.status_code,
                missing="Workspace not found",
                missing_class=FailureClass.TOOL_MISSING,
            )
        return self._record_from_detail(_json_object(detail), expect_workspace=wanted)

    async def write_text(self, record: E2BSandboxRecord, path: str, content: str) -> None:
        response = await self._send(
            "POST",
            f"{self._sandbox_host}/files",
            params={"path": path},
            content=content.encode("utf-8"),
            headers=self._envd_headers(record),
            api=False,
        )
        if response.status_code not in range(200, 300):
            raise _classify_status(response.status_code, missing="File not found", missing_class=FailureClass.TOOL_FAILURE)

    async def read_text(self, record: E2BSandboxRecord, path: str) -> str:
        response = await self._send(
            "GET",
            f"{self._sandbox_host}/files",
            params={"path": path},
            headers=self._envd_headers(record),
            api=False,
        )
        if response.status_code not in range(200, 300):
            raise _classify_status(response.status_code, missing="File not found", missing_class=FailureClass.TOOL_FAILURE)
        raw = response.content
        if b"\x00" in raw:
            raise WorkspaceError("Binary content is not allowed", FailureClass.TOOL_FAILURE)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError("Workspace file is not utf-8 text", FailureClass.TOOL_FAILURE) from None

    def _record_from_detail(self, payload: dict[str, Any], *, expect_workspace: str) -> E2BSandboxRecord:
        sandbox_id = payload.get("sandboxID")
        if not isinstance(sandbox_id, str) or not _SANDBOX_ID_RE.fullmatch(sandbox_id):
            raise WorkspaceError("E2B returned an invalid sandbox id", FailureClass.TOOL_FAILURE)
        metadata = _metadata_strings(payload.get("metadata"))
        if metadata.get("swarm_workspace_id") != expect_workspace:
            raise WorkspaceError("E2B sandbox metadata does not match the workspace", FailureClass.TOOL_FAILURE)
        token = payload.get("envdAccessToken")
        if token is not None and not isinstance(token, str):
            raise WorkspaceError("E2B sandbox access token is invalid", FailureClass.AUTHORIZATION_REQUIRED)
        if isinstance(token, str) and not token.strip():
            token = None
        internet = payload.get("allowInternetAccess")
        if internet is not None and not isinstance(internet, bool):
            raise WorkspaceError("E2B sandbox network policy is invalid", FailureClass.TOOL_FAILURE)
        state = payload.get("state")
        if not isinstance(state, str):
            raise WorkspaceError("E2B sandbox state is missing", FailureClass.TOOL_FAILURE)
        end_at = payload.get("endAt")
        return E2BSandboxRecord(
            sandbox_id=sandbox_id,
            metadata=metadata,
            access_token=token,
            state=state,
            allow_internet_access=internet,
            end_at=end_at if isinstance(end_at, str) else None,
        )

    def _envd_headers(self, record: E2BSandboxRecord) -> dict[str, str]:
        if not record.access_token:
            raise WorkspaceError("E2B sandbox access token is missing", FailureClass.AUTHORIZATION_REQUIRED)
        if not _SANDBOX_ID_RE.fullmatch(record.sandbox_id):
            raise WorkspaceError("E2B sandbox id is invalid", FailureClass.TOOL_FAILURE)
        return {
            "E2b-Sandbox-Id": record.sandbox_id,
            "E2b-Sandbox-Port": E2B_ENVD_PORT,
            "X-Access-Token": record.access_token,
        }

    async def _send(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        api: bool,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        if api:
            request_headers["X-API-Key"] = self._api_key
            request_headers.setdefault("Accept", "application/json")
        if json_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        elif content is not None:
            request_headers.setdefault("Content-Type", "application/octet-stream")
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(E2B_HTTP_TIMEOUT, connect=5.0),
                trust_env=False,
                transport=self._transport,
            ) as client:
                return await client.request(
                    method,
                    url,
                    json=json_body,
                    params=params,
                    content=content,
                    headers=request_headers,
                )
        except httpx.TimeoutException:
            raise WorkspaceError("E2B request timed out", FailureClass.TIMEOUT) from None
        except httpx.RequestError:
            raise WorkspaceError("Could not reach E2B", FailureClass.PROVIDER_OUTAGE) from None


class E2BWorkspaceProvider(WorkspaceProvider):
    """Remote E2B filesystem sandbox. Not a host shell and not a local directory."""

    provider_id = "e2b"

    def __init__(
        self,
        client: E2BSandboxClient,
        *,
        ttl_seconds: int = E2B_TTL_DEFAULT_SECONDS,
        allow_internet: bool = False,
    ):
        if not isinstance(client, E2BSandboxClient):
            raise WorkspaceError("E2B client is not configured", FailureClass.TOOL_MISSING)
        if ttl_seconds < E2B_TTL_MIN_SECONDS or ttl_seconds > E2B_TTL_MAX_SECONDS:
            raise WorkspaceError("E2B TTL is outside the allowed range", FailureClass.TOOL_FAILURE)
        self._client = client
        self.ttl_seconds = ttl_seconds
        self.allow_internet = allow_internet
        self._records: dict[UUID, E2BSandboxRecord] = {}

    async def create(self, *, mission_id: UUID, agent_id: UUID | None = None) -> WorkspaceHandle:
        workspace_id = uuid4()
        metadata = {
            "swarm_workspace_id": str(workspace_id),
            "mission_id": str(mission_id),
        }
        if agent_id is not None:
            metadata["agent_id"] = str(agent_id)
        record = await self._client.create_sandbox(
            metadata=metadata,
            timeout_seconds=self.ttl_seconds,
            allow_internet_access=self.allow_internet,
        )
        self._require_record(record, workspace_id=workspace_id, mission_id=mission_id, agent_id=agent_id)
        self._records[workspace_id] = record
        return self._handle(record)

    async def get(self, workspace_id: UUID) -> WorkspaceHandle:
        record = await self._client.find_workspace(workspace_id)
        self._require_record(record, workspace_id=workspace_id)
        self._records[workspace_id] = record
        return self._handle(record)

    def path(self, workspace_id: UUID, relative: str = ".") -> Path:
        record = self._records.get(workspace_id)
        if record is None:
            raise WorkspaceError("Workspace not found", FailureClass.TOOL_MISSING)
        return _logical_sandbox_path(record.sandbox_id, relative)

    async def write_file(self, workspace_id: UUID, relative: str, content: str) -> None:
        if not isinstance(content, str):
            raise WorkspaceError("Workspace writes require string content", FailureClass.TOOL_FAILURE)
        if "\x00" in content:
            raise WorkspaceError("Binary content is not allowed", FailureClass.TOOL_FAILURE)
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise WorkspaceError("File content exceeds the size limit", FailureClass.TOOL_FAILURE)
        target = _sandbox_file_path(relative)
        record = await self._load(workspace_id)
        await self._client.write_text(record, target, content)

    async def read_file(self, workspace_id: UUID, relative: str) -> str:
        target = _sandbox_file_path(relative)
        record = await self._load(workspace_id)
        return await self._client.read_text(record, target)

    async def health(self) -> WorkspaceHealth:
        return WorkspaceHealth(
            provider=self.provider_id,
            status="healthy",
            backend="e2b",
            root=None,
            detail="E2B adapter is configured; the API was not probed and no sandbox was created",
            remote=True,
            ttl_seconds=self.ttl_seconds,
            internet=self.allow_internet,
        )

    async def _load(self, workspace_id: UUID) -> E2BSandboxRecord:
        cached = self._records.get(workspace_id)
        if cached is not None:
            return cached
        record = await self._client.find_workspace(workspace_id)
        self._require_record(record, workspace_id=workspace_id)
        self._records[workspace_id] = record
        return record

    def _require_record(
        self,
        record: E2BSandboxRecord,
        *,
        workspace_id: UUID,
        mission_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> None:
        if record.state != "running":
            raise WorkspaceError("E2B sandbox is not running", FailureClass.TOOL_FAILURE)
        if not record.access_token:
            raise WorkspaceError("E2B sandbox access token is missing", FailureClass.AUTHORIZATION_REQUIRED)
        if record.allow_internet_access is not self.allow_internet:
            raise WorkspaceError("E2B sandbox network policy does not match", FailureClass.TOOL_FAILURE)
        metadata = record.metadata
        if metadata.get("swarm_workspace_id") != str(workspace_id):
            raise WorkspaceError("E2B sandbox metadata does not match the workspace", FailureClass.TOOL_FAILURE)
        if mission_id is not None and metadata.get("mission_id") != str(mission_id):
            raise WorkspaceError("E2B sandbox metadata is missing the mission id", FailureClass.TOOL_FAILURE)
        if agent_id is not None and metadata.get("agent_id") != str(agent_id):
            raise WorkspaceError("E2B sandbox metadata is missing the agent id", FailureClass.TOOL_FAILURE)
        try:
            UUID(metadata["mission_id"])
            if metadata.get("agent_id"):
                UUID(metadata["agent_id"])
        except (KeyError, ValueError) as exc:
            raise WorkspaceError("E2B sandbox metadata is invalid", FailureClass.TOOL_FAILURE) from exc

    def _handle(self, record: E2BSandboxRecord) -> WorkspaceHandle:
        metadata = record.metadata
        agent_raw = metadata.get("agent_id") or None
        return WorkspaceHandle(
            id=UUID(metadata["swarm_workspace_id"]),
            mission_id=UUID(metadata["mission_id"]),
            agent_id=UUID(agent_raw) if agent_raw else None,
            path=str(_logical_sandbox_path(record.sandbox_id, ".")),
            provider=self.provider_id,
            created_at=utcnow().isoformat(),
        )


class ClosedE2BWorkspaceProvider(WorkspaceProvider):
    """Fail closed when remote E2B was requested but cannot be used. Never falls back to local."""

    provider_id = "e2b"

    def __init__(
        self,
        message: str,
        failure_class: FailureClass,
        *,
        status: Literal["unconfigured", "unavailable"],
    ):
        self._message = message
        self._failure_class = failure_class
        self._status = status

    def _fail(self) -> NoReturn:
        raise WorkspaceError(self._message, self._failure_class)

    async def create(self, *, mission_id: UUID, agent_id: UUID | None = None) -> WorkspaceHandle:
        self._fail()

    async def get(self, workspace_id: UUID) -> WorkspaceHandle:
        self._fail()

    def path(self, workspace_id: UUID, relative: str = ".") -> Path:
        self._fail()

    async def write_file(self, workspace_id: UUID, relative: str, content: str) -> None:
        self._fail()

    async def read_file(self, workspace_id: UUID, relative: str) -> str:
        self._fail()

    async def health(self) -> WorkspaceHealth:
        return WorkspaceHealth(
            provider=self.provider_id,
            status=self._status,
            backend="e2b",
            root=None,
            detail=self._message,
            remote=True,
            ttl_seconds=None,
            internet=None,
        )


def build_workspace_provider(root: Path | str | None = None) -> WorkspaceProvider:
    """Local filesystem unless ``SWARM_WORKSPACE_E2B`` explicitly selects E2B.

    A requested remote backend never falls back to the local root. Docker is not used.
    """
    if not workspace_e2b_opted_in():
        return LocalFilesystemWorkspaceProvider(root=root)
    api_key = os.getenv("E2B_API_KEY", "").strip()
    if not api_key:
        return ClosedE2BWorkspaceProvider(
            "E2B workspace is not configured",
            FailureClass.TOOL_MISSING,
            status="unconfigured",
        )
    try:
        ttl = e2b_ttl_seconds()
        template = e2b_template_id()
    except WorkspaceError as exc:
        return ClosedE2BWorkspaceProvider(str(exc), exc.failure_class, status="unavailable")
    return E2BWorkspaceProvider(
        HttpxE2BClient(api_key=api_key, template_id=template),
        ttl_seconds=ttl,
        allow_internet=e2b_allow_internet(),
    )
