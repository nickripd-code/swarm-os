"""Mission Control last-event chip: latest recorded event_type only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from uuid import uuid4

import pytest

from app.models import MissionEvent

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_event_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS last-event harness")
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
    assert view["unavailable"] is False
    assert view["label"] == ""
    assert view["eventType"] == ""
    assert view["title"] == ""
    assert view["ariaLabel"] == ""


def _unavailable(view: dict) -> None:
    assert view["visible"] is True
    assert view["unavailable"] is True
    assert view["label"] == UNAVAILABLE
    assert view["eventType"] == ""
    assert view["title"] == ""
    assert view["ariaLabel"] == "Last event unavailable"
    assert "agent.spawned" not in view["label"]


def test_mission_event_exposes_existing_event_type_field():
    event = MissionEvent(mission_id=uuid4(), event_type="agent.spawned")
    payload = event.model_dump(mode="json")
    assert payload["event_type"] == "agent.spawned"
    assert "name" not in payload


def test_no_mission_preview_and_empty_feed_stay_hidden(cases):
    for key in ("noMission", "preview", "previewMission", "empty", "missingLog", "notArray"):
        _hidden(cases[key])


def test_latest_recorded_type_is_the_log_tail(cases):
    view = cases["latest"]
    assert view["visible"] is True
    assert view["unavailable"] is False
    assert view["label"] == "llm.completed"
    assert view["eventType"] == "llm.completed"
    assert view["title"] == "llm.completed"
    assert view["ariaLabel"] == "Last event llm.completed"
    assert cases["ignoresEarlier"] == "llm.completed"
    assert cases["tailNotTimestamp"]["label"] == "agent.spawned"
    assert cases["historical"]["label"] == "custom.historical"
    assert cases["recorded"]["label"] == "task.completed"
    assert cases["duplicateIgnored"] == ["mission.started", "task.completed"]


def test_missing_latest_type_is_unavailable_and_not_invented(cases):
    for key in (
        "blank", "emptyType", "padded", "number", "objectType",
        "missingType", "nullEvent", "newline",
    ):
        _unavailable(cases[key])


def test_replay_scrub_does_not_replace_the_loaded_tail(cases):
    assert cases["replayFrame"] == "agent.spawned"
    assert cases["replayChip"]["label"] == "mission.completed"
    assert cases["replayChip"]["eventType"] == "mission.completed"


def test_chip_is_hidden_under_the_objective_and_reads_the_event_log():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    start = html.index('id="lastEventChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "unavailable" not in tag
    assert "hud-objective" in html[html.rfind("<div", 0, start):start]
    assert start < html.index('class="hud-chips"')
    assert "#lastEventChip[hidden]{display:none}" in css
    assert "max-width:100%" in css[css.index("#lastEventChip"):css.index("#lastEventChip[hidden]")]
    render = control[control.index("function renderLastEventChip"):control.index("function renderHud")]
    assert "lastEventTypeView(eventLog," in render
    assert "state.events" not in render
    assert "replayCursor" not in render
    assert "renderLastEventChip();" in control
