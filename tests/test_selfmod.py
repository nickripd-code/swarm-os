import json
import subprocess
from pathlib import Path

import pytest

from app.health import selfmod_health_status
from app.models import FailureClass, Mission
from app.policy import (
    PolicyError, PolicyGate, PolicyRequest, tool_is_dangerous, tool_is_opted_in_selfmod,
)
from app.runtime import SwarmRuntime
from app.selfmod import (
    PRODUCTION_ROOT, MemoryWorkspace, SandboxWorkspace, SelfModToolProvider,
    SelfModWorkspace, WorktreeWorkspace, normalize_relpath, path_is_protected,
    selfmod_opted_in, selfmod_write_opted_in,
)
from app.store import Store
from app.tools import ToolCall, ToolError, ToolProvider, build_tool_provider


def _no_selfmod_env(monkeypatch):
    monkeypatch.delenv("SWARM_SELFMOD", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD_WRITE", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD_PRODUCTION_WRITE", raising=False)
    monkeypatch.delenv("SWARM_SELFMOD_SANDBOX", raising=False)
    monkeypatch.delenv("SWARM_LOCAL_TOOLS", raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("SWARM_BROWSER", raising=False)


def _proposal_args(path="notes.txt", content="hello sandbox", reason="improve notes"):
    return {"reason": reason, "changes": [{"path": path, "content": content}]}


def test_selfmod_opt_in_is_off_by_default(monkeypatch):
    _no_selfmod_env(monkeypatch)
    assert selfmod_opted_in() is False
    assert selfmod_write_opted_in() is False
    assert SelfModToolProvider().configured() is False


@pytest.mark.asyncio
async def test_unconfigured_selfmod_is_missing_not_success(monkeypatch):
    _no_selfmod_env(monkeypatch)
    provider = SelfModToolProvider()
    assert provider.list_tools() == []
    health = await provider.health()
    assert health.status == "unconfigured"
    assert health.tools == []
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args()))
    assert exc.value.failure_class == FailureClass.TOOL_MISSING


@pytest.mark.asyncio
async def test_opted_in_propose_and_diff_do_not_write(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    workspace = MemoryWorkspace(files={"notes.txt": "old\n"})
    provider = SelfModToolProvider(opted_in=True, write_enabled=False, workspace=workspace)
    assert isinstance(provider, ToolProvider)
    assert [spec.name for spec in provider.list_tools()] == ["selfmod.propose", "selfmod.diff"]
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        content="new\n",
    )))
    assert proposed.ok
    assert proposed.output["applied"] is False
    assert proposed.output["mode"] == "proposal"
    assert proposed.output["files"] == ["notes.txt"]
    assert proposed.output["write_enabled"] is False
    assert "api_key" not in proposed.output
    diffed = await provider.invoke(ToolCall(
        name="selfmod.diff",
        arguments={"proposal_id": proposed.output["proposal_id"]},
    ))
    assert diffed.output["applied"] is False
    blob = diffed.output["diffs"][0]["diff"]
    assert "old" in blob and "new" in blob
    assert workspace.written == []
    assert workspace.files["notes.txt"] == "old\n"


@pytest.mark.asyncio
async def test_apply_without_write_flag_is_not_success(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    workspace = MemoryWorkspace()
    provider = SelfModToolProvider(opted_in=True, write_enabled=False, workspace=workspace)
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args()))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(
            name="selfmod.apply",
            arguments={"proposal_id": proposed.output["proposal_id"]},
        ))
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert workspace.written == []


@pytest.mark.asyncio
async def test_sandbox_apply_writes_only_when_write_opted_in(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    workspace = MemoryWorkspace(files={"notes.txt": "old"})
    provider = SelfModToolProvider(opted_in=True, write_enabled=True, workspace=workspace)
    assert [spec.name for spec in provider.list_tools()] == [
        "selfmod.propose", "selfmod.diff", "selfmod.apply",
    ]
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        content="new",
    )))
    applied = await provider.invoke(ToolCall(
        name="selfmod.apply",
        arguments={"proposal_id": proposed.output["proposal_id"]},
    ))
    assert applied.output["applied"] is True
    assert applied.output["sandbox"] is True
    assert workspace.written == [("notes.txt", "new")]


@pytest.mark.asyncio
async def test_production_workspace_refuses_apply_without_production_flag(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    workspace = MemoryWorkspace(production=True)
    provider = SelfModToolProvider(opted_in=True, write_enabled=True, workspace=workspace)
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args()))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(
            name="selfmod.apply",
            arguments={"proposal_id": proposed.output["proposal_id"]},
        ))
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert workspace.written == []


