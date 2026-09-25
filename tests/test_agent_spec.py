import math
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.migrations import CURRENT_SCHEMA_VERSION
from app.models import (
    MAX_AGENT_TOKEN_COST,
    MAX_AGENT_TTL_SECONDS,
    AgentSpec,
    AgentStatus,
    Mission,
    utcnow,
)
from app.runtime import SwarmRuntime
from app.store import Store


def _mission() -> Mission:
    return Mission(goal="Persist optional agent hints")


def test_omitted_fields_default_to_unspecified_and_round_trip():
    mission = _mission()
    agent = AgentSpec(mission_id=mission.id, role="researcher", purpose="Look")
    assert agent.preferred_model is None
    assert agent.max_token_cost is None
    assert agent.tool_allowlist is None
    assert agent.ttl_seconds is None
    restored = AgentSpec.model_validate_json(agent.model_dump_json())
    assert restored == agent
    dumped = agent.model_dump(mode="json")
    assert dumped["preferred_model"] is None
    assert dumped["max_token_cost"] is None
    assert dumped["tool_allowlist"] is None
    assert dumped["ttl_seconds"] is None


def test_optional_fields_round_trip_through_schema_and_store(tmp_path):
    mission = _mission()
    agent = AgentSpec(
        mission_id=mission.id,
        role="researcher",
        purpose="Look",
        preferred_model="  openai/gpt-test  ",
        max_token_cost=0,
        tool_allowlist=[" read ", "write"],
        ttl_seconds=60,
    )
    assert agent.preferred_model == "openai/gpt-test"
    assert agent.max_token_cost == 0
    assert agent.tool_allowlist == ["read", "write"]
    assert agent.ttl_seconds == 60
    assert AgentSpec.model_validate(agent.model_dump(mode="json")) == agent

    store = Store(str(tmp_path / "agents.db"))
    store.save_mission(mission)
    store.save_agent(agent)
    reloaded = Store(str(tmp_path / "agents.db"))
    loaded = reloaded.load_agents(mission.id)[0]
    assert loaded == agent
    projected = reloaded.project(mission.id)["agents"][0]
    assert projected["preferred_model"] == "openai/gpt-test"
    assert projected["max_token_cost"] == 0
    assert projected["tool_allowlist"] == ["read", "write"]
    assert projected["ttl_seconds"] == 60
    assert CURRENT_SCHEMA_VERSION == 4


def test_legacy_payload_without_optional_fields_reloads_as_unspecified(tmp_path):
    mission = _mission()
    created = utcnow()
    agent_id = uuid4()
    legacy = {
        "id": str(agent_id),
        "mission_id": str(mission.id),
        "parent_id": None,
        "role": "researcher",
        "purpose": "Look",
        "capabilities": ["reason"],
        "depth": 1,
        "status": "created",
        "output": None,
        "created_at": created.isoformat(),
    }
    loaded = AgentSpec.model_validate(legacy)
    assert loaded.id == agent_id
    assert loaded.preferred_model is None
    assert loaded.max_token_cost is None
    assert loaded.tool_allowlist is None
    assert loaded.ttl_seconds is None
    store = Store(str(tmp_path / "legacy.db"))
    store.save_mission(mission)
    store.save_agent(loaded)
    assert store.load_agents(mission.id)[0].tool_allowlist is None


def test_empty_tool_allowlist_is_stored_and_means_unspecified():
    mission = _mission()
    agent = AgentSpec(
        mission_id=mission.id, role="researcher", purpose="Look", tool_allowlist=[],
    )
    restored = AgentSpec.model_validate_json(agent.model_dump_json())
    assert restored.tool_allowlist == []
    assert not restored.tool_allowlist


@pytest.mark.parametrize("kwargs", [
    {"preferred_model": ""},
    {"preferred_model": "   "},
    {"preferred_model": 12},
    {"max_token_cost": -0.01},
    {"max_token_cost": MAX_AGENT_TOKEN_COST + 0.01},
    {"max_token_cost": math.inf},
    {"max_token_cost": math.nan},
    {"max_token_cost": True},
    {"tool_allowlist": [""]},
    {"tool_allowlist": ["   "]},
    {"tool_allowlist": ["ok", 1]},
    {"tool_allowlist": "shell"},
    {"ttl_seconds": 0},
    {"ttl_seconds": -1},
    {"ttl_seconds": MAX_AGENT_TTL_SECONDS + 1},
    {"ttl_seconds": True},
    {"ttl_seconds": 1.5},
])
def test_invalid_optional_fields_fail_closed(kwargs):
    mission = _mission()
    with pytest.raises(ValidationError):
        AgentSpec(mission_id=mission.id, role="researcher", purpose="Look", **kwargs)


@pytest.mark.asyncio
async def test_spawn_without_optional_fields_keeps_them_unspecified(tmp_path):
    store = Store(str(tmp_path / "spawn-plain.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)
    agent = await runtime.spawn(mission, "researcher", "Look", capabilities=["reason"])
    assert agent.status == AgentStatus.CREATED
    assert agent.preferred_model is None
    assert agent.max_token_cost is None
    assert agent.tool_allowlist is None
    assert agent.ttl_seconds is None
    saved = store.load_agents(mission.id)[0]
    assert saved == agent
    spawned = next(event for event in store.events(mission.id) if event.event_type == "agent.spawned")
    assert spawned.event_type == "agent.spawned"
    assert spawned.payload["preferred_model"] is None
    assert spawned.payload["tool_allowlist"] is None
    assert spawned.payload["ttl_seconds"] is None
    assert spawned.payload["max_token_cost"] is None


@pytest.mark.asyncio
async def test_spawn_persists_optional_fields_on_row_and_existing_events(tmp_path):
    store = Store(str(tmp_path / "spawn-fields.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)
    agent = await runtime.spawn(
        mission, "researcher", "Look",
        preferred_model="local/test",
        max_token_cost=1.5,
        tool_allowlist=[],
        ttl_seconds=120,
    )
    await runtime.agent_status(agent, AgentStatus.RUNNING)
    saved = store.load_agents(mission.id)[0]
    assert saved.preferred_model == "local/test"
    assert saved.max_token_cost == 1.5
    assert saved.tool_allowlist == []
    assert saved.ttl_seconds == 120
    assert saved.status == AgentStatus.RUNNING
    events = store.events(mission.id)
    spawned = next(event for event in events if event.event_type == "agent.spawned")
    updated = next(event for event in events if event.event_type == "agent.updated")
    assert spawned.payload["preferred_model"] == "local/test"
    assert spawned.payload["tool_allowlist"] == []
    assert updated.payload["ttl_seconds"] == 120
    assert updated.payload["max_token_cost"] == 1.5
    assert {event.event_type for event in events} <= {"agent.spawned", "agent.updated"}


@pytest.mark.asyncio
async def test_spawn_rejects_invalid_fields_without_persisting(tmp_path):
    store = Store(str(tmp_path / "spawn-invalid.db"))
    runtime = SwarmRuntime(store)
    mission = _mission()
    store.save_mission(mission)
    with pytest.raises(ValidationError):
        await runtime.spawn(mission, "researcher", "Look", preferred_model="")
    with pytest.raises(ValidationError):
        await runtime.spawn(mission, "researcher", "Look", max_token_cost=-1)
    with pytest.raises(ValidationError):
        await runtime.spawn(mission, "researcher", "Look", ttl_seconds=0)
    assert store.load_agents(mission.id) == []
    assert runtime.agents[mission.id] == []
    assert store.events(mission.id) == []
