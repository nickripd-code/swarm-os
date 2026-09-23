"""E2B WorkspaceProvider seed. Fakes and httpx.MockTransport only — no live E2B calls."""
from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx
import pytest

from app.health import workspace_health_status
from app.models import FailureClass, Mission
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.workspace import (
    ClosedE2BWorkspaceProvider,
    E2BSandboxClient,
    E2BSandboxRecord,
    E2BWorkspaceProvider,
    HttpxE2BClient,
    LocalFilesystemWorkspaceProvider,
    WorkspaceError,
    build_workspace_provider,
    e2b_ttl_seconds,
    workspace_e2b_opted_in,
)

SECRET = "e2b-test-key"
TOKEN = "envd-test-token"
SANDBOX_ID = "sbx_test_1"


class FakeE2BClient(E2BSandboxClient):
    def __init__(
        self,
        *,
        fail: WorkspaceError | None = None,
        state: str = "running",
        reported_internet: bool | None = None,
    ):
        self.fail = fail
        self.state = state
        self.reported_internet = reported_internet
        self.records: dict[str, E2BSandboxRecord] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.writes: list[str] = []
        self.created: list[dict] = []

    async def create_sandbox(self, *, metadata, timeout_seconds, allow_internet_access):
        if self.fail:
            raise self.fail
        self.created.append({
            "metadata": dict(metadata),
            "timeout_seconds": timeout_seconds,
            "allow_internet_access": allow_internet_access,
        })
        internet = allow_internet_access if self.reported_internet is None else self.reported_internet
        record = E2BSandboxRecord(
            sandbox_id=f"sbx{len(self.records) + 1}",
            metadata=dict(metadata),
            access_token=TOKEN,
            state=self.state,
            allow_internet_access=internet,
        )
        self.records[metadata["swarm_workspace_id"]] = record
        return record

    async def find_workspace(self, workspace_id: UUID) -> E2BSandboxRecord:
        record = self.records.get(str(workspace_id))
        if record is None:
            raise WorkspaceError("Workspace not found", FailureClass.TOOL_MISSING)
        return record

    async def write_text(self, record: E2BSandboxRecord, path: str, content: str) -> None:
        self.writes.append(path)
        self.files[(record.sandbox_id, path)] = content

    async def read_text(self, record: E2BSandboxRecord, path: str) -> str:
        try:
            return self.files[(record.sandbox_id, path)]
        except KeyError as exc:
            raise WorkspaceError("File not found", FailureClass.TOOL_FAILURE) from exc


def _clear_e2b(monkeypatch):
    for name in (
        "SWARM_WORKSPACE_E2B",
        "E2B_API_KEY",
        "SWARM_WORKSPACE_E2B_TTL_SECONDS",
        "SWARM_WORKSPACE_E2B_TEMPLATE",
        "SWARM_WORKSPACE_E2B_ALLOW_INTERNET",
    ):
        monkeypatch.delenv(name, raising=False)


def _opt_in(monkeypatch, *, key: str | None = SECRET, ttl: str | None = None, internet: str | None = None):
    _clear_e2b(monkeypatch)
    monkeypatch.setenv("SWARM_WORKSPACE_E2B", "1")
    if key is not None:
        monkeypatch.setenv("E2B_API_KEY", key)
    if ttl is not None:
        monkeypatch.setenv("SWARM_WORKSPACE_E2B_TTL_SECONDS", ttl)
    if internet is not None:
        monkeypatch.setenv("SWARM_WORKSPACE_E2B_ALLOW_INTERNET", internet)


def test_e2b_flag_is_explicit(monkeypatch):
    _clear_e2b(monkeypatch)
    assert workspace_e2b_opted_in() is False
    monkeypatch.setenv("SWARM_WORKSPACE_E2B", "yes")
    assert workspace_e2b_opted_in() is True
    monkeypatch.setenv("SWARM_WORKSPACE_E2B", "0")
    assert workspace_e2b_opted_in() is False


def test_key_alone_stays_on_local_filesystem(tmp_path, monkeypatch):
    _clear_e2b(monkeypatch)
    monkeypatch.setenv("E2B_API_KEY", SECRET)
    monkeypatch.setenv("SWARM_WORKSPACE_ROOT", str(tmp_path / "local"))
    provider = build_workspace_provider()
    assert isinstance(provider, LocalFilesystemWorkspaceProvider)


