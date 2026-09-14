"""Mission Control historical replay: recorded events only, never invented progress."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "replay_cases.mjs"
UNAVAILABLE = "estimate unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS replay harness")
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


def test_duplicate_recorded_ids_are_ignored(cases):
    assert cases["duplicateIgnored"] is False
    assert cases["logLength"] == 5


def test_empty_log_is_live_with_no_invented_agents(cases):
    empty = cases["empty"]
    assert empty["agents"] == 0
    assert empty["status"] == "pending"
    assert empty["result"] is None
    assert empty["tokens"] == 0
    assert empty["view"]["live"] is True
    assert empty["view"]["label"] == "LIVE"
    assert empty["view"]["positionLabel"] == "0 / 0"
    assert empty["view"]["disabled"] is True


def test_scrub_to_spawn_does_not_show_later_tokens_or_result(cases):
    frame = cases["atSpawn"]
    assert frame["agents"] == [
        {"id": "root", "role": "mission_controller", "status": "running"}
    ]
    assert frame["status"] == "running"
    assert frame["result"] is None
    assert frame["pending"] is None
    assert frame["tokens"] == 0
    assert frame["known"] is False
    assert frame["spend"] == UNAVAILABLE
    assert frame["replay"] is True
    assert frame["view"]["label"] == "REPLAY"
    assert frame["view"]["live"] is False
    assert frame["view"]["positionLabel"] == "2 / 5"
    assert frame["view"]["eventType"] == "agent.spawned"


def test_known_spend_appears_only_after_the_budget_event(cases):
    frame = cases["atBudget"]
    assert frame["tokens"] == 14
    assert frame["known"] is True
    assert frame["cost"] == 1.25
    assert frame["spend"] == "$1.25"
    assert frame["status"] == "running"
    assert frame["result"] is None
    assert frame["replay"] is True


def test_live_end_matches_full_recorded_log(cases):
    frame = cases["atEnd"]
    assert frame["status"] == "completed"
    assert frame["result"]["summary"] == "verified result"
    assert frame["tokens"] == 14
    assert frame["spend"] == "$1.25"
    assert frame["replay"] is False
    assert frame["view"]["label"] == "LIVE"
    assert frame["view"]["live"] is True
    assert cases["liveApplyMatches"] is True


def test_snapshot_drops_future_status_and_does_not_invent_crew(cases):
    snap = cases["noInventedCrew"]["snapshot"]
    assert snap["status"] == "pending"
    assert snap["result"] is None
    assert snap["pending_question"] is None
    assert snap["goal"] == "Ship the landing page"
    assert cases["noInventedCrew"]["agentIds"] == []


def test_paused_and_question_frames_are_recorded_state_only(cases):
    assert cases["paused"]["status"] == "paused"
    assert cases["questionOpen"]["question"] == "Need a domain?"
    assert cases["questionClosed"] is None
    assert cases["afterAnswer"] == "running"


def test_step_and_live_helpers_clamp_to_the_log(cases):
    assert cases["step"] == {
        "back": 3,
        "forward": 1,
        "clampLow": 0,
        "clampHigh": 4,
        "empty": -1,
    }
    assert cases["live"]["mid"] is False
    assert cases["live"]["end"] is True
    assert cases["live"]["empty"] is True
    assert cases["live"]["clamp"] == 4
    assert cases["previewView"]["label"] == "PREVIEW"
    assert "synthetic" in cases["previewView"]["caption"]
    assert cases["elapsed"] == 3000
    assert cases["unavailable"] == UNAVAILABLE


def test_markup_is_not_a_fake_replay_animation():
    html = (ROOT / "app/static/index.html").read_text()
    css = (ROOT / "app/static/control.css").read_text()
    control = (ROOT / "app/static/control.js").read_text()
    state = (ROOT / "app/static/state.mjs").read_text()
    assert 'id="replayHud"' in html
    assert 'id="replayScrub"' in html
    assert "Live now" in html
    assert "projectEvents" in state
    assert "recordEvent" in state
    assert "showReplayAt" in control
    assert "ingestRecorded" in control
    assert "Historical replay" in html or "HISTORICAL REPLAY" in html
    block = css.split(".replay-hud{")[1].split("@media")[0]
    assert "animation" not in block
    assert "@keyframes" not in block


def test_static_replay_hud_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="replayHud"' in page.text
        assert 'id="replayScrub"' in page.text
        module = client.get("/static/state.mjs")
        assert module.status_code == 200
        assert "export function projectEvents" in module.text
        js = client.get("/static/control.js")
        assert js.status_code == 200
        assert "showReplayAt" in js.text
        styles = client.get("/static/control.css")
        assert styles.status_code == 200
        assert ".replay-hud" in styles.text
