import pytest

from app.llm import FallbackController, LLMProvider
from app.models import FailureClass, Mission
from app.policy import (
    PolicyError, PolicyGate, PolicyRequest, privacy_from_state, tool_is_dangerous,
    tool_is_opted_in_composio,
)
from app.router import capability_request_for
from app.runtime import SwarmRuntime
from app.store import Store
from app.tools import ToolCall, ToolProvider, ToolResult, ToolSpec
from app.verifier import local_evidence_check


class ListedTools(ToolProvider):
    """Test provider that advertises names PolicyGate must still refuse."""

    provider_id = "listed"

    def __init__(self, names: list[str]):
        self.names = names

    def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name=name, description=name, provider=self.provider_id) for name in self.names]

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            name=call.name, call_id=call.call_id, ok=True,
            output={"name": call.name}, provider=self.provider_id,
        )


def _request(**kwargs) -> PolicyRequest:
    mission = kwargs.pop("mission", None) or Mission(goal="Policy gate seed")
    return PolicyRequest(mission=mission, **kwargs)


def test_spawn_respects_agent_and_depth_limits():
    gate = PolicyGate()
    mission = Mission(goal="limits", limits={"max_agents": 1, "max_depth": 0})
    gate.authorize(_request(action="spawn", mission=mission, agent_count=0, depth=0,
                            capabilities=("spawn", "coordinate", "reason")))
    with pytest.raises(PolicyError) as exc:
        gate.authorize(_request(action="spawn", mission=mission, agent_count=1, depth=0))
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    with pytest.raises(PolicyError) as depth:
        gate.authorize(_request(action="spawn", mission=mission, agent_count=0, depth=1))
    assert depth.value.failure_class == FailureClass.RESOURCE_EXHAUSTED


def test_spawn_denies_unknown_capabilities_except_demo():
    gate = PolicyGate()
    mission = Mission(goal="caps")
    with pytest.raises(PolicyError) as exc:
        gate.authorize(_request(action="spawn", mission=mission, capabilities=("shell",)))
    assert exc.value.failure_class == FailureClass.CAPABILITY_MISMATCH
    gate.authorize(_request(action="spawn", mission=mission, mode="demo",
                            capabilities=("project_work", "report")))


def test_finish_requires_summary_and_idle_tasks():
    gate = PolicyGate()
    mission = Mission(goal="finish")
    with pytest.raises(PolicyError) as inflight:
        gate.authorize(_request(action="finish", mission=mission, in_flight_tasks=1,
                                summary="done"))
    assert inflight.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(PolicyError) as empty:
        gate.authorize(_request(action="finish", mission=mission, summary="  "))
    assert empty.value.failure_class == FailureClass.INVALID_OUTPUT
    gate.authorize(_request(action="finish", mission=mission, summary="Answer ready"))
    assert gate.approval_required(_request(action="finish", mission=mission, summary="Answer ready")) is None


def test_finish_approval_is_optional_and_off_by_default():
    from app.policy import interpret_approval, parse_approval_answer

    gate = PolicyGate()
    plain = Mission(goal="finish")
    gated = Mission(goal="finish", limits={"require_finish_approval": True})
    assert gate.approval_required(_request(action="finish", mission=plain, summary="done")) is None
    needed = gate.approval_required(_request(action="finish", mission=gated, summary="done"))
    assert needed is not None and needed.action == "finish"
    assert "approve" in needed.question.lower() and "deny" in needed.question.lower()
    gate.authorize(_request(action="finish", mission=gated, summary="done"))

    assert parse_approval_answer("Approve") == "approve"
    assert parse_approval_answer("yes.") == "approve"
    assert parse_approval_answer("DENY") == "deny"
    assert parse_approval_answer("ok") is None
    interpret_approval("allow")
    with pytest.raises(PolicyError) as denied:
        interpret_approval("refuse")
    assert denied.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError) as ambiguous:
        interpret_approval("maybe later")
    assert ambiguous.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED


