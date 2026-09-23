"""Read-only Mission Control chip for the newest recorded park time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_park_at_chip_cases.mjs"
UNAVAILABLE = "LAST PARK unavailable"
NONE = "LAST PARK none"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-park chip harness")
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
    assert view["hidden"] is True
    assert view["label"] == ""
    assert view["known"] is False
    assert view["at"] is None
    assert view["title"] == ""


def _unavailable(view: dict) -> None:
    assert view["hidden"] is False
    assert view["label"] == UNAVAILABLE
    assert view["known"] is False
    assert view["at"] is None
    assert view["title"] == ""
    assert ":" not in view["label"]
    assert "just now" not in view["label"]
    assert "1970" not in view["label"]
    assert "ago" not in view["label"]


def _none(view: dict) -> None:
    assert view["hidden"] is False
    assert view["label"] == NONE
    assert view["known"] is True
    assert view["at"] is None
    assert view["title"] == ""
    assert ":" not in view["label"]
    assert "just now" not in view["label"]
    assert "1970" not in view["label"]
    assert "ago" not in view["label"]
    assert view["label"] != UNAVAILABLE


def test_chip_stays_hidden_without_a_mission_or_in_preview(cases):
    _hidden(cases["noMission"])
    _hidden(cases["preview"])


def test_missing_feed_says_last_park_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE


def test_loaded_feed_without_a_park_event_says_none(cases):
    for name in (
        "empty",
        "cursorBefore",
        "nonPark",
        "nonObject",
        "pauseIgnored",
        "waitingIgnored",
        "failIgnored",
        "completeIgnored",
        "replayPrefix",
    ):
        _none(cases[name])
    assert cases["none"] == NONE
    assert "$" not in cases["nonPark"]["label"]
    assert "1.25" not in cases["nonPark"]["label"]
    assert "paused" not in cases["pauseIgnored"]["label"].lower() or cases["pauseIgnored"]["label"] == NONE
    assert "waiting" not in cases["waitingIgnored"]["label"]
    assert "failed" not in cases["failIgnored"]["label"].lower() or cases["failIgnored"]["label"] == NONE
    assert "completed" not in cases["completeIgnored"]["label"].lower() or cases["completeIgnored"]["label"] == NONE


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
        "naive",
        "garbage",
        "impossibleDay",
        "newestInvalid",
    ],
)
def test_a_park_event_without_a_valid_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_park_event_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == "LAST PARK 12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert "12:40:00" not in view["label"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert cases["offset"]["label"] == "LAST PARK 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert cases["newestByTime"]["label"] == "LAST PARK 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    assert cases["approvalQuestion"]["label"] == "LAST PARK 01:02:03Z"
    assert cases["waitingDoesNotOverride"]["label"] == "LAST PARK 12:35:04Z"
    assert cases["replayAtPark"]["label"] == "LAST PARK 12:35:04Z"
    assert cases["replayAfter"]["label"] == "LAST PARK 12:35:04Z"
    spend = cases["spendIgnored"]
    assert spend["label"] == "LAST PARK 12:35:04Z"
    assert "$" not in spend["label"]
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]


def test_shell_mounts_a_hidden_last_park_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastParkAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert ".hud-chip.last-park[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-park")[1].split("}")[0]
    assert "export function lastParkAtView" in state
    assert "export function recordedParkAtFeed" in state
    assert 'LAST_PARK_UNAVAILABLE = "LAST PARK unavailable"' in state
    assert 'LAST_PARK_NONE = "LAST PARK none"' in state
    park_set = state.split("const PARK_AT_EVENTS")[1].split("]);")[0]
    assert '"mission.question"' in park_set
    assert "mission.paused" not in park_set
    assert "mission.waiting" not in park_set
    assert "mission.failed" not in park_set
    assert "mission.completed" not in park_set
    assert "PARK_AT_EVENTS.has(event.event_type)" in state.split("export function lastParkAtView")[1]
    render = control[control.index('const parkAtChip=$("lastParkAtChip")'):control.index("const running=")]
    assert "recordedParkAtFeed(eventLog,replayCursor,parkAtFeedLoaded)" in render
    assert "lastParkAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "parkAtFeedLoaded=options.parkAtFeedLoaded===true" in control
    assert "parkAtFeedLoaded=true" in control
