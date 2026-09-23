"""Mission Control active-mission chip: health count only, never invented."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "active_mission_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the active-mission chip harness")
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


def test_missing_or_non_numeric_stays_unavailable(cases):
    assert cases["unavailable"] == UNAVAILABLE
    for name, flagged in cases["flags"].items():
        view = cases["cases"][name]
        assert flagged is True, name
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE
        assert view["aria"] == "Active missions unavailable"
        assert view["label"] != "0 live"
        assert view["count"] != 0


def test_reported_zero_is_shown_and_not_rewritten(cases):
    view = cases["cases"]["zero"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "0 live"
    assert view["aria"] == "0 active missions"


def test_positive_counts_are_copied_verbatim(cases):
    one = cases["cases"]["one"]
    assert one["known"] is True
    assert one["count"] == 1
    assert one["label"] == "1 live"
    assert one["aria"] == "1 active mission"
    many = cases["cases"]["many"]
    assert many["count"] == 4
    assert many["label"] == "4 live"
    assert many["aria"] == "4 active missions"


def test_chip_source_reads_health_and_does_not_invent_a_count():
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert "export function activeMissionChipView" in state
    assert "Number.isSafeInteger" in state
    assert "activeMissionChipView(activeMissionHealth)" in control
    assert 'request("/api/health")' in control
    assert "activeMissionHealth=null" in control
    assert "setInterval(()=>{void refreshActiveMissions();},5000)" in control
    assert "active_missions||0" not in control
    assert "active_missions ?? 0" not in control
    assert "active_missions||" not in state
    assert 'id="activeMissionsChip"' in html
    assert 'aria-label="Active missions unavailable"' in html
    assert ">unavailable</span>" in html
    assert ">0 live<" not in html
    assert ">0<" not in html.split('id="activeMissionsChip"', 1)[1].split("</span>", 1)[0]


def test_static_active_mission_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="activeMissionsChip"' in page.text
        assert ">unavailable</span>" in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function activeMissionChipView" in state.text
        health = client.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert isinstance(body["active_missions"], int)
        assert body["active_missions"] >= 0
        assert body["active_missions"] == 0
