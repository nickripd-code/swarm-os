from pathlib import Path
from uuid import uuid4

import pytest

from app.health import workspace_health_status
from app.models import FailureClass, Mission
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store
from app.workspace import (
    LocalFilesystemWorkspaceProvider,
    META_NAME,
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


@pytest.mark.asyncio
async def test_code_mission_hand_copies_same_mission_files_only(tmp_path):
    provider = _provider(tmp_path)
    mission_id = uuid4()
    source = await provider.create(mission_id=mission_id, agent_id=uuid4())
    dest = await provider.create(mission_id=mission_id, agent_id=uuid4())
    other = await provider.create(mission_id=uuid4(), agent_id=uuid4())
    await provider.write_file(source.id, "src/app.py", "print('handed')\n")
    copied = await provider.hand_files(source.id, dest.id, ["src/app.py"])
    assert copied == ["src/app.py"]
    assert await provider.read_file(dest.id, "src/app.py") == "print('handed')\n"
    assert await provider.read_file(source.id, "src/app.py") == "print('handed')\n"
    with pytest.raises(WorkspaceError) as cross:
        await provider.hand_files(source.id, other.id, ["src/app.py"])
    assert cross.value.failure_class == FailureClass.POLICY_REFUSAL
    assert not (Path(other.path) / "src").exists()
    with pytest.raises(WorkspaceError) as same:
        await provider.hand_files(source.id, source.id, ["src/app.py"])
    assert same.value.failure_class == FailureClass.POLICY_REFUSAL


@pytest.mark.asyncio
async def test_code_mission_hand_refuses_symlink_and_metadata(tmp_path):
    provider = _provider(tmp_path)
    mission_id = uuid4()
    source = await provider.create(mission_id=mission_id)
    dest = await provider.create(mission_id=mission_id)
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    link = Path(source.path) / "leak.txt"
    link.symlink_to(outside)
    with pytest.raises(WorkspaceError) as exc:
        await provider.hand_files(source.id, dest.id, ["leak.txt"])
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert outside.read_text(encoding="utf-8") == "nope"
    assert [path.name for path in Path(dest.path).iterdir()] == [META_NAME]
    with pytest.raises(WorkspaceError) as meta:
        await provider.hand_files(source.id, dest.id, [META_NAME])
    assert meta.value.failure_class == FailureClass.POLICY_REFUSAL


@pytest.mark.asyncio
async def test_runtime_hand_maps_cross_mission_to_policy_error(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    provider = _provider(tmp_path)
    runtime = SwarmRuntime(store, workspaces=provider)
    mission = Mission(goal="hand code")
    store.save_mission(mission)
    other = Mission(goal="other")
    store.save_mission(other)
    source = await runtime.create_workspace(mission, agent_id=uuid4())
    dest = await provider.create(mission_id=other.id, agent_id=uuid4())
    await runtime.write_workspace_file(source.id, "notes.txt", "keep")
    with pytest.raises(PolicyError) as exc:
        await runtime.hand_workspace_files(source.id, dest.id, ["notes.txt"])
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert not (Path(dest.path) / "notes.txt").exists()


def test_normalize_relpath_rejects_traversal(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_ROOT", raising=False)
    with pytest.raises(WorkspaceError) as exc:
        normalize_relpath("../etc/passwd")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert normalize_relpath("notes/hello.txt") == "notes/hello.txt"
    assert default_workspace_root().name == "swarm-workspaces"
