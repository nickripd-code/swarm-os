import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.health import workspace_health_status
from app.models import FailureClass, Mission, utcnow
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.workspace import (
    META_NAME,
    LocalFilesystemWorkspaceProvider,
    WorkspaceError,
    WorkspaceProvider,
    build_workspace_provider,
    configured_workspace_ttl_seconds,
    default_workspace_root,
    normalize_relpath,
)


def _provider(tmp_path: Path) -> LocalFilesystemWorkspaceProvider:
    return LocalFilesystemWorkspaceProvider(root=tmp_path / "workspaces")


@pytest.mark.asyncio
async def test_create_workspace_under_configured_root(tmp_path):
    root = tmp_path / "workspaces"
    provider = LocalFilesystemWorkspaceProvider(root=root)
    mission_id = uuid4()
    agent_id = uuid4()
    handle = await provider.create(mission_id=mission_id, agent_id=agent_id)
    assert isinstance(provider, WorkspaceProvider)
    assert handle.provider == "local"
    assert handle.mission_id == mission_id
    assert handle.agent_id == agent_id
    workspace_path = Path(handle.path)
    assert workspace_path.is_dir()
    assert workspace_path.resolve().is_relative_to(root.resolve())
    loaded = await provider.get(handle.id)
    assert loaded.id == handle.id
    assert provider.path(handle.id) == workspace_path.resolve()


@pytest.mark.asyncio
async def test_read_write_roundtrip_and_nested_path(tmp_path):
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())
    await provider.write_file(handle.id, "notes/hello.txt", "hello sandbox")
    assert await provider.read_file(handle.id, "notes/hello.txt") == "hello sandbox"
    nested = provider.path(handle.id, "notes/hello.txt")
    assert nested.is_file()
    assert nested.read_text(encoding="utf-8") == "hello sandbox"
    other = await provider.create(mission_id=uuid4())
    with pytest.raises(WorkspaceError) as exc:
        await provider.read_file(other.id, "notes/hello.txt")
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE


@pytest.mark.asyncio
@pytest.mark.parametrize("escape", ["../escape.txt", "foo/../../escape.txt", "/etc/passwd", "~/secret"])
async def test_path_escape_fails_closed(tmp_path, escape):
    root = tmp_path / "workspaces"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    provider = LocalFilesystemWorkspaceProvider(root=root)
    handle = await provider.create(mission_id=uuid4())
    with pytest.raises(WorkspaceError) as exc:
        await provider.write_file(handle.id, escape, "pwned")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(WorkspaceError) as read_exc:
        await provider.read_file(handle.id, escape)
    assert read_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(WorkspaceError) as path_exc:
        provider.path(handle.id, escape)
    assert path_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert not (tmp_path / "escape.txt").exists()
    assert outside.read_text(encoding="utf-8") == "secret"
    assert [path.name for path in Path(handle.path).iterdir()] == [META_NAME]


@pytest.mark.asyncio
async def test_symlink_escape_fails_closed(tmp_path):
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())
    secret = tmp_path / "secret.txt"
    secret.write_text("nope", encoding="utf-8")
    link = Path(handle.path) / "escape"
    link.symlink_to(secret)
    with pytest.raises(WorkspaceError) as exc:
        await provider.read_file(handle.id, "escape")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert secret.read_text(encoding="utf-8") == "nope"


@pytest.mark.asyncio
async def test_missing_workspace_is_classified(tmp_path):
    provider = _provider(tmp_path)
    missing = uuid4()
    with pytest.raises(WorkspaceError) as get_exc:
        await provider.get(missing)
    assert get_exc.value.failure_class == FailureClass.TOOL_MISSING
    with pytest.raises(WorkspaceError) as write_exc:
        await provider.write_file(missing, "a.txt", "x")
    assert write_exc.value.failure_class == FailureClass.TOOL_MISSING
    with pytest.raises(WorkspaceError) as read_exc:
        await provider.read_file(missing, "a.txt")
    assert read_exc.value.failure_class == FailureClass.TOOL_MISSING
    with pytest.raises(WorkspaceError) as path_exc:
        provider.path(missing, "a.txt")
    assert path_exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_reserved_metadata_cannot_be_overwritten(tmp_path):
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())
    with pytest.raises(WorkspaceError) as exc:
        await provider.write_file(handle.id, META_NAME, "{}")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    loaded = await provider.get(handle.id)
    assert loaded.id == handle.id