def test_irreversible_org_and_live_payment_require_approval():
    gate = PolicyGate()
    mission = Mission(goal="org")
    live = Mission(goal="pay", live_payments=True)
    assert gate.approval_required(_request(action="spawn", mission=mission,
                                           capabilities=("reason",))) is None
    assert gate.approval_required(_request(action="org_change", mission=mission,
                                           org_op="spawn")) is None
    for op in ("replace", "reparent", "retire"):
        needed = gate.approval_required(_request(action="org_change", mission=mission, org_op=op))
        assert needed is not None and needed.action == "org_change" and needed.org_op == op
    with pytest.raises(PolicyError) as unknown_op:
        gate.authorize(_request(action="org_change", mission=mission, org_op="merge"))
    assert unknown_op.value.failure_class == FailureClass.INVALID_OUTPUT
    with pytest.raises(PolicyError) as disabled:
        gate.authorize(_request(action="live_payment", mission=mission))
    assert disabled.value.failure_class == FailureClass.POLICY_REFUSAL
    gate.authorize(_request(action="live_payment", mission=live))
    pay = gate.approval_required(_request(action="live_payment", mission=live))
    assert pay is not None and pay.action == "live_payment"


def test_dangerous_tools_are_denied_by_default():
    gate = PolicyGate()
    mission = Mission(goal="tools")
    assert tool_is_dangerous("shell")
    assert tool_is_dangerous("browser.open")
    with pytest.raises(PolicyError) as exc:
        gate.authorize(_request(action="tool_use", mission=mission, tool="shell"))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    with pytest.raises(PolicyError):
        gate.authorize(_request(action="tool_use", mission=mission, tool="web.search"))
    with pytest.raises(PolicyError):
        gate.authorize(_request(action="tool_use", mission=mission, tool=""))


def test_local_only_blocks_network_tools_and_defaults_allow_cloud():
    gate = PolicyGate()
    local = Mission(goal="private", privacy="local_only")
    cloud = Mission(goal="public")
    assert privacy_from_state({"privacy": "local_only"}) == "local_only"
    assert privacy_from_state({}) == "cloud_allowed"
    with pytest.raises(PolicyError) as exc:
        gate.authorize(_request(action="tool_use", mission=local, tool="http"))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(exc.value)
    gate.authorize(_request(action="tool_use", mission=local, tool="echo"))
    gate.authorize(_request(action="tool_use", mission=cloud, tool="echo"))
    request = capability_request_for(kind="decision", privacy="local_only")
    assert request.privacy == "local_only"
    assert capability_request_for(kind="decision").privacy == "cloud_allowed"


def test_tool_budget_fails_closed_before_other_tool_rules():
    gate = PolicyGate()
    mission = Mission(goal="budget", limits={"max_tool_calls": 1})
    with pytest.raises(PolicyError) as exc:
        gate.authorize(_request(action="tool_use", mission=mission, tool_calls_used=1, tool="shell"))
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED


def test_composio_is_external_and_requires_explicit_configuration(monkeypatch):
    gate = PolicyGate()
    cloud = Mission(goal="cloud")
    local = Mission(goal="private", privacy="local_only")
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    assert tool_is_dangerous("composio.GMAIL_FETCH_EMAILS")
    assert not tool_is_opted_in_composio("composio.GMAIL_FETCH_EMAILS")
    with pytest.raises(PolicyError):
        gate.authorize(_request(action="tool_use", mission=cloud, tool="composio.GMAIL_FETCH_EMAILS"))

    monkeypatch.setenv("COMPOSIO_API_KEY", "configured")
    monkeypatch.delenv("COMPOSIO_WRITE_ALLOWLIST", raising=False)
    assert tool_is_opted_in_composio("composio.GMAIL_FETCH_EMAILS")
    gate.authorize(_request(action="tool_use", mission=cloud, tool="composio.GMAIL_FETCH_EMAILS"))
    assert gate.approval_required(
        _request(action="tool_use", mission=cloud, tool="composio.GMAIL_FETCH_EMAILS")
    ) is None
    with pytest.raises(PolicyError) as exc:
        gate.authorize(_request(action="tool_use", mission=local, tool="composio.GMAIL_FETCH_EMAILS"))
    assert "local_only" in str(exc.value)
    with pytest.raises(PolicyError) as refused:
        gate.authorize(_request(action="tool_use", mission=cloud, tool="composio.GITHUB_CREATE_ISSUE"))
    assert refused.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "not allowlisted" in str(refused.value)


