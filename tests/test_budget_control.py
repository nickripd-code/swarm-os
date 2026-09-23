"""Human change-budget: raise, lower, refuse, terminal, and CAS. No live providers."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.budget import BudgetUpdateError
from app.llm import LLMProvider
from app.main import update_mission_budget
from app.models import (
    AgentSpec, FailureClass, LimitFieldPatch, Mission, MissionBudgetPatch, MissionLimits, MissionStatus,
)
from app.runtime import PolicyError, SwarmRuntime
from app.store import Store


class IdleProvider(LLMProvider):
    def configured(self) -> bool:
        return False


def _runtime(tmp_path) -> tuple[Store, SwarmRuntime]:
    store = Store(str(tmp_path / "budget.db"))
    return store, SwarmRuntime(store, controller=IdleProvider())


def _mission(**overrides) -> Mission:
    limits = overrides.pop("limits", None) or MissionLimits(
        max_token_cost=2,
        max_tool_calls=10,
        max_payment_amount=1,
        max_agents=2,
    )
    mission = Mission(
        goal="Adjust the live caps",
        status=overrides.pop("status", MissionStatus.RUNNING),
        budget=overrides.pop("budget", 10),
        limits=limits,
        **overrides,
    )
    return mission


async def _raise_token(runtime: SwarmRuntime, mission: Mission, amount: float = 4):
    return await runtime.update_budget(
        mission.id,
        MissionBudgetPatch(set=LimitFieldPatch(max_token_cost=amount)),
    )


@pytest.mark.asyncio
async def test_raise_and_lower_caps_emit_budget_updated_without_inventing_usd(tmp_path):
    store, runtime = _runtime(tmp_path)
    mission = _mission(
        token_spent=1.25,
        limits=MissionLimits(
            max_token_cost=2,
            max_tool_calls=10,
            max_payment_amount=1,
            max_agents=2,
            require_finish_approval=True,
        ),
    )
    store.save_mission(mission)

    raised = await _raise_token(runtime, mission, 4)
    assert raised["known"] is False
    assert raised["source"] == "human"
    assert raised["kind"] == "limits"
    assert raised["token_spent"] == 1.25
    assert raised["token_budget"] == 4
    assert raised["changes"]["max_token_cost"] == {"from": 2.0, "to": 4.0, "mode": "set"}
    assert "estimated_cost" not in raised
    assert "input_tokens" not in raised

    lowered = await runtime.update_budget(
        mission.id,
        MissionBudgetPatch(delta=LimitFieldPatch(max_tool_calls=-3, max_token_cost=-1)),
    )
    saved = store.get_mission(mission.id)
    assert saved is not None
    assert saved.limits.max_token_cost == 3
    assert saved.limits.max_tool_calls == 7
    assert saved.token_spent == 1.25
    assert saved.budget == 10
    assert saved.spent == 0
    assert saved.live_payments is False
    assert saved.limits.require_finish_approval is True
    assert lowered["known"] is False
    assert lowered["changes"]["max_tool_calls"]["mode"] == "delta"
    assert lowered["changes"]["max_token_cost"]["to"] == 3

    events = [event for event in store.events(mission.id) if event.event_type == "budget.updated"]
    assert len(events) == 2
    assert events[0].payload["known"] is False
    assert events[0].payload["source"] == "human"
    assert "estimated_cost" not in events[0].payload
    assert events[0].payload["token_spent"] == 1.25
    assert not any(event.event_type == "payment.created" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_delta_from_unset_token_cap_uses_effective_budget_not_token_math(tmp_path):
    store, runtime = _runtime(tmp_path)
    mission = _mission(limits=MissionLimits())
    assert mission.limits.max_token_cost is None
    store.save_mission(mission)
    baseline = runtime.resources.budget_for(mission)

    result = await runtime.update_budget(
        mission.id,
        MissionBudgetPatch(delta=LimitFieldPatch(max_token_cost=1)),
    )
    saved = store.get_mission(mission.id)
    assert saved is not None
    assert saved.limits.max_token_cost == baseline + 1
    change = result["changes"]["max_token_cost"]
    assert change["from"] is None
    assert change["from_effective"] == baseline
    assert change["to"] == baseline + 1
    assert result["known"] is False
    assert "estimated_cost" not in result


@pytest.mark.asyncio
async def test_over_cap_under_floor_and_empty_patch_are_refused(tmp_path):
    store, runtime = _runtime(tmp_path)
    mission = _mission()
    store.save_mission(mission)
    hard_cap = runtime.resources.settings.hard_cap

    over = BudgetUpdateError
    with pytest.raises(over) as token_cap:
        await runtime.update_budget(
            mission.id,
            MissionBudgetPatch(set=LimitFieldPatch(max_token_cost=hard_cap + 0.01)),
        )
    assert token_cap.value.code == "over_cap"
    assert token_cap.value.status_code == 409

    with pytest.raises(BudgetUpdateError) as agents:
        await runtime.update_budget(
            mission.id,
            MissionBudgetPatch(set=LimitFieldPatch(max_agents=501)),
        )
    assert agents.value.code == "over_cap"

    with pytest.raises(BudgetUpdateError) as floor:
        await runtime.update_budget(
            mission.id,
            MissionBudgetPatch(set=LimitFieldPatch(max_tool_calls=0)),
        )
    assert floor.value.code == "under_floor"
    assert floor.value.status_code == 409

    with pytest.raises(BudgetUpdateError) as payment_floor:
        await runtime.update_budget(
            mission.id,
            MissionBudgetPatch(delta=LimitFieldPatch(max_payment_amount=-2)),
        )
    assert payment_floor.value.code == "under_floor"

    with pytest.raises(BudgetUpdateError) as empty:
        await runtime.update_budget(mission.id, MissionBudgetPatch())
    assert empty.value.code == "empty"

    with pytest.raises(BudgetUpdateError) as overlap:
        await runtime.update_budget(
            mission.id,
            MissionBudgetPatch(
                set=LimitFieldPatch(max_tool_calls=4),
                delta=LimitFieldPatch(max_tool_calls=1),
            ),
        )
    assert overlap.value.code == "invalid"
    assert overlap.value.status_code == 422

    saved = store.get_mission(mission.id)
    assert saved is not None
    assert saved.limits.max_token_cost == 2
    assert saved.limits.max_tool_calls == 10
    assert saved.limits.max_payment_amount == 1
    assert store.events(mission.id) == []


def test_unknown_limit_field_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        MissionBudgetPatch.model_validate({"set": {"wallet": 5}})
    with pytest.raises(ValidationError):
        MissionBudgetPatch.model_validate({"delta": {"max_tool_calls": 1.5}})
    with pytest.raises(ValidationError):
        MissionBudgetPatch.model_validate({"live_payments": True, "set": {"max_tool_calls": 3}})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    MissionStatus.COMPLETED,
    MissionStatus.FAILED,
    MissionStatus.STOPPED,
    MissionStatus.BLOCKED,
])
async def test_terminal_mission_refuses_budget_change(tmp_path, status):
    store, runtime = _runtime(tmp_path)
    mission = _mission(status=status)
    store.save_mission(mission)
    with pytest.raises(BudgetUpdateError) as exc:
        await _raise_token(runtime, mission, 4)
    assert exc.value.code == "terminal"
    assert exc.value.status_code == 409
    saved = store.get_mission(mission.id)
    assert saved is not None
    assert saved.status == status
    assert saved.limits.max_token_cost == 2
    assert store.events(mission.id) == []


@pytest.mark.asyncio
async def test_paused_mission_can_change_budget(tmp_path):
    store, runtime = _runtime(tmp_path)
    mission = _mission(status=MissionStatus.PAUSED)
    store.save_mission(mission)
    await runtime.update_budget(
        mission.id,
        MissionBudgetPatch(set=LimitFieldPatch(max_payment_amount=2.5)),
    )
    saved = store.get_mission(mission.id)
    assert saved is not None
    assert saved.status == MissionStatus.PAUSED
    assert saved.limits.max_payment_amount == 2.5


@pytest.mark.asyncio
async def test_stale_expected_updated_at_and_concurrent_cas(tmp_path):
    store, runtime = _runtime(tmp_path)
    mission = _mission()
    store.save_mission(mission)
    saved = store.get_mission(mission.id)
    assert saved is not None
    stamp = saved.updated_at

    first = await runtime.update_budget(
        mission.id,
        MissionBudgetPatch(
            set=LimitFieldPatch(max_tool_calls=11),
            expected_updated_at=stamp,
        ),
    )
    assert first["limits"]["max_tool_calls"] == 11

    with pytest.raises(BudgetUpdateError) as stale:
        await runtime.update_budget(
            mission.id,
            MissionBudgetPatch(
                set=LimitFieldPatch(max_tool_calls=12),
                expected_updated_at=stamp,
            ),
        )
    assert stale.value.code == "conflict"
    assert stale.value.status_code == 409

    current = store.get_mission(mission.id)
    assert current is not None
    raced = await asyncio.gather(
        runtime.update_budget(
            mission.id,
            MissionBudgetPatch(
                set=LimitFieldPatch(max_tool_calls=15),
                expected_updated_at=current.updated_at,
            ),
        ),
        runtime.update_budget(
            mission.id,
            MissionBudgetPatch(
                set=LimitFieldPatch(max_tool_calls=16),
                expected_updated_at=current.updated_at,
            ),
        ),
        return_exceptions=True,
    )
    winners = [item for item in raced if isinstance(item, dict)]
    losers = [item for item in raced if isinstance(item, BudgetUpdateError)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].code == "conflict"
    final = store.get_mission(mission.id)
    assert final is not None
    assert final.limits.max_tool_calls == winners[0]["limits"]["max_tool_calls"]
    assert final.limits.max_tool_calls in {15, 16}
    updates = [event for event in store.events(mission.id) if event.event_type == "budget.updated"]
    assert len(updates) == 2


@pytest.mark.asyncio
async def test_live_mission_and_next_checks_see_new_limits(tmp_path):
    store, runtime = _runtime(tmp_path)
    mission = _mission(token_spent=1, limits=MissionLimits(
        max_token_cost=1,
        max_tool_calls=1,
        max_payment_amount=1,
        max_agents=1,
        max_runtime_seconds=30,
    ))
    store.save_mission(mission)
    live = store.get_mission(mission.id)
    assert live is not None
    runtime._live_missions[mission.id] = live
    runtime.agents[mission.id].append(AgentSpec(
        mission_id=mission.id, role="strategist", purpose="think", capabilities=["reason"],
    ))
    runtime._tool_calls[mission.id] = 1
    from app.models import utcnow
    runtime.started_at[mission.id] = utcnow()

    await runtime.update_budget(
        mission.id,
        MissionBudgetPatch(set=LimitFieldPatch(
            max_token_cost=4,
            max_tool_calls=4,
            max_payment_amount=3,
            max_agents=2,
            max_runtime_seconds=120,
        )),
    )
    assert live.limits.max_token_cost == 4
    assert runtime.resources.budget_for(live) == 4
    runtime.policy.check_tool_budget(live, 1)

    stale = store.get_mission(mission.id)
    assert stale is not None
    stale.limits = MissionLimits(
        max_token_cost=1, max_tool_calls=1, max_payment_amount=1, max_agents=1, max_runtime_seconds=30,
    )
    spawned = await runtime.spawn(stale, "reviewer", "check the work", capabilities=["review"])
    assert spawned.role == "reviewer"
    assert stale.limits.max_agents == 2
    assert runtime.consume_tool_call(stale) == 2
    assert runtime.remaining_runtime(stale) > 60
    intent = await runtime.create_payment(stale, "0xabc", 2, "within the new cap", idempotency_key="cap-ok")
    assert intent.status == "simulated"
    assert stale.spent == 2
    assert stale.live_payments is False
    assert stale.budget == 10

    blocked = _mission(token_spent=2, limits=MissionLimits(max_token_cost=4, max_payment_amount=1))
    store.save_mission(blocked)
    actor = AgentSpec(mission_id=blocked.id, role="mission_controller", purpose="decide", capabilities=["reason"])

    async def called():
        raise RuntimeError("called")

    await runtime.update_budget(
        blocked.id,
        MissionBudgetPatch(delta=LimitFieldPatch(max_token_cost=-3)),
    )
    with pytest.raises(PolicyError) as exhausted:
        await runtime.model_call(blocked, actor, "decision", called)
    assert exhausted.value.failure_class == FailureClass.RESOURCE_EXHAUSTED

    opened = _mission(token_spent=1, limits=MissionLimits(max_token_cost=1))
    store.save_mission(opened)
    opener = AgentSpec(mission_id=opened.id, role="mission_controller", purpose="decide", capabilities=["reason"])
    with pytest.raises(PolicyError):
        await runtime.model_call(opened, opener, "decision", called)
    await runtime.update_budget(
        opened.id,
        MissionBudgetPatch(set=LimitFieldPatch(max_token_cost=4)),
    )
    with pytest.raises(RuntimeError, match="called"):
        await runtime.model_call(opened, opener, "decision", called)


@pytest.mark.asyncio
async def test_raising_payment_cap_does_not_approve_or_settle_live_payment(tmp_path):
    store, runtime = _runtime(tmp_path)
    mission = _mission(
        live_payments=True,
        budget=10,
        limits=MissionLimits(max_payment_amount=1, max_token_cost=2),
    )
    store.save_mission(mission)
    await runtime.update_budget(
        mission.id,
        MissionBudgetPatch(set=LimitFieldPatch(max_payment_amount=5)),
    )
    fresh = store.get_mission(mission.id)
    assert fresh is not None
    assert fresh.live_payments is True
    assert fresh.limits.max_payment_amount == 5
    assert fresh.spent == 0
    with pytest.raises(PolicyError) as exc:
        await runtime.create_payment(fresh, "0xabc", 2, "needs approval", idempotency_key="live-no")
    assert exc.value.failure_class == FailureClass.AUTHORIZATION_REQUIRED
    saved = store.get_mission(mission.id)
    assert saved is not None
    assert saved.spent == 0
    assert saved.live_payments is True
    assert not any(event.event_type == "payment.created" for event in store.events(mission.id))


@pytest.mark.asyncio
async def test_http_budget_route_fail_closed_statuses(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    store = Store(str(tmp_path / "api.db"))
    runtime = SwarmRuntime(store, controller=IdleProvider())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "runtime", runtime)
    monkeypatch.setattr(main, "process_pool", None)
    mission = _mission()
    store.save_mission(mission)

    missing = uuid4()
    with pytest.raises(HTTPException) as not_found:
        await update_mission_budget(missing, MissionBudgetPatch(set=LimitFieldPatch(max_tool_calls=3)))
    assert not_found.value.status_code == 404

    with pytest.raises(HTTPException) as empty:
        await update_mission_budget(mission.id, MissionBudgetPatch())
    assert empty.value.status_code == 409
    assert "empty" in str(empty.value.detail).lower()

    with pytest.raises(HTTPException) as null_cap:
        await update_mission_budget(
            mission.id,
            MissionBudgetPatch.model_validate({"set": {"max_token_cost": None}}),
        )
    assert null_cap.value.status_code == 422

    with TestClient(main.app) as client:
        unknown = client.post(
            f"/api/missions/{uuid4()}/budget",
            json={"set": {"wallet": 1}},
        )
        assert unknown.status_code == 422
        absent = client.post(
            f"/api/missions/{uuid4()}/budget",
            json={"set": {"max_tool_calls": 4}},
        )
        assert absent.status_code == 404
        raised = client.post(
            f"/api/missions/{mission.id}/budget",
            json={"set": {"max_token_cost": 5}},
        )
        assert raised.status_code == 200
        body = raised.json()
        assert body["known"] is False
        assert body["limits"]["max_token_cost"] == 5
        assert body["status"] == "running"
        assert "estimated_cost" not in body
