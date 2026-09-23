"""Mission pause-state chip: paused or running from status only, never invented."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models import Mission, MissionStatus
from app.store import Store

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "mission_pause_state_cases.mjs"
UNAVAILABLE = "pause unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS pause-state harness")
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


def test_missing_or_other_status_is_unavailable(cases):
    for name in (
        "missing", "null", "bareString", "list", "noStatus", "nullStatus",
        "blankStatus", "wrongCase", "spaced", "flagOnly", "flagFalse",
        "pausedAtOnly", "pausedSecondsOnly", "waiting", "pending", "completed",
        "failed", "stopped", "blocked", "waitingIsNotRunning",
    ):
        view = cases[name]
        assert view["known"] is False, name
        assert view["state"] is None, name
        assert view["label"] == UNAVAILABLE, name
    assert cases["unavailable"] == UNAVAILABLE


def test_exact_status_is_paused_or_running(cases):
    assert cases["paused"] == {"known": True, "state": "paused", "label": "PAUSED"}
    assert cases["pausedWithoutTimestamp"]["label"] == "PAUSED"
    assert cases["running"] == {"known": True, "state": "running", "label": "RUNNING"}
    assert cases["runningAfterPauseTime"]["label"] == "RUNNING"
    assert cases["flagDoesNotOverrideRunning"]["label"] == "RUNNING"
    assert cases["flagDoesNotOverridePaused"]["label"] == "PAUSED"
    assert cases["pausedEvent"]["label"] == "PAUSED"
    assert cases["resumeRequestedStaysPaused"]["label"] == "PAUSED"
    assert cases["resumedEvent"]["label"] == "RUNNING"
    assert cases["startedSetsRunning"]["label"] == "RUNNING"


def test_chip_reads_status_and_hides_without_a_mission_or_in_preview():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="missionPauseState" class="hud-chip status" hidden>pause unavailable</span>' in html
    assert "export function missionPauseState" in state
    assert "PAUSE_STATE_UNAVAILABLE" in state
    assert "mission.status === \"paused\"" in state
    assert "mission.status === \"running\"" in state
    assert "paused_at" not in state[state.index("export function missionPauseState"):state.index("export function costHudView")]
    start = control.index('if($("missionPauseState"))')
    snippet = control[start:start + 460]
    assert "missionPauseState(mission)" in snippet
    assert "state.preview" in snippet
    assert "el.hidden=true" in snippet
    assert "textContent=view.label" in snippet
    assert "paused_at" not in snippet
    assert "paused_seconds" not in snippet


def test_loaded_mission_status_is_the_pause_field(tmp_path, monkeypatch):
    import app.main as main

    local = Store(str(tmp_path / "pause.db"))
    monkeypatch.setattr(main, "store", local)
    paused = Mission(goal="User paused this mission", status=MissionStatus.PAUSED)
    running = Mission(goal="This mission is running", status=MissionStatus.RUNNING)
    local.save_mission(paused)
    local.save_mission(running)
    with TestClient(main.app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="missionPauseState"' in page.text
        assert "pause unavailable" in page.text
        paused_body = client.get(f"/api/missions/{paused.id}")
        assert paused_body.status_code == 200
        paused_payload = paused_body.json()
        assert paused_payload["status"] == "paused"
        assert paused_payload["paused_at"] is None
        running_body = client.get(f"/api/missions/{running.id}")
        assert running_body.status_code == 200
        assert running_body.json()["status"] == "running"
