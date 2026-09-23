"""Read-only Mission Control chip for the newest recorded event time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_event_at_chip_cases.mjs"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-event chip harness")
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
    assert view["ariaLabel"] == ""
    assert view["createdAt"] is None


def _unavailable(view: dict) -> None:
    assert view["visible"] is True
    assert view["label"] == "unavailable"
    assert view["title"] == ""
    assert view["ariaLabel"] == "unavailable"
    assert view["createdAt"] is None
    assert "just now" not in view["label"]
    assert "1970" not in view["label"]


def test_chip_stays_hidden_without_a_known_event_time(cases):
    _hidden(cases["noMission"])
    _hidden(cases["preview"])
    _hidden(cases["noEvents"])
    _hidden(cases["notAnArray"])


@pytest.mark.parametrize(
    "name",
    [
        "missingTime",
        "blankTime",
        "whitespace",
        "numericZero",
        "numericNow",
        "stringZero",
        "epoch",
        "epochFraction",
        "epochOffset",
        "naive",
        "garbage",
        "impossibleDay",
        "newestInvalid",
        "nonObject",
    ],
)
def test_loaded_mission_with_a_bad_newest_time_says_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_event_clock_in_utc(cases):
    view = cases["clock"]
    assert view["visible"] is True
    assert view["label"] == "12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["createdAt"] == "2026-09-23T12:35:04.123456Z"
    assert view["label"] != "08:00:00Z"
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]


def test_offset_timestamps_render_as_utc_without_inventing_local_time(cases):
    view = cases["offset"]
    assert view["visible"] is True
    assert view["label"] == "12:35:04Z"
    assert view["createdAt"] == "2026-09-23T08:35:04-04:00"


def test_shell_mounts_a_hidden_last_event_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    start = html.index('id="lastEventAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    objective = html[html.rfind('<div class="hud-objective"', 0, start):html.index("</div>", start)]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("></span>")
    assert "Awaiting a mission." in objective
    assert "#lastEventAtChip{" in css
    assert "[hidden]{display:none!important}" in css
    render = control[control.index("function renderLastEventAtChip"):control.index("function clearAlerts")]
    assert "lastEventAtView(eventLog" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "toLocaleTimeString" not in render
