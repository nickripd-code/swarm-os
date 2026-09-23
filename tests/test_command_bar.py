"""Mission Control command bar: typed commands map to existing APIs, fail closed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "command_bar_cases.mjs"
MISSION = "11111111-1111-4111-8111-111111111111"
AGENT = "22222222-2222-4222-8222-222222222222"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS command bar harness")
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


def test_empty_and_unknown_commands_fail_closed(cases):
    assert cases["empty"]["ok"] is False
    assert "empty" in cases["empty"]["error"].lower()
    assert cases["unknown"]["ok"] is False
    assert cases["unknown"]["error"].startswith("Unknown command:")
    assert cases["unknownNatural"]["ok"] is False
    assert cases["stopExtra"]["ok"] is False
    assert cases["stopAllExtra"]["ok"] is False
    assert cases["resolveUnknown"]["ok"] is False


def test_stop_and_stop_all_map_to_existing_routes(cases):
    assert cases["stop"] == {"ok": True, "action": "stop"}
    assert cases["stopSlash"]["action"] == "stop"
    assert cases["stopCase"]["action"] == "stop"
    assert cases["stopAll"]["action"] == "stop-all"
    assert cases["stopAllWords"]["action"] == "stop-all"
    assert cases["stopAllOneWord"]["action"] == "stop-all"
    resolved = cases["resolveStop"]
    assert resolved["ok"] is True
    assert resolved["method"] == "POST"
    assert resolved["path"] == f"/api/missions/{MISSION}/stop"
    assert cases["resolveStopAll"]["path"] == "/api/stop-all"
    assert cases["resolveStopPreview"]["ok"] is False
    assert cases["resolveStopNoMission"]["ok"] is False


def test_answer_requires_open_question_and_text(cases):
    assert cases["answerEmpty"]["ok"] is False
    assert cases["answerText"]["action"] == "answer"
    assert cases["answerText"]["text"] == "ship it"
    resolved = cases["resolveAnswer"]
    assert resolved["ok"] is True
    assert resolved["method"] == "POST"
    assert resolved["path"] == f"/api/missions/{MISSION}/answers/q-open"
    assert resolved["body"] == {"answer": "ship it"}
    assert cases["resolveAnswerNoQuestion"]["ok"] is False
    assert "question" in cases["resolveAnswerNoQuestion"]["error"].lower()
    assert cases["resolveAnswerPreview"]["ok"] is False


def test_budget_command_maps_to_limit_patch(cases):
    assert cases["budgetSet"]["action"] == "budget"
    assert cases["budgetSet"]["mode"] == "set"
    assert cases["budgetSet"]["field"] == "max_token_cost"
    assert cases["budgetSet"]["value"] == 4.5
    assert cases["budgetDelta"]["mode"] == "delta"
    assert cases["budgetDelta"]["value"] == -2
    assert cases["budgetBadField"]["ok"] is False
    assert cases["budgetBadMode"]["ok"] is False
    assert cases["budgetShort"]["ok"] is False
    assert cases["budgetFraction"]["ok"] is False
    resolved = cases["resolveBudget"]
    assert resolved["ok"] is True
    assert resolved["method"] == "POST"
    assert resolved["path"] == f"/api/missions/{MISSION}/budget"
    assert resolved["body"] == {"set": {"max_token_cost": 4.5}}
    assert cases["resolveBudgetDelta"]["body"] == {"delta": {"max_tool_calls": -2}}
    assert cases["resolveBudgetPreview"]["ok"] is False
    assert cases["resolveBudgetNoMission"]["ok"] is False


def test_kill_is_fail_closed_unless_route_present(cases):
    assert cases["killExtra"]["ok"] is False
    assert cases["killPresent"] is True
    assert cases["killAbsent"] is False
    assert cases["killGetOnly"] is False
    assert cases["killPattern"] is True
    assert cases["resolveKillUnavailable"]["ok"] is False
    assert "not available" in cases["resolveKillUnavailable"]["error"].lower()
    resolved = cases["resolveKill"]
    assert resolved["ok"] is True
    assert resolved["path"] == f"/api/missions/{MISSION}/agents/{AGENT}/kill"
    assert cases["resolveKillSelected"]["path"] == resolved["path"]
    assert cases["resolveKillMissing"]["ok"] is False
    assert cases["resolveKillPreview"]["ok"] is False


def test_static_command_bar_is_vanilla_and_unanimated():
    html = (ROOT / "app/static/index.html").read_text()
    css = (ROOT / "app/static/control.css").read_text()
    control = (ROOT / "app/static/control.js").read_text()
    state = (ROOT / "app/static/state.mjs").read_text()
    blob = html + css + control + state
    assert 'id="commandBar"' in html
    assert 'id="commandForm"' in html
    assert "parseCommand" in state
    assert "resolveCommand" in control
    assert "react" not in blob.lower()
    assert "pixi" not in blob.lower()
    command_block = css.split(".command-bar{")[1].split(".alert-stack")[0]
    assert "animation" not in command_block
    assert "@keyframes" not in command_block
    assert "working…" not in control.lower()
    assert "working..." not in control.lower()


def test_static_command_bar_is_served_and_maps_live_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="commandBar"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function parseCommand" in state.text
        assert "export function resolveCommand" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".command-bar{" in css.text
        spec = client.get("/openapi.json").json()
        paths = spec["paths"]
        assert "post" in paths["/api/stop-all"]
        assert "post" in paths["/api/missions/{mission_id}/stop"]
        assert "post" in paths["/api/missions/{mission_id}/answers/{question_id}"]
        assert "post" in paths["/api/missions/{mission_id}/budget"]
        kill_path = "/api/missions/{mission_id}/agents/{agent_id}/kill"
        assert "post" in paths[kill_path]
        stopped = client.post("/api/stop-all")
        assert stopped.status_code == 200
        body = stopped.json()
        assert body["status"] == "stopped"
        assert body["mission_ids"] == []
