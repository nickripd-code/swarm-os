"""Mission Control last-updated chip: relative age from mission.updated_at only."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models import Mission

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "mission_updated_cases.mjs"
STAMP = "2026-09-23T11:56:00Z"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS updated-chip harness")
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


def _hidden(view: dict) -> None:
    assert view["visible"] is False
    assert view["label"] == ""
    assert view["title"] == ""
    assert view["updatedAt"] is None
    assert view["ageMs"] is None


def test_mission_json_uses_existing_updated_at():
    mission = Mission(
        goal="Ship it",
        created_at=datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 23, 11, 56, tzinfo=timezone.utc),
    )
    payload = mission.model_dump(mode="json")
    assert payload["updated_at"] == STAMP
    assert payload["created_at"] != payload["updated_at"]


def test_empty_missing_and_preview_stay_hidden(cases):
    for key in (
        "noMission", "preview", "createdOnly", "blank", "number", "object",
        "nullStamp", "garbage", "dateOnly", "yearOnly", "impossibleDay",
        "naive", "missingNow", "badNow", "skewHide",
    ):
        _hidden(cases[key])


def test_relative_age_uses_updated_at_not_created_at(cases):
    view = cases["minutes"]
    assert view["visible"] is True
    assert view["label"] == "Updated 4m ago"
    assert view["title"] == STAMP
    assert view["updatedAt"] == STAMP
    assert view["ageMs"] == 240000
    assert view["ariaLabel"] == "Updated 4m ago (" + STAMP + ")"
    assert "08:00:00" not in view["label"]
    assert cases["trimmed"] == view
    assert cases["offset"]["label"] == "Updated 4m ago"
    assert cases["offset"]["title"] == "2026-09-23T07:56:00-04:00"


def test_age_buckets_and_clock_skew(cases):
    assert cases["seconds"]["label"] == "Updated 59s ago"
    assert cases["oneMinute"]["label"] == "Updated 1m ago"
    assert cases["hours"]["label"] == "Updated 2h ago"
    assert cases["oneDay"]["label"] == "Updated 1d ago"
    assert cases["justNow"]["label"] == "Updated 0s ago"
    assert cases["micros"]["label"] == "Updated 59s ago"
    assert cases["micros"]["title"] == "2026-09-23T11:59:00.123456Z"
    assert cases["skewOk"]["visible"] is True
    assert cases["skewOk"]["label"] == "Updated 0s ago"
    assert cases["skewOk"]["title"] == "2026-09-23T12:02:00Z"


def test_replay_keeps_loaded_stamp_and_does_not_invent_one(cases):
    assert cases["snapshotKeepsStamp"] == STAMP
    assert cases["snapshotDoesNotInvent"] is None
    assert cases["replayKeepsLoadedStamp"] == STAMP
    assert cases["replayView"]["label"] == "Updated 4m ago"
    assert cases["replayView"]["title"] == STAMP


def test_chip_markup_is_hidden_and_wired_to_updated_at_only():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    start = html.index('id="missionUpdated"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-objective" in html[html.rfind("<div", 0, start):start]
    assert "#missionUpdated[hidden]{display:none}" in css
    render = control[control.index("function renderUpdatedChip"):control.index("function renderHud")]
    assert "missionUpdatedView" in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "setInterval(renderHud" not in control[control.index("updatedTick=setInterval"):control.index("if(!showUpdated")]
