import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.health import workspace_health_status
from app.models import FailureClass, Mission
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.workspace import (
    META_NAME,
    MAX_GC_CANDIDATES,
    LocalFilesystemWorkspaceProvider,
    WorkspaceError,
    WorkspaceProvider,
    build_workspace_provider,
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
    assert Path(status["root"]).resolve() == (tmp_path / "from-env").resolve()


def _stamp(handle, when: datetime) -> None:
    meta_path = Path(handle.path) / META_NAME
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    payload["created_at"] = when.isoformat()
    meta_path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.asyncio
async def test_destroy_removes_only_the_sandbox_tree(tmp_path):
    provider = _provider(tmp_path)
    root = tmp_path / "workspaces"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    handle = await provider.create(mission_id=uuid4())
    await provider.write_file(handle.id, "notes/hello.txt", "gone")
    sibling = await provider.create(mission_id=uuid4())
    removed = await provider.destroy(handle.id)
    assert removed.id == handle.id
    assert not Path(handle.path).exists()
    assert Path(sibling.path).is_dir()
    assert outside.read_text(encoding="utf-8") == "keep"
    assert root.is_dir()
    with pytest.raises(WorkspaceError) as exc:
        await provider.get(handle.id)
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_destroy_missing_workspace_is_tool_missing(tmp_path):
    provider = _provider(tmp_path)
    with pytest.raises(WorkspaceError) as exc:
        await provider.destroy(uuid4())
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_destroy_refuses_symlink_and_absolute_escapes(tmp_path):
    provider = _provider(tmp_path)
    root = tmp_path / "workspaces"
    handle = await provider.create(mission_id=uuid4())
    secret = tmp_path / "secret.txt"
    secret.write_text("keep", encoding="utf-8")
    (Path(handle.path) / "escape").symlink_to(secret)
    with pytest.raises(WorkspaceError) as link_exc:
        await provider.destroy(handle.id)
    assert link_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert secret.read_text(encoding="utf-8") == "keep"
    assert Path(handle.path).is_dir()
    (Path(handle.path) / "escape").unlink()

    meta_path = Path(handle.path) / META_NAME
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    payload["path"] = "../../outside"
    meta_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkspaceError) as relative_exc:
        await provider.destroy(handle.id)
    assert relative_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert secret.read_text(encoding="utf-8") == "keep"
    assert Path(handle.path).is_dir()

    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep", encoding="utf-8")
    meta_path = Path(handle.path) / META_NAME
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    payload["path"] = str(outside)
    meta_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkspaceError) as path_exc:
        await provider.destroy(handle.id)
    assert path_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "keep"
    assert Path(handle.path).is_dir()

    linked_id = uuid4()
    linked_root = tmp_path / "linked-outside"
    linked_root.mkdir()
    (linked_root / "secret.txt").write_text("keep", encoding="utf-8")
    (root / str(linked_id)).symlink_to(linked_root, target_is_directory=True)
    with pytest.raises(WorkspaceError) as dir_exc:
        await provider.destroy(linked_id)
    assert dir_exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert (linked_root / "secret.txt").read_text(encoding="utf-8") == "keep"
    assert (root / str(linked_id)).is_symlink()


@pytest.mark.asyncio
async def test_destroy_mission_removes_only_that_mission(tmp_path):
    provider = _provider(tmp_path)
    mission_id = uuid4()
    first = await provider.create(mission_id=mission_id)
    second = await provider.create(mission_id=mission_id, agent_id=uuid4())
    other = await provider.create(mission_id=uuid4())
    removed = await provider.destroy_mission(mission_id)
    assert set(removed) == {first.id, second.id}
    assert not Path(first.path).exists()
    assert not Path(second.path).exists()
    assert Path(other.path).is_dir()
    assert (await provider.get(other.id)).id == other.id


