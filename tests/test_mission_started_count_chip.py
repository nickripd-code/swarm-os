"""Read-only Mission Control mission-started count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "mission_started_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the mission-started chip harness")
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


def test_catalog_event_is_mission_started():
    from app.events import EventType

    assert EventType.MISSION_STARTED == "mission.started"
    assert "job.started" not in {member.value for member in EventType}
    assert "worker.heartbeat" not in {member.value for member in EventType}
    assert "task.suspended" not in {member.value for member in EventType}


def test_chip_stays_hidden_without_a_loaded_mission_or_in_preview(cases):
    for key in ("hidden", "hiddenDefault", "preview"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == "MISSION STARTED " + UNAVAILABLE
        assert view["label"] != "MISSION STARTED 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "MISSION STARTED 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "MISSION STARTED 0"


def test_counts_mission_started_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "MISSION STARTED 3"
    assert "$" not in view["label"]
    assert "token" not in view["label"].lower()
    assert ":" not in view["label"]
    assert "LAST" not in view["label"]
    assert cases["ignoresResumed"]["count"] == 0
    assert cases["ignoresRunning"]["count"] == 0
    assert cases["ignoresResumeRequested"]["count"] == 0
    assert cases["ignoresPaused"]["count"] == 0
    assert cases["ignoresTaskStarted"]["count"] == 0
    assert cases["ignoresLlmStarted"]["count"] == 0
    assert cases["ignoresToolStarted"]["count"] == 0
    assert cases["ignoresVerificationStarted"]["count"] == 0
    assert cases["ignoresCompleted"]["count"] == 0
    assert cases["ignoresFailed"]["count"] == 0
    assert cases["ignoresToolCompleted"]["count"] == 0
    assert cases["ignoresBudget"]["count"] == 0
    assert cases["oneStartedNotPayload"]["count"] == 1
    assert cases["oneStartedNotPayload"]["label"] == "MISSION STARTED 1"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    unreadable = cases["unreadableType"]
    assert unreadable["known"] is False
    assert unreadable["count"] is None
    assert unreadable["label"] == "MISSION STARTED " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_starts(cases):
    assert cases["prefixFirst"]["count"] == 1
    assert cases["prefix"]["count"] == 1
    assert cases["prefixTwo"]["count"] == 2
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function missionStartedCountView" in state
    assert "export function recordedMissionStartedCountFeed" in state
    assert 'const MISSION_STARTED_COUNT_EVENT = "mission.started"' in state
    view_body = state.split("export function missionStartedCountView")[1].split("export function applyEvent")[0]
    assert "MISSION_STARTED_COUNT_EVENT" in view_body
    assert "mission.resumed" not in view_body
    assert "mission.running" not in view_body
    assert "mission.resume_requested" not in view_body
    assert "mission.paused" not in view_body
    assert "task.started" not in view_body
    assert "llm.started" not in view_body
    assert "tool.started" not in view_body
    assert "verification.started" not in view_body
    assert "job.started" not in view_body
    assert "worker.heartbeat" not in view_body
    assert "task.suspended" not in view_body
    assert "created_at" not in view_body
    assert "token_spent" not in view_body
    assert "state.preview?null:recordedMissionStartedCountFeed(eventLog,replayCursor,missionStartedFeedLoaded)" in control
    assert "missionStartedCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "missionStartedFeedLoaded=options.missionStartedFeedLoaded===true" in control
    assert 'missionStartedChip.textContent=missionView.hidden?"":missionView.label' in control
    assert "if(Array.isArray(events))" in control
    assert "missionStartedFeedLoaded=true" in control
    assert 'id="missionStartedCountChip"' in html
    chip = html.split('id="missionStartedCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    css_rule = css.split(".hud-chip.mission-started")[1].split(".hud-stats")[0]
    assert '.hud-chip.mission-started[data-known="false"]' in css
    assert "animation" not in css_rule


def test_static_mission_started_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="missionStartedCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function missionStartedCountView" in state.text