@pytest.mark.asyncio
async def test_protected_core_cannot_be_applied(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    workspace = MemoryWorkspace()
    provider = SelfModToolProvider(opted_in=True, write_enabled=True, workspace=workspace)
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        path="app/policy.py",
        content="raise SystemExit\n",
        reason="weaken policy",
    )))
    assert proposed.output["protected"] == ["app/policy.py"]
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(
            name="selfmod.apply",
            arguments={"proposal_id": proposed.output["proposal_id"]},
        ))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert workspace.written == []


@pytest.mark.asyncio
async def test_path_traversal_and_absolute_paths_fail_closed(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    workspace = MemoryWorkspace()
    provider = SelfModToolProvider(opted_in=True, workspace=workspace)
    with pytest.raises(ToolError) as traversal:
        await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
            path="../secrets.txt",
        )))
    assert traversal.value.failure_class == FailureClass.TOOL_FAILURE
    with pytest.raises(ToolError) as absolute:
        await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
            path="/etc/passwd",
        )))
    assert absolute.value.failure_class == FailureClass.TOOL_FAILURE
    assert provider._proposals == {}


@pytest.mark.asyncio
async def test_diff_redacts_secret_lines(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    workspace = MemoryWorkspace(files={"app/config.py": "debug = False\n"})
    provider = SelfModToolProvider(opted_in=True, workspace=workspace)
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments={
        "reason": "add a key",
        "changes": [{"path": "app/config.py", "content": "debug = False\napi_key = 'must-not-leak'\n"}],
    }))
    diffed = await provider.invoke(ToolCall(
        name="selfmod.diff",
        arguments={"proposal_id": proposed.output["proposal_id"]},
    ))
    blob = json.dumps(diffed.output)
    assert "must-not-leak" not in blob
    assert "[redacted]" in blob


@pytest.mark.asyncio
async def test_unknown_proposal_and_missing_reason_fail_closed(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    provider = SelfModToolProvider(opted_in=True, workspace=MemoryWorkspace())
    with pytest.raises(ToolError) as missing:
        await provider.invoke(ToolCall(name="selfmod.propose", arguments={"changes": []}))
    assert missing.value.failure_class == FailureClass.TOOL_FAILURE
    with pytest.raises(ToolError) as unknown:
        await provider.invoke(ToolCall(name="selfmod.diff", arguments={"proposal_id": "nope"}))
    assert unknown.value.failure_class == FailureClass.TOOL_FAILURE


def test_build_tool_provider_includes_selfmod_only_when_opted_in(monkeypatch):
    _no_selfmod_env(monkeypatch)
    assert build_tool_provider() is None
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    provider = build_tool_provider()
    assert [spec.name for spec in provider.list_tools()] == ["selfmod.propose", "selfmod.diff"]
    assert provider.provider_id == "selfmod"
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    writable = build_tool_provider()
    assert [spec.name for spec in writable.list_tools()] == [
        "selfmod.propose", "selfmod.diff", "selfmod.apply",
    ]


@pytest.mark.asyncio
async def test_health_is_unconfigured_by_default(monkeypatch):
    _no_selfmod_env(monkeypatch)
    status = await selfmod_health_status()
    assert status["configured"] is False
    assert status["status"] == "unconfigured"
    assert status["tools"] == []
    assert status["write_enabled"] is False
    assert status["production_write"] is False
    assert status["fallback"] is False
    assert "secret" not in json.dumps(status)


@pytest.mark.asyncio
async def test_health_reports_opt_in_without_write(monkeypatch):
    _no_selfmod_env(monkeypatch)
    monkeypatch.setenv("SWARM_SELFMOD", "true")
    status = await selfmod_health_status()
    assert status["configured"] is True
    assert status["status"] == "healthy"
    assert status["write_enabled"] is False
    assert status["tools"] == ["selfmod.propose", "selfmod.diff"]


def test_policy_still_denies_selfmod_without_opt_in(monkeypatch):
    _no_selfmod_env(monkeypatch)
    gate = PolicyGate()
    mission = Mission(goal="tools")
    assert tool_is_dangerous("selfmod.propose")
    assert tool_is_dangerous("self_modify")
    assert not tool_is_opted_in_selfmod("selfmod.propose")
    with pytest.raises(PolicyError) as exc:
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.propose"))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.apply"))


def test_policy_allows_opted_in_propose_diff_only(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.delenv("SWARM_SELFMOD_WRITE", raising=False)
    gate = PolicyGate()
    mission = Mission(goal="propose")
    assert tool_is_opted_in_selfmod("selfmod.propose")
    gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.propose"))
    gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.diff"))
    with pytest.raises(PolicyError) as apply_denied:
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.apply"))
    assert apply_denied.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="self_modify"))
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="shell"))


