"""Mission agent-count chip: listed agents only, never a missing zero."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models import AgentSpec, Mission
from app.store import Store

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "mission_agent_count_cases.mjs"
UNAVAILABLE = "agents unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS agent-count harness")
    result = subprocess.run(
        ["node", str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def cases() -> dict:
    return _load_cases()


def test_missing_list_is_unavailable_not_zero(cases):
    for name in (
        "missing", "null", "missionWithoutAgents", "nullAgents",
        "stringZero", "bareNumber", "negative", "fraction",
    ):
        view = cases[name]
        assert view["known"] is False, name
        assert view["count"] is None, name
        assert view["label"] == UNAVAILABLE, name
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_or_zero_is_zero(cases):
    for name in ("emptyList", "emptyAgentsField", "explicitZero", "explicitZeroAlias"):
        view = cases[name]
        assert view["known"] is True, name
        assert view["count"] == 0, name
        assert view["label"] == "0 agents", name


def test_listed_agents_use_list_length(cases):
    assert cases["oneAgent"]["count"] == 1
    assert cases["oneAgent"]["label"] == "1 agent"
    assert cases["twoAgents"]["count"] == 2
    assert cases["twoAgents"]["label"] == "2 agents"
    assert cases["listBeatsConflictingCount"]["count"] == 2
    assert cases["listBeatsConflictingCount"]["label"] == "2 agents"


def test_chip_reads_the_agents_list_and_hides_without_a_mission():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="missionAgentCount" class="hud-chip" hidden>agents unavailable</span>' in html
    assert "export function missionAgentCount" in state
    assert "missionAgentCount(listedAgents)" in control
    assert "listedAgents=Array.isArray(listed)?listed:null" in control
    assert '"/api/missions/"+encodeURIComponent(id)+"/agents"' in control
    start = control.index('if($("missionAgentCount"))')
    snippet = control[start:start + 420]
    assert "state.agents.size" not in snippet
    assert "el.hidden=true" in snippet
    assert "textContent=view.label" in snippet
    assert "0" not in snippet


def test_agents_route_lists_saved_agents_and_mission_omits_the_list(tmp_path, monkeypatch):
    import app.main as main

    local = Store(str(tmp_path / "agents.db"))
    monkeypatch.setattr(main, "store", local)
    mission = Mission(goal="Count attached agents")
    local.save_mission(mission)
    with TestClient(main.app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="missionAgentCount"' in page.text
        assert "agents unavailable" in page.text
        mission_body = client.get(f"/api/missions/{mission.id}")
        assert mission_body.status_code == 200
        payload = mission_body.json()
        assert "agents" not in payload
        assert "agent_count" not in payload
        assert "agents_count" not in payload
        empty = client.get(f"/api/missions/{mission.id}/agents")
        assert empty.status_code == 200
        assert empty.json() == []
        local.save_agent(AgentSpec(
            mission_id=mission.id,
            role="mission_controller",
            purpose="Coordinate the mission.",
        ))
        listed = client.get(f"/api/missions/{mission.id}/agents")
        assert listed.status_code == 200
        body = listed.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["role"] == "mission_controller"
        missing = client.get(f"/api/missions/{uuid4()}/agents")
        assert missing.status_code == 404