@pytest.mark.asyncio
async def test_runtime_hook_creates_isolated_workspace(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = _provider(tmp_path)
    runtime = SwarmRuntime(store, workspaces=provider)
    mission = Mission(goal="sandbox")
    store.save_mission(mission)
    handle = await runtime.create_workspace(mission)
    await runtime.write_workspace_file(handle.id, "out.txt", "ok")
    assert await runtime.read_workspace_file(handle.id, "out.txt") == "ok"
    assert Path(handle.path).resolve().is_relative_to((tmp_path / "workspaces").resolve())


@pytest.mark.asyncio
async def test_runtime_missing_workspace_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, workspaces=_provider(tmp_path))
    with pytest.raises(PolicyError) as exc:
        await runtime.read_workspace_file(uuid4(), "missing.txt")
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_health_is_truthful_and_does_not_expose_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_WORKSPACE_ROOT", str(tmp_path / "from-env"))
    monkeypatch.delenv("SWARM_WORKSPACE_TTL_SECONDS", raising=False)
    provider = build_workspace_provider()
    health = await provider.health()
    assert health.status == "healthy"
    assert health.provider == "local"
    assert health.backend == "filesystem"
    dumped = health.model_dump()
    assert "key" not in str(dumped).lower()
    assert "secret" not in str(dumped).lower()
    status = await workspace_health_status()
    assert status["configured"] is True
    assert status["provider"] == "local"
    assert status["status"] == "healthy"
    assert status["fallback"] is False
    assert status["docker"] is False
    assert status["destroy"] is True
    assert status["gc"] == "unconfigured"
    assert status["ttl_seconds"] is None
    assert Path(status["root"]).resolve() == (tmp_path / "from-env").resolve()


def _rewrite_created_at(handle, created_at: str) -> None:
    meta = Path(handle.path) / META_NAME
    payload = json.loads(meta.read_text(encoding="utf-8"))
    payload["created_at"] = created_at
    meta.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.asyncio
async def test_destroy_removes_only_that_sandbox(tmp_path):
    root = tmp_path / "workspaces"
    provider = LocalFilesystemWorkspaceProvider(root=root)
    handle = await provider.create(mission_id=uuid4())
    sibling = await provider.create(mission_id=uuid4())
    await provider.write_file(handle.id, "notes/hello.txt", "gone")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    stray = root / "not-a-workspace.txt"
    stray.write_text("keep", encoding="utf-8")
    repo_file = Path("app/workspace.py").resolve()
    assert repo_file.is_file()

    await provider.destroy(handle.id)

    assert not Path(handle.path).exists()
    assert Path(sibling.path).is_dir()
    assert (Path(sibling.path) / META_NAME).is_file()
    assert outside.read_text(encoding="utf-8") == "keep"
    assert stray.read_text(encoding="utf-8") == "keep"
    assert repo_file.is_file()
    with pytest.raises(WorkspaceError) as exc:
        await provider.get(handle.id)
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_destroy_ignores_metadata_path_outside_root(tmp_path):
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep", encoding="utf-8")
    meta = Path(handle.path) / META_NAME
    payload = json.loads(meta.read_text(encoding="utf-8"))
    payload["path"] = str(outside)
    meta.write_text(json.dumps(payload), encoding="utf-8")

    await provider.destroy(handle.id)

    assert not Path(handle.path).exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_destroy_missing_workspace_is_tool_missing(tmp_path):
    root = tmp_path / "workspaces"
    provider = LocalFilesystemWorkspaceProvider(root=root)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    missing = uuid4()

    with pytest.raises(WorkspaceError) as exc:
        await provider.destroy(missing)
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert outside.read_text(encoding="utf-8") == "keep"
    assert root.exists()
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_destroy_directory_without_metadata_is_not_removed(tmp_path):
    provider = _provider(tmp_path)
    workspace_id = uuid4()
    impostor = provider.root / str(workspace_id)
    provider._ensure_root()
    impostor.mkdir()
    (impostor / "notes.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(WorkspaceError) as exc:
        await provider.destroy(workspace_id)
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    assert (impostor / "notes.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_destroy_symlink_workspace_is_refused(tmp_path):
    root = tmp_path / "workspaces"
    provider = LocalFilesystemWorkspaceProvider(root=root)
    provider._ensure_root()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("keep", encoding="utf-8")
    workspace_id = uuid4()
    link = root / str(workspace_id)
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError) as exc:
        await provider.destroy(workspace_id)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert secret.read_text(encoding="utf-8") == "keep"
    assert link.is_symlink()


@pytest.mark.asyncio
async def test_destroy_symlink_directory_is_refused(tmp_path):
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("keep", encoding="utf-8")
    link = Path(handle.path) / "escape-dir"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError) as exc:
        await provider.destroy(handle.id)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert secret.read_text(encoding="utf-8") == "keep"
    assert Path(handle.path).is_dir()
    assert link.is_symlink()
    assert (Path(handle.path) / META_NAME).is_file()


@pytest.mark.asyncio
async def test_destroy_nested_symlink_is_refused(tmp_path):
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())
    secret = tmp_path / "secret.txt"
    secret.write_text("keep", encoding="utf-8")
    link = Path(handle.path) / "escape"
    link.symlink_to(secret)

    with pytest.raises(WorkspaceError) as exc:
        await provider.destroy(handle.id)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert secret.read_text(encoding="utf-8") == "keep"
    assert Path(handle.path).is_dir()
    assert link.is_symlink()