def test_policy_allows_apply_only_when_write_opted_in(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "yes")
    gate = PolicyGate()
    mission = Mission(goal="apply")
    gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.apply"))
    with pytest.raises(PolicyError):
        gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.deploy"))


def test_local_only_still_allows_selfmod(monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    gate = PolicyGate()
    mission = Mission(goal="private", privacy="local_only")
    gate.authorize(PolicyRequest(action="tool_use", mission=mission, tool="selfmod.propose"))


def test_normalize_and_protected_helpers():
    assert normalize_relpath("app/foo.py") == "app/foo.py"
    assert path_is_protected("app/policy.py")
    assert path_is_protected(".env")
    assert path_is_protected("secrets/key.pem")
    assert not path_is_protected("app/runtime.py")
    with pytest.raises(ToolError):
        normalize_relpath("..\\windows")


@pytest.mark.asyncio
async def test_sandbox_workspace_apply_does_not_touch_source(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    source = tmp_path / "src"
    sandbox = tmp_path / "sandbox"
    source.mkdir()
    sandbox.mkdir()
    (source / "notes.txt").write_text("original", encoding="utf-8")
    workspace = SandboxWorkspace(source_root=source, sandbox_root=sandbox, production_write=False)
    provider = SelfModToolProvider(opted_in=True, write_enabled=True, workspace=workspace)
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        content="patched",
    )))
    applied = await provider.invoke(ToolCall(
        name="selfmod.apply",
        arguments={"proposal_id": proposed.output["proposal_id"]},
    ))
    assert applied.output["applied"] is True
    assert applied.output["sandbox"] is True
    assert (source / "notes.txt").read_text(encoding="utf-8") == "original"
    assert (sandbox / "notes.txt").read_text(encoding="utf-8") == "patched"


@pytest.mark.asyncio
async def test_sandbox_inside_source_refuses_without_production_write(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    monkeypatch.delenv("SWARM_SELFMOD_PRODUCTION_WRITE", raising=False)
    source = tmp_path / "repo"
    source.mkdir()
    (source / "notes.txt").write_text("keep", encoding="utf-8")
    workspace = SandboxWorkspace(
        source_root=source,
        sandbox_root=source / "nested",
        production_write=False,
    )
    provider = SelfModToolProvider(opted_in=True, write_enabled=True, workspace=workspace)
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        content="overwrite",
    )))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(
            name="selfmod.apply",
            arguments={"proposal_id": proposed.output["proposal_id"]},
        ))
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert (source / "notes.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_runtime_invokes_opted_in_selfmod_with_fake_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        tools=SelfModToolProvider(opted_in=True, workspace=MemoryWorkspace()),
    )
    mission = Mission(goal="Propose with a fake")
    store.save_mission(mission)
    result = await runtime.invoke_tool(mission, "selfmod.propose", _proposal_args())
    assert result["ok"] is True
    assert result["output"]["applied"] is False
    events = store.events(mission.id)
    assert any(e.event_type == "tool.started" for e in events)
    assert any(e.event_type == "tool.completed" for e in events)
    assert not any(e.event_type == "tool.failed" for e in events)
    assert runtime.tool_calls_used(mission.id) == 1


@pytest.mark.asyncio
async def test_runtime_denies_selfmod_when_listed_but_not_opted_in(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(
        store,
        tools=SelfModToolProvider(opted_in=True, workspace=MemoryWorkspace()),
    )
    mission = Mission(goal="No selfmod")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "selfmod.propose", _proposal_args())
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    assert not any(e.event_type == "tool.started" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_runtime_denies_apply_without_write_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.delenv("SWARM_SELFMOD_WRITE", raising=False)
    store = Store(str(tmp_path / "swarm.db"))
    workspace = MemoryWorkspace()
    runtime = SwarmRuntime(
        store,
        tools=SelfModToolProvider(opted_in=True, write_enabled=True, workspace=workspace),
    )
    mission = Mission(goal="No apply")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "selfmod.apply", {"proposal_id": "x"})
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert workspace.written == []
    assert runtime.tool_calls_used(mission.id) == 0