def test_allowlisted_composio_write_requires_approval_and_stays_local_only_blocked(monkeypatch):
    gate = PolicyGate()
    cloud = Mission(goal="cloud")
    local = Mission(goal="private", privacy="local_only")
    monkeypatch.setenv("COMPOSIO_API_KEY", "configured")
    monkeypatch.setenv("COMPOSIO_WRITE_ALLOWLIST", "github:GITHUB_CREATE_ISSUE, nope")
    gate.authorize(_request(action="tool_use", mission=cloud, tool="composio.GITHUB_GET_REPOSITORY"))
    assert gate.approval_required(
        _request(action="tool_use", mission=cloud, tool="composio.GITHUB_GET_REPOSITORY")
    ) is None
    write = _request(action="tool_use", mission=cloud, tool="composio.GITHUB_CREATE_ISSUE")
    gate.authorize(write)
    needed = gate.approval_required(write)
    assert needed is not None
    assert needed.action == "tool_use"
    assert needed.scope == "composio_write:composio.github_create_issue"
    with pytest.raises(PolicyError) as exc:
        gate.authorize(_request(action="tool_use", mission=local, tool="composio.GITHUB_CREATE_ISSUE"))
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert "local_only" in str(exc.value)
    monkeypatch.setenv("COMPOSIO_WRITE_ALLOWLIST", "gmail:GITHUB_CREATE_ISSUE")
    with pytest.raises(PolicyError) as mismatched:
        gate.authorize(_request(action="tool_use", mission=cloud, tool="composio.GITHUB_CREATE_ISSUE"))
    assert mismatched.value.failure_class == FailureClass.POLICY_REFUSAL


def test_token_budget_is_independent_of_payment_spent():
    gate = PolicyGate()
    mission = Mission(goal="tokens", spent=9, budget=10, token_spent=0.4)
    gate.check_token_budget(mission, spent=0.4, additional=0.1, budget=1.0)
    with pytest.raises(PolicyError) as exc:
        gate.check_token_budget(mission, spent=0.4, additional=0.7, budget=1.0)
    assert exc.value.failure_class == FailureClass.RESOURCE_EXHAUSTED
    assert mission.spent == 9


class ShellSpawnProvider(LLMProvider):
    async def decide(self, state):
        return {"action": "spawn", "role": "hacker", "purpose": "Run shell", "capabilities": ["shell"]}


class PassingFinishProvider(LLMProvider):
    async def decide(self, state):
        return {"action": "finish", "summary": "The answer is a short text-only result."}

    async def verify(self, state, claim):
        return local_evidence_check(state, claim)


@pytest.mark.asyncio
async def test_runtime_spawn_denied_capability_fails_closed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=ShellSpawnProvider())
    mission = Mission(goal="Do not grant shell")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "CAPABILITY_MISMATCH"
    assert not any(e.event_type == "mission.completed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_runtime_denies_dangerous_tool_even_when_listed(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=ListedTools(["shell", "echo"]))
    mission = Mission(goal="No shell")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "shell")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    failed = [e for e in store.events(mission.id) if e.event_type == "tool.failed"]
    assert failed and failed[-1].payload["failure_class"] == "POLICY_REFUSAL"
    assert not any(e.event_type == "tool.started" for e in store.events(mission.id))
    echoed = await runtime.invoke_tool(mission, "echo", {"text": "ok"})
    assert echoed["used"] == 1 and echoed["ok"]


@pytest.mark.asyncio
async def test_runtime_local_only_denies_network_tool(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, tools=ListedTools(["http"]))
    mission = Mission(goal="Stay local", privacy="local_only")
    store.save_mission(mission)
    with pytest.raises(PolicyError) as exc:
        await runtime.invoke_tool(mission, "http")
    assert exc.value.failure_class == FailureClass.POLICY_REFUSAL
    assert runtime.tool_calls_used(mission.id) == 0
    assert "local_only" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_only_finish_path_still_completes_with_gate(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=PassingFinishProvider())
    mission = Mission(goal="Plain text answer")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "completed"
    assert saved.privacy == "cloud_allowed"
    assert runtime._state(mission)["privacy"] == "cloud_allowed"
    assert not any(e.event_type == "mission.failed" for e in store.events(mission.id))


@pytest.mark.asyncio
async def test_demo_controller_still_completes_through_policy_gate(tmp_path):
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=FallbackController())
    mission = Mission(goal="Launch a small project")
    store.save_mission(mission)
    await runtime.run(mission)
    assert store.get_mission(mission.id).status == "completed"