@pytest.mark.asyncio
async def test_gc_removes_stale_workspaces_only(tmp_path):
    provider = _provider(tmp_path)
    root = tmp_path / "workspaces"
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    fresh = await provider.create(mission_id=uuid4())
    stale = await provider.create(mission_id=uuid4())
    _stamp(stale, now - timedelta(hours=48))
    _stamp(fresh, now - timedelta(minutes=5))
    old_orphan = root / str(uuid4())
    old_orphan.mkdir()
    old_ts = (now - timedelta(hours=48)).timestamp()
    os.utime(old_orphan, (old_ts, old_ts))
    new_orphan = root / str(uuid4())
    new_orphan.mkdir()
    keeper = root / "not-a-workspace"
    keeper.mkdir()
    (keeper / "notes.txt").write_text("keep", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    result = await provider.gc(now=now, ttl_seconds=24 * 60 * 60)
    assert result.ok is True
    assert result.truncated is False
    assert set(result.removed) == {stale.id, UUID(old_orphan.name)}
    assert set(result.retained) == {fresh.id, UUID(new_orphan.name)}
    assert not Path(stale.path).exists()
    assert not old_orphan.exists()
    assert Path(fresh.path).is_dir()
    assert new_orphan.is_dir()
    assert (keeper / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert outside.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_gc_terminal_retention_removes_only_expired_missions(tmp_path):
    provider = _provider(tmp_path)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    expired_mission = uuid4()
    recent_mission = uuid4()
    live_mission = uuid4()
    expired = await provider.create(mission_id=expired_mission)
    recent = await provider.create(mission_id=recent_mission)
    live = await provider.create(mission_id=live_mission)
    for handle in (expired, recent, live):
        _stamp(handle, now - timedelta(minutes=5))
    result = await provider.gc(
        now=now,
        ttl_seconds=24 * 60 * 60,
        terminal_retention_seconds=60 * 60,
        terminal_missions={
            expired_mission: now - timedelta(hours=2),
            recent_mission: now - timedelta(minutes=10),
        },
    )
    assert result.ok is True
    assert result.removed == [expired.id]
    assert set(result.retained) == {recent.id, live.id}
    assert not Path(expired.path).exists()
    assert Path(recent.path).is_dir()
    assert Path(live.path).is_dir()


@pytest.mark.asyncio
async def test_gc_corrupt_metadata_fails_closed(tmp_path):
    provider = _provider(tmp_path)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    stale = await provider.create(mission_id=uuid4())
    _stamp(stale, now - timedelta(hours=48))
    corrupt = tmp_path / "workspaces" / str(uuid4())
    corrupt.mkdir()
    (corrupt / META_NAME).write_text("{", encoding="utf-8")
    with pytest.raises(WorkspaceError) as exc:
        await provider.gc(now=now, ttl_seconds=24 * 60 * 60)
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert exc.value.removed == []
    assert Path(stale.path).is_dir()
    assert corrupt.is_dir()


@pytest.mark.asyncio
async def test_gc_symlink_escape_removes_nothing(tmp_path):
    provider = _provider(tmp_path)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    clean = await provider.create(mission_id=uuid4())
    escaped = await provider.create(mission_id=uuid4())
    _stamp(clean, now - timedelta(hours=48))
    _stamp(escaped, now - timedelta(hours=48))
    secret = tmp_path / "secret.txt"
    secret.write_text("keep", encoding="utf-8")
    (Path(escaped.path) / "escape").symlink_to(secret)
    with pytest.raises(WorkspaceError) as exc:
        await provider.gc(now=now, ttl_seconds=24 * 60 * 60)
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert exc.value.removed == []
    assert secret.read_text(encoding="utf-8") == "keep"
    assert Path(clean.path).is_dir()
    assert Path(escaped.path).is_dir()


@pytest.mark.asyncio
async def test_destroy_does_not_claim_success_when_delete_fails(tmp_path, monkeypatch):
    provider = _provider(tmp_path)
    handle = await provider.create(mission_id=uuid4())

    def fail_delete(directory: Path) -> None:
        raise OSError("read-only")

    monkeypatch.setattr("app.workspace.delete_sandbox_tree", fail_delete)
    with pytest.raises(WorkspaceError) as exc:
        await provider.destroy(handle.id)
    assert exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert Path(handle.path).is_dir()
    assert (Path(handle.path) / META_NAME).is_file()


@pytest.mark.asyncio
async def test_gc_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("app.workspace.MAX_GC_CANDIDATES", 1)
    provider = _provider(tmp_path)
    first = await provider.create(mission_id=uuid4())
    second = await provider.create(mission_id=uuid4())
    result = await provider.gc(ttl_seconds=24 * 60 * 60)
    assert result.truncated is True
    assert result.ok is False
    assert result.removed == []
    assert len(result.retained) == 1
    assert Path(first.path).is_dir()
    assert Path(second.path).is_dir()
    assert MAX_GC_CANDIDATES == 200


@pytest.mark.asyncio
async def test_runtime_destroy_and_gc_map_errors(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = _provider(tmp_path)
    runtime = SwarmRuntime(store, workspaces=provider)
    mission = Mission(goal="sandbox")
    store.save_mission(mission)
    handle = await runtime.create_workspace(mission)
    await runtime.write_workspace_file(handle.id, "out.txt", "ok")
    removed = await runtime.destroy_workspace(handle.id)
    assert removed.id == handle.id
    assert not Path(handle.path).exists()
    with pytest.raises(PolicyError) as missing:
        await runtime.destroy_workspace(uuid4())
    assert missing.value.failure_class == FailureClass.TOOL_MISSING
    corrupt = tmp_path / "workspaces" / str(uuid4())
    corrupt.mkdir()
    (corrupt / META_NAME).write_text("{", encoding="utf-8")
    with pytest.raises(PolicyError) as gc_exc:
        await runtime.gc_workspaces(ttl_seconds=60)
    assert gc_exc.value.failure_class == FailureClass.TOOL_FAILURE
    assert corrupt.is_dir()


def test_normalize_relpath_rejects_traversal(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_ROOT", raising=False)
    with pytest.raises(WorkspaceError) as exc:
        normalize_relpath("../etc/passwd")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert normalize_relpath("notes/hello.txt") == "notes/hello.txt"
    assert default_workspace_root().name == "swarm-workspaces"