def test_workspace_abc_is_implemented():
    assert issubclass(MemoryWorkspace, SelfModWorkspace)
    assert issubclass(SandboxWorkspace, SelfModWorkspace)
    assert issubclass(WorktreeWorkspace, SelfModWorkspace)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _init_repo(path: Path) -> Path:
    path.mkdir()
    (path / "notes.txt").write_text("committed\n", encoding="utf-8")
    (path / "app").mkdir()
    (path / "app" / "policy.py").write_text("POLICY = True\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "selfmod@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "selfmod"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def _worktree_file(root: Path, relative: str) -> Path:
    matches = list(root.glob(f"slot-*/tree/{relative}"))
    assert len(matches) == 1
    return matches[0]


@pytest.mark.asyncio
async def test_worktree_propose_diff_reads_committed_tree_not_live_source(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    repo = _init_repo(tmp_path / "src")
    head = _git(repo, "rev-parse", "HEAD")
    branches = _git(repo, "branch")
    (repo / "notes.txt").write_text("dirty-live\n", encoding="utf-8")
    production_policy = (PRODUCTION_ROOT / "app" / "policy.py").read_bytes()
    root = tmp_path / "worktrees"
    provider = SelfModToolProvider(
        opted_in=True,
        write_enabled=False,
        source_repo=repo,
        worktree_root=root,
    )
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        content="proposed\n",
    )))
    assert proposed.output["applied"] is False
    assert proposed.output["isolation"] == "worktree"
    assert proposed.output["worktree"] is True
    assert proposed.output["branch"].startswith("swarm-selfmod-")
    diffed = await provider.invoke(ToolCall(
        name="selfmod.diff",
        arguments={"proposal_id": proposed.output["proposal_id"]},
    ))
    assert diffed.output["applied"] is False
    blob = diffed.output["diffs"][0]["diff"]
    assert "committed" in blob
    assert "proposed" in blob
    assert "dirty-live" not in blob
    assert _worktree_file(root, "notes.txt").read_text(encoding="utf-8") == "committed\n"
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "dirty-live\n"
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "branch") == branches
    assert "swarm-selfmod-" not in branches
    assert (PRODUCTION_ROOT / "app" / "policy.py").read_bytes() == production_policy


@pytest.mark.asyncio
async def test_worktree_apply_writes_only_the_isolated_tree(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    repo = _init_repo(tmp_path / "src")
    root = tmp_path / "worktrees"
    provider = SelfModToolProvider(
        opted_in=True,
        write_enabled=True,
        source_repo=repo,
        worktree_root=root,
    )
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        content="patched\n",
    )))
    applied = await provider.invoke(ToolCall(
        name="selfmod.apply",
        arguments={"proposal_id": proposed.output["proposal_id"]},
    ))
    assert applied.output["applied"] is True
    assert applied.output["sandbox"] is True
    assert _worktree_file(root, "notes.txt").read_text(encoding="utf-8") == "patched\n"
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "committed\n"
    assert "swarm-selfmod-" not in _git(repo, "branch")


@pytest.mark.asyncio
async def test_worktree_refuses_protected_core_apply(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    repo = _init_repo(tmp_path / "src")
    root = tmp_path / "worktrees"
    provider = SelfModToolProvider(
        opted_in=True,
        write_enabled=True,
        source_repo=repo,
        worktree_root=root,
    )
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        path="app/policy.py",
        content="raise SystemExit\n",
        reason="weaken policy",
    )))
    with pytest.raises(ToolError) as exc:
        await provider.invoke(ToolCall(
            name="selfmod.apply",
            arguments={"proposal_id": proposed.output["proposal_id"]},
        ))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert _worktree_file(root, "app/policy.py").read_text(encoding="utf-8") == "POLICY = True\n"
    assert (repo / "app" / "policy.py").read_text(encoding="utf-8") == "POLICY = True\n"


@pytest.mark.asyncio
async def test_worktree_refuses_traversal_absolute_and_overlapping_roots(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    repo = _init_repo(tmp_path / "src")
    root = tmp_path / "worktrees"
    provider = SelfModToolProvider(
        opted_in=True,
        source_repo=repo,
        worktree_root=root,
    )
    with pytest.raises(ToolError) as traversal:
        await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
            path="../secrets/key",
        )))
    assert traversal.value.failure_class == FailureClass.TOOL_FAILURE
    with pytest.raises(ToolError) as absolute:
        await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
            path="/etc/passwd",
        )))
    assert absolute.value.failure_class == FailureClass.TOOL_FAILURE
    assert not root.exists()
    inside = repo / "nested-wt"
    overlapping = SelfModToolProvider(
        opted_in=True,
        source_repo=repo,
        worktree_root=inside,
    )
    with pytest.raises(ToolError) as overlap:
        await overlapping.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args()))
    assert overlap.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    assert not inside.exists()
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "committed\n"
    before = {path.name for path in PRODUCTION_ROOT.iterdir()}
    with pytest.raises(ToolError) as production:
        WorktreeWorkspace(repo, PRODUCTION_ROOT, production_write=False).prepare()
    assert production.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    after = {path.name for path in PRODUCTION_ROOT.iterdir()}
    assert not any(name.startswith("slot-") for name in after - before)
    with pytest.raises(ToolError) as relative:
        WorktreeWorkspace(repo, Path("relative-wt"), production_write=False).prepare()
    assert relative.value.failure_class == FailureClass.POLICY_REFUSAL
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ToolError) as missing_git:
        WorktreeWorkspace(plain, tmp_path / "plain-wt", production_write=False).prepare()
    assert missing_git.value.failure_class == FailureClass.TOOL_FAILURE