@pytest.mark.asyncio
async def test_unconfigured_remote_does_not_fall_back_to_local(tmp_path, monkeypatch):
    root = tmp_path / "should-not-exist"
    _opt_in(monkeypatch, key=None)
    monkeypatch.setenv("SWARM_WORKSPACE_ROOT", str(root))
    provider = build_workspace_provider()
    assert isinstance(provider, ClosedE2BWorkspaceProvider)
    with pytest.raises(WorkspaceError) as exc:
        await provider.create(mission_id=uuid4())
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert SECRET not in str(exc.value)
    assert not root.exists()
    status = await workspace_health_status()
    assert status["configured"] is False
    assert status["provider"] == "e2b"
    assert status["status"] == "unconfigured"
    assert status["fallback"] is False
    assert status["docker"] is False
    assert status["remote"] is True
    assert status["root"] is None
    assert SECRET not in str(status)


@pytest.mark.asyncio
async def test_invalid_ttl_fails_closed(monkeypatch):
    _opt_in(monkeypatch, ttl="99999")
    provider = build_workspace_provider()
    assert isinstance(provider, ClosedE2BWorkspaceProvider)
    health = await provider.health()
    assert health.status == "unavailable"
    with pytest.raises(WorkspaceError) as exc:
        await provider.create(mission_id=uuid4())
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert SECRET not in str(exc.value)
    _opt_in(monkeypatch, ttl="14")
    with pytest.raises(WorkspaceError):
        e2b_ttl_seconds()
    _opt_in(monkeypatch, ttl="300")
    assert e2b_ttl_seconds() == 300


@pytest.mark.asyncio
async def test_fake_client_roundtrip_carries_metadata_and_blocks_escape(tmp_path):
    client = FakeE2BClient()
    provider = E2BWorkspaceProvider(client, ttl_seconds=90, allow_internet=False)
    mission_id = uuid4()
    agent_id = uuid4()
    missing = uuid4()
    with pytest.raises(WorkspaceError) as path_exc:
        provider.path(missing, "a.txt")
    assert path_exc.value.failure_class == FailureClass.TOOL_MISSING
    handle = await provider.create(mission_id=mission_id, agent_id=agent_id)
    assert handle.provider == "e2b"
    assert handle.mission_id == mission_id
    assert handle.agent_id == agent_id
    assert client.created[0]["metadata"]["mission_id"] == str(mission_id)
    assert client.created[0]["metadata"]["agent_id"] == str(agent_id)
    assert client.created[0]["timeout_seconds"] == 90
    assert client.created[0]["allow_internet_access"] is False
    logical = provider.path(handle.id, "notes/hello.txt")
    assert logical.is_absolute() is False
    assert not logical.exists()
    assert TOKEN not in str(handle.model_dump())
    await provider.write_file(handle.id, "notes/hello.txt", "hello sandbox")
    assert await provider.read_file(handle.id, "notes/hello.txt") == "hello sandbox"
    assert client.files[("sbx1", "/home/user/notes/hello.txt")] == "hello sandbox"
    with pytest.raises(WorkspaceError) as escape:
        await provider.write_file(handle.id, "../escape.txt", "pwned")
    assert escape.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "../" not in "".join(client.writes)
    with pytest.raises(WorkspaceError) as reserved:
        await provider.write_file(handle.id, ".swarm-workspace.json", "{}")
    assert reserved.value.failure_class == FailureClass.POLICY_REFUSAL
    loaded = await provider.get(handle.id)
    assert loaded.id == handle.id
    assert TOKEN not in str(loaded.model_dump())
    health = await provider.health()
    assert health.status == "healthy"
    assert health.remote is True
    assert health.internet is False
    assert health.ttl_seconds == 90
    assert "not probed" in (health.detail or "")
    assert TOKEN not in str(health.model_dump())


