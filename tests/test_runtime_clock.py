"""Mission Control runtime clock: durable timestamps only, never invented."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "runtime_clock_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS runtime clock harness")
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


def test_no_mission_hides_the_clock(cases):
    assert cases["empty"]["visible"] is False
    assert cases["missingId"]["visible"] is False
    assert cases["preview"]["visible"] is False
    assert cases["empty"]["startedAt"] is None
    assert cases["empty"]["elapsedMs"] is None


def test_loaded_mission_without_a_start_event_does_not_invent_time(cases):
    for key in ("noEvents", "createdAtIgnored"):
        view = cases[key]
        assert view["visible"] is True
        assert view["status"] == "running"
        assert view["statusLabel"] == "RUNNING"
        assert view["startedAt"] is None
        assert view["elapsedMs"] is None
        assert view["startedLabel"] == UNAVAILABLE
        assert view["elapsedLabel"] == UNAVAILABLE
        assert "2025-12-31" not in view["startedLabel"]


def test_running_elapsed_uses_the_started_event_and_pause_field(cases):
    running = cases["running"]
    assert running["startedAt"] == "2026-01-01T00:00:00.000Z"
    assert running["elapsedMs"] == 600_000
    assert running["elapsedLabel"] == "10m 0s"
    assert running["statusLabel"] == "RUNNING"
    paused = cases["pauseSubtracted"]
    assert paused["elapsedMs"] == 480_000
    assert paused["elapsedLabel"] == "8m 0s"
    assert paused["startedAt"] == running["startedAt"]


def test_paused_and_terminal_clocks_do_not_follow_the_wall_clock(cases):
    paused = cases["pausedFreeze"]
    assert paused["elapsedMs"] == 210_000
    assert paused["elapsedLabel"] == "3m 30s"
    assert paused["statusLabel"] == "PAUSED"
    assert cases["pausedMissingAnchor"]["elapsedMs"] is None
    assert cases["pausedMissingAnchor"]["elapsedLabel"] == UNAVAILABLE
    done = cases["terminalFreeze"]
    assert done["elapsedMs"] == 330_000
    assert done["elapsedLabel"] == "5m 30s"
    assert done["statusLabel"] == "COMPLETED"
    assert cases["terminalMissing"]["elapsedMs"] is None
    assert cases["terminalMissing"]["statusLabel"] == "FAILED"


def test_bad_timestamps_and_non_active_status_fail_closed(cases):
    assert cases["badPause"]["startedAt"] == "2026-01-01T00:00:00.000Z"
    assert cases["badPause"]["elapsedMs"] is None
    assert cases["badStart"]["startedAt"] is None
    assert cases["badStart"]["elapsedMs"] is None
    assert cases["pending"]["statusLabel"] == "PENDING"
    assert cases["pending"]["elapsedMs"] is None
    assert cases["badNow"]["elapsedMs"] is None
    waiting = cases["waiting"]
    assert waiting["statusLabel"] == "WAITING"
    assert waiting["elapsedMs"] == 600_000


def test_start_anchor_is_the_first_started_or_resumed_event(cases):
    assert cases["resumedOnly"]["startedAt"] == "2026-01-01T00:00:00.000Z"
    assert cases["resumedOnly"]["elapsedMs"] == 600_000
    assert cases["firstStartedWins"]["startedAt"] == "2026-01-01T00:00:00.000Z"
    assert cases["firstStartedWins"]["elapsedMs"] == 600_000
    assert cases["format"]["bad"] == UNAVAILABLE
    assert cases["format"]["zero"] == "0s"
    assert cases["format"]["seconds"] == "3s"


def test_clock_markup_is_hidden_and_does_not_invent_a_start():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert 'id="runtimeClock" aria-label="Mission runtime" hidden' in html
    assert "runtimeClockView" in control
    assert "state.preview?null" in control
    assert "export function runtimeClockView" in state
    clock_helpers = state.split("const RUNTIME_ACTIVE", 1)[1]
    assert "mission.created_at" not in clock_helpers
    assert "Date.now" not in clock_helpers
    clock_css = css.split(".runtime-clock{")[1].split(".telemetry-drawer")[0]
    assert "animation" not in clock_css
    assert "@keyframes" not in clock_css


def test_static_runtime_clock_is_served_hidden(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="runtimeClock"' in page.text
        assert 'id="runtimeClock" aria-label="Mission runtime" hidden' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function runtimeClockView" in state.text


def test_durable_mission_fields_and_start_event_are_the_clock_inputs(tmp_path):
    from app.events import EventType
    from app.models import Mission, MissionEvent, MissionStatus
    from app.store import Store

    store = Store(str(tmp_path / "swarm.db"))
    paused_at = datetime(2026, 1, 1, 0, 4, tzinfo=timezone.utc)
    mission = Mission(
        goal="Clock fields stay on the mission payload",
        status=MissionStatus.PAUSED,
        paused_at=paused_at,
        paused_seconds=30,
    )
    store.save_mission(mission)
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.append(MissionEvent(
        mission_id=mission.id,
        event_type=EventType.MISSION_STARTED,
        created_at=started,
        payload={"goal": mission.goal},
    ))
    body = store.get_mission(mission.id).model_dump(mode="json")
    events = [event.model_dump(mode="json") for event in store.events(mission.id)]
    assert body["status"] == "paused"
    assert body["paused_seconds"] == 30
    assert body["paused_at"].startswith("2026-01-01T00:04:00")
    assert "started_at" not in body
    assert events[0]["event_type"] == "mission.started"
    assert events[0]["created_at"].startswith("2026-01-01T00:00:00")