@pytest.mark.asyncio
async def test_worktree_symlink_escape_to_protected_core_fails_closed(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    monkeypatch.setenv("SWARM_SELFMOD_WRITE", "1")
    repo = _init_repo(tmp_path / "src")
    root = tmp_path / "worktrees"
    provider = SelfModToolProvider(
        opted_in=True,
        write_enabled=True,
        source_repo=repo,
        worktree_root=root,
    )
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        path="alias.txt",
        content="overwrite\n",
    )))
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n", encoding="utf-8")
    _worktree_file(root, "notes.txt").parent.joinpath("alias.txt").symlink_to(
        repo / "app" / "policy.py",
    )
    with pytest.raises(ToolError) as diff_escape:
        await provider.invoke(ToolCall(
            name="selfmod.diff",
            arguments={"proposal_id": proposed.output["proposal_id"]},
        ))
    assert diff_escape.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "POLICY" not in str(diff_escape.value)
    with pytest.raises(ToolError) as apply_escape:
        await provider.invoke(ToolCall(
            name="selfmod.apply",
            arguments={"proposal_id": proposed.output["proposal_id"]},
        ))
    assert apply_escape.value.failure_class == FailureClass.POLICY_REFUSAL
    assert (repo / "app" / "policy.py").read_text(encoding="utf-8") == "POLICY = True\n"
    assert outside.read_text(encoding="utf-8") == "keep\n"
    external = tmp_path / "external.txt"
    external.write_text("external-keep\n", encoding="utf-8")
    link = _worktree_file(root, "notes.txt")
    link.unlink()
    link.symlink_to(external)
    escaped = await provider.invoke(ToolCall(name="selfmod.propose", arguments=_proposal_args(
        content="mutated\n",
    )))
    with pytest.raises(ToolError) as outside_escape:
        await provider.invoke(ToolCall(
            name="selfmod.diff",
            arguments={"proposal_id": escaped.output["proposal_id"]},
        ))
    assert outside_escape.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(ToolError) as outside_apply:
        await provider.invoke(ToolCall(
            name="selfmod.apply",
            arguments={"proposal_id": escaped.output["proposal_id"]},
        ))
    assert outside_apply.value.failure_class == FailureClass.POLICY_REFUSAL
    assert external.read_text(encoding="utf-8") == "external-keep\n"


@pytest.mark.asyncio
async def test_worktree_diff_redacts_secret_lines(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    repo = _init_repo(tmp_path / "src")
    root = tmp_path / "worktrees"
    provider = SelfModToolProvider(opted_in=True, source_repo=repo, worktree_root=root)
    proposed = await provider.invoke(ToolCall(name="selfmod.propose", arguments={
        "reason": "add a key",
        "changes": [{
            "path": "app/config.py",
            "content": "debug = False\napi_key = 'must-not-leak'\n",
        }],
    }))
    diffed = await provider.invoke(ToolCall(
        name="selfmod.diff",
        arguments={"proposal_id": proposed.output["proposal_id"]},
    ))
    blob = json.dumps(diffed.output)
    assert "must-not-leak" not in blob
    assert "[redacted]" in blob
    assert diffed.output["applied"] is False
    assert list(root.glob("slot-*/tree/app/config.py")) == []


@pytest.mark.asyncio
async def test_unconfigured_health_does_not_materialize_a_worktree(tmp_path, monkeypatch):
    _no_selfmod_env(monkeypatch)
    root = tmp_path / "health-wt"
    monkeypatch.setenv("SWARM_SELFMOD_WORKTREE_ROOT", str(root))
    status = await selfmod_health_status()
    assert status["status"] == "unconfigured"
    assert status["configured"] is False
    assert status["write_enabled"] is False
    assert status["production_write"] is False
    assert not root.exists()
    monkeypatch.setenv("SWARM_SELFMOD", "1")
    opted = await selfmod_health_status()
    assert opted["status"] == "healthy"
    assert opted["write_enabled"] is False
    assert opted["production_write"] is False
    assert not root.exists()