@pytest.mark.asyncio
async def test_runtime_hook_maps_e2b_errors(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    client = FakeE2BClient()
    runtime = SwarmRuntime(store, workspaces=E2BWorkspaceProvider(client))
    mission = Mission(goal="sandbox")
    store.save_mission(mission)
    handle = await runtime.create_workspace(mission)
    await runtime.write_workspace_file(handle.id, "out.txt", "ok")
    assert await runtime.read_workspace_file(handle.id, "out.txt") == "ok"
    with pytest.raises(PolicyError) as exc:
        await runtime.read_workspace_file(uuid4(), "missing.txt")
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_paused_or_open_network_sandbox_is_not_success():
    paused = FakeE2BClient(state="paused")
    provider = E2BWorkspaceProvider(paused)
    with pytest.raises(WorkspaceError) as exc:
        await provider.create(mission_id=uuid4())
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert provider._records == {}
    opened = FakeE2BClient(reported_internet=True)
    provider = E2BWorkspaceProvider(opened, allow_internet=False)
    with pytest.raises(WorkspaceError) as network_exc:
        await provider.create(mission_id=uuid4())
    assert network_exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert "policy" in str(network_exc.value)


def _created_payload(**overrides):
    payload = {
        "templateID": "base",
        "sandboxID": SANDBOX_ID,
        "clientID": "client",
        "envdVersion": "0.1.0",
        "envdAccessToken": TOKEN,
    }
    payload.update(overrides)
    return payload


def _detail(metadata: dict[str, str], **overrides):
    payload = {
        "templateID": "base",
        "sandboxID": SANDBOX_ID,
        "clientID": "client",
        "startedAt": "2026-09-23T00:00:00Z",
        "cpuCount": 2,
        "memoryMB": 512,
        "diskSizeMB": 1024,
        "endAt": "2026-09-23T00:05:00Z",
        "state": "running",
        "envdVersion": "0.1.0",
        "envdAccessToken": TOKEN,
        "allowInternetAccess": False,
        "metadata": metadata,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_http_client_create_read_write_and_redaction():
    seen = {"files": {}, "create": None, "file_hosts": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "sandbox.e2b.app":
            seen["file_hosts"].append(dict(request.headers))
            assert "x-api-key" not in {key.lower() for key in request.headers}
            assert request.headers["X-Access-Token"] == TOKEN
            assert SECRET not in str(request.url)
            path = request.url.params["path"]
            if request.method == "POST":
                seen["files"][path] = request.content.decode()
                return httpx.Response(200, content=b"")
            if path not in seen["files"]:
                return httpx.Response(404, json={"code": 404, "message": SECRET})
            return httpx.Response(200, content=seen["files"][path].encode())
        assert request.headers["X-API-Key"] == SECRET
        if request.method == "POST" and request.url.path == "/sandboxes":
            body = json.loads(request.content)
            seen["create"] = body
            return httpx.Response(201, json=_created_payload())
        if request.method == "GET" and request.url.path == "/v2/sandboxes":
            metadata = seen["create"]["metadata"]
            return httpx.Response(200, json=[{
                "sandboxID": SANDBOX_ID,
                "metadata": metadata,
                "state": "running",
            }])
        if request.method == "GET" and request.url.path == f"/sandboxes/{SANDBOX_ID}":
            return httpx.Response(200, json=_detail(seen["create"]["metadata"]))
        return httpx.Response(500, json={"code": 500, "message": SECRET})

    client = HttpxE2BClient(api_key=SECRET, transport=httpx.MockTransport(handler))
    provider = E2BWorkspaceProvider(client, ttl_seconds=300, allow_internet=False)
    mission_id = uuid4()
    agent_id = uuid4()
    handle = await provider.create(mission_id=mission_id, agent_id=agent_id)
    body = seen["create"]
    assert body["timeout"] == 300
    assert body["secure"] is True
    assert body["allow_internet_access"] is False
    assert body["network"]["denyOut"] == ["0.0.0.0/0"]
    assert body["metadata"]["mission_id"] == str(mission_id)
    assert body["metadata"]["agent_id"] == str(agent_id)
    assert SECRET not in json.dumps(body)
    await provider.write_file(handle.id, "notes/hello.txt", "remote")
    assert await provider.read_file(handle.id, "notes/hello.txt") == "remote"
    assert seen["files"]["/home/user/notes/hello.txt"] == "remote"
    loaded = await provider.get(handle.id)
    assert loaded.mission_id == mission_id
    assert loaded.agent_id == agent_id
    assert TOKEN not in str(loaded.model_dump())
    assert SECRET not in repr(client)
    with pytest.raises(WorkspaceError) as missing:
        await provider.read_file(handle.id, "notes/missing.txt")
    assert missing.value.failure_class == FailureClass.TOOL_FAILURE
    assert SECRET not in str(missing.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error", "failure_class"),
    [
        (401, None, FailureClass.AUTHORIZATION_REQUIRED),
        (403, None, FailureClass.AUTHORIZATION_REQUIRED),
        (429, None, FailureClass.RATE_LIMIT),
        (503, None, FailureClass.PROVIDER_OUTAGE),
        (504, None, FailureClass.TIMEOUT),
        (400, None, FailureClass.TOOL_FAILURE),
        (None, httpx.ReadTimeout("timed out"), FailureClass.TIMEOUT),
        (None, httpx.ConnectError("offline"), FailureClass.PROVIDER_OUTAGE),
    ],
)
async def test_http_errors_are_classified_and_redacted(status, error, failure_class):
    def handler(request: httpx.Request) -> httpx.Response:
        if error is not None:
            raise error
        return httpx.Response(status, json={"code": status, "message": SECRET})

    client = HttpxE2BClient(api_key=SECRET, transport=httpx.MockTransport(handler))
    provider = E2BWorkspaceProvider(client)
    with pytest.raises(WorkspaceError) as exc:
        await provider.create(mission_id=uuid4())
    assert exc.value.failure_class == failure_class
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_create_without_id_or_token_is_not_success():
    def without_id(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"templateID": "base", "clientID": "c", "envdVersion": "0"})

    provider = E2BWorkspaceProvider(HttpxE2BClient(api_key=SECRET, transport=httpx.MockTransport(without_id)))
    with pytest.raises(WorkspaceError) as exc:
        await provider.create(mission_id=uuid4())
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE

    def without_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_created_payload(envdAccessToken=None))

    provider = E2BWorkspaceProvider(HttpxE2BClient(api_key=SECRET, transport=httpx.MockTransport(without_token)))
    with pytest.raises(WorkspaceError) as token_exc:
        await provider.create(mission_id=uuid4())
    assert token_exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


@pytest.mark.asyncio
async def test_internet_opt_in_is_explicit_and_duplicate_sandbox_fails(monkeypatch):
    bodies = []

    def allow(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json=_created_payload())

    client = HttpxE2BClient(api_key=SECRET, transport=httpx.MockTransport(allow))
    provider = E2BWorkspaceProvider(client, allow_internet=True)
    await provider.create(mission_id=uuid4())
    assert bodies[0]["allow_internet_access"] is True
    assert "network" not in bodies[0]

    def duplicates(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/sandboxes":
            item = {"sandboxID": SANDBOX_ID, "metadata": {"swarm_workspace_id": request.url.params["metadata"].split("=", 1)[1]}}
            return httpx.Response(200, json=[item, dict(item)])
        return httpx.Response(500, json={"code": 500, "message": "nope"})

    client = HttpxE2BClient(api_key=SECRET, transport=httpx.MockTransport(duplicates))
    provider = E2BWorkspaceProvider(client)
    with pytest.raises(WorkspaceError) as exc:
        await provider.get(uuid4())
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_configured_health_does_not_probe_or_leak(monkeypatch):
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("health must not call E2B")

    _opt_in(monkeypatch, ttl="120", internet="1")
    provider = build_workspace_provider()
    assert isinstance(provider, E2BWorkspaceProvider)
    health = await provider.health()
    assert health.remote is True
    assert health.ttl_seconds == 120
    assert health.internet is True
    assert health.root is None
    assert SECRET not in str(health.model_dump())
    assert TOKEN not in str(health.model_dump())
    status = await workspace_health_status()
    assert status["configured"] is True
    assert status["provider"] == "e2b"
    assert status["fallback"] is False
    assert status["remote"] is True
    assert status["ttl_seconds"] == 120
    assert status["internet"] is True
    assert SECRET not in str(status)
    unused = HttpxE2BClient(api_key=SECRET, transport=httpx.MockTransport(boom))
    assert "not probed" in (await E2BWorkspaceProvider(unused, ttl_seconds=120, allow_internet=True).health()).detail
