"""Mission Control recent missions: recorded rows only, empty list stays empty."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "recent_missions_cases.mjs"
MISSION = "11111111-1111-4111-8111-111111111111"
CREATED = "2026-09-23T08:00:00+00:00"
STARTED = "2026-09-23T09:00:00+00:00"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS recent-missions harness")
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


def test_unreadable_or_empty_lists_render_no_rows(cases):
    assert cases["empty"] == []
    assert cases["missing"] == []
    assert cases["wrapped"] == []
    assert cases["string"] == []
    assert cases["skipped"] == [{
        "id": MISSION,
        "status": "failed",
        "snippet": "real failure",
        "startedAt": CREATED,
        "startedFrom": "created_at",
    }]


def test_rows_use_recorded_fields_and_keep_api_order(cases):
    assert cases["recorded"] == [{
        "id": MISSION,
        "status": "completed",
        "snippet": "Ship the read-only mission list",
        "startedAt": CREATED,
        "startedFrom": "created_at",
    }]
    assert cases["startedPrefersExplicit"][0]["startedAt"] == STARTED
    assert cases["startedPrefersExplicit"][0]["startedFrom"] == "started_at"
    assert cases["unknownStart"] == [{
        "id": MISSION,
        "status": "pending",
        "snippet": "",
        "startedAt": None,
        "startedFrom": None,
    }]
    assert [row["id"] for row in cases["order"]] == ["a", "b"]
    assert cases["order"][1]["startedAt"] == STARTED


def test_goal_snippet_is_short_and_not_invented(cases):
    snippet = cases["snippet"][0]["snippet"]
    assert len(snippet) == cases["limit"]
    assert snippet.endswith("…")
    assert "mission" not in snippet
    assert cases["unknownStart"][0]["snippet"] == ""


def test_recent_missions_panel_is_read_only_static_markup():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    panel = html.split('id="recentMissions"', 1)[1].split("</section>", 1)[0]
    assert "No recorded missions." in panel
    assert 'id="recentMissionsEmpty"' in panel
    assert 'id="recentMissionsList"' in panel
    assert "started_at" in panel
    assert "POST" not in panel
    assert "export function recentMissionRows" in state
    assert "recentMissionRows(missions)" in control
    assert 'request("/api/missions")' in control
    assert "loadMission(id)" in control
    assert "renderRecentMissions([])" in control
    assert ".recent-missions{" in css
    assert "animation" not in css.split(".recent-missions{")[1].split(".notice{")[0]
    blob = panel + css.split(".recent-missions{")[1].split(".notice{")[0]
    assert "react" not in blob.lower()
    assert "pixi" not in blob.lower()


def test_recent_missions_panel_is_served_from_existing_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="recentMissions"' in page.text
        assert "No recorded missions." in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function recentMissionRows" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".recent-missions{" in css.text
        spec = client.get("/openapi.json").json()
        mission_list = spec["paths"]["/api/missions"]
        assert "get" in mission_list
        assert "get" in spec["paths"]["/api/missions/{mission_id}"]
        listed = client.get("/api/missions")
        assert listed.status_code == 200
        assert listed.json() == []
