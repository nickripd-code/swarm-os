import json

import pytest

from app.health import selfmod_health_status
from app.models import FailureClass, Mission
from app.policy import (
    PolicyError, PolicyGate, PolicyRequest, tool_is_dangerous, tool_is_opted_in_selfmod,
)
from app.runtime import SwarmRuntime
from app.selfmod import (
    MemoryWorkspace, SandboxWorkspace, SelfModToolProvider, SelfModWorkspace,
    normalize_relpath, path_is_protected, selfmod_opted_in, selfmod_write_opted_in,
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