@pytest.mark.asyncio
async def test_gc_unconfigured_does_not_delete(tmp_path, monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_TTL_SECONDS", raising=False)
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())
    _rewrite_created_at(handle, (utcnow() - timedelta(days=30)).isoformat())
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    for raw in (None, "", "0", "-5", "nope"):
        if raw is None:
            monkeypatch.delenv("SWARM_WORKSPACE_TTL_SECONDS", raising=False)
        else:
            monkeypatch.setenv("SWARM_WORKSPACE_TTL_SECONDS", raw)
        assert configured_workspace_ttl_seconds() is None
        result = await provider.gc(now=utcnow())
        assert result.configured is False
        assert result.destroyed == []
        assert result.ttl_seconds is None
        assert Path(handle.path).is_dir()
        assert outside.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_gc_configured_deletes_only_expired(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_WORKSPACE_TTL_SECONDS", "60")
    root = tmp_path / "workspaces"
    provider = LocalFilesystemWorkspaceProvider(root=root)
    old = await provider.create(mission_id=uuid4())
    fresh = await provider.create(mission_id=uuid4())
    unknown = await provider.create(mission_id=uuid4())
    _rewrite_created_at(old, (utcnow() - timedelta(seconds=120)).isoformat())
    _rewrite_created_at(unknown, "not-a-timestamp")
    stray = root / "notes.txt"
    stray.write_text("keep", encoding="utf-8")
    other_dir = root / "not-a-uuid"
    other_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    repo_file = Path("app/workspace.py").resolve()

    result = await provider.gc()

    assert result.configured is True
    assert result.ttl_seconds == 60
    assert result.destroyed == [old.id]
    assert not Path(old.path).exists()
    assert Path(fresh.path).is_dir()
    assert Path(unknown.path).is_dir()
    assert stray.read_text(encoding="utf-8") == "keep"
    assert other_dir.is_dir()
    assert outside.read_text(encoding="utf-8") == "keep"
    assert repo_file.is_file()
    assert result.kept == 2


@pytest.mark.asyncio
async def test_gc_refuses_symlink_and_does_not_follow_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_WORKSPACE_TTL_SECONDS", "30")
    root = tmp_path / "workspaces"
    provider = LocalFilesystemWorkspaceProvider(root=root)
    provider._ensure_root()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("keep", encoding="utf-8")
    link = root / str(uuid4())
    link.symlink_to(outside, target_is_directory=True)

    result = await provider.gc()

    assert result.configured is True
    assert result.destroyed == []
    assert result.refused == 1
    assert secret.read_text(encoding="utf-8") == "keep"
    assert link.is_symlink()


@pytest.mark.asyncio
async def test_health_reports_destroy_gc_and_does_not_sweep(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_WORKSPACE_ROOT", str(tmp_path / "from-env"))
    monkeypatch.setenv("SWARM_WORKSPACE_TTL_SECONDS", "30")
    provider = build_workspace_provider()
    handle = await provider.create(mission_id=uuid4())
    _rewrite_created_at(handle, (utcnow() - timedelta(days=1)).isoformat())

    health = await provider.health()
    status = await workspace_health_status()

    assert Path(handle.path).is_dir()
    assert health.destroy is True
    assert health.gc == "configured"
    assert health.ttl_seconds == 30
    assert status["destroy"] is True
    assert status["gc"] == "configured"
    assert status["ttl_seconds"] == 30
    assert status["docker"] is False
    assert status["fallback"] is False
    dumped = health.model_dump()
    assert "key" not in str(dumped).lower()
    assert "secret" not in str(dumped).lower()

    monkeypatch.delenv("SWARM_WORKSPACE_TTL_SECONDS", raising=False)
    idle = await provider.health()
    assert idle.gc == "unconfigured"
    assert idle.ttl_seconds is None
    assert Path(handle.path).is_dir()


@pytest.mark.asyncio
async def test_runtime_destroy_workspace_hook(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = _provider(tmp_path)
    runtime = SwarmRuntime(store, workspaces=provider)
    mission = Mission(goal="sandbox")
    store.save_mission(mission)
    handle = await runtime.create_workspace(mission)
    await runtime.destroy_workspace(handle.id)
    assert not Path(handle.path).exists()
    with pytest.raises(PolicyError) as exc:
        await runtime.destroy_workspace(handle.id)
    assert exc.value.failure_class == FailureClass.TOOL_MISSING
    with pytest.raises(PolicyError) as missing:
        await runtime.destroy_workspace(uuid4())
    assert missing.value.failure_class == FailureClass.TOOL_MISSING


def test_normalize_relpath_rejects_traversal(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_ROOT", raising=False)
    with pytest.raises(WorkspaceError) as exc:
        normalize_relpath("../etc/passwd")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert normalize_relpath("notes/hello.txt") == "notes/hello.txt"
    assert default_workspace_root().name == "swarm-workspaces"
