"""Read-only Mission Control chip for the newest recorded agent.retired time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_retired_at_chip_cases.mjs"
UNAVAILABLE = "LAST RETIRE unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-retired chip harness")
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


def test_chip_stays_hidden_without_a_mission_or_in_preview(cases):
    _hidden(cases["noMission"])
    _hidden(cases["preview"])


def test_missing_feed_says_last_retire_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE


def test_loaded_feed_without_an_agent_retired_event_stays_hidden(cases):
    for name in (
        "empty",
        "cursorBefore",
        "nonRetire",
        "nonObject",
        "orgIgnored",
        "killedOnly",
        "spawnedOnly",
        "updatedOnly",
        "stoppedOnly",
        "proposalOnly",
        "replayBeforeRetire",
    ):
        _hidden(cases[name])
    assert "$" not in cases["nonRetire"]["label"]
    assert "1.25" not in cases["nonRetire"]["label"]
    assert "killed" not in cases["killedOnly"]["label"]
    assert "spawned" not in cases["spawnedOnly"]["label"]
    assert "updated" not in cases["updatedOnly"]["label"]
    assert "stopped" not in cases["stoppedOnly"]["label"]
    assert "proposal" not in cases["proposalOnly"]["label"]
    assert "killed" not in cases["orgIgnored"]["label"]


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
def test_an_agent_retired_event_without_a_valid_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_agent_retired_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == "LAST RETIRE 12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert "12:10:00" not in view["label"]
    assert "12:20:00" not in view["label"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert cases["offset"]["label"] == "LAST RETIRE 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert cases["newestByTime"]["label"] == "LAST RETIRE 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    assert cases["kinds"]["label"] == "LAST RETIRE 01:02:03Z"
    assert cases["killedDoesNotOverride"]["label"] == "LAST RETIRE 12:35:04Z"
    assert cases["spawnedDoesNotOverride"]["label"] == "LAST RETIRE 12:35:04Z"
    assert cases["proposalDoesNotOverride"]["label"] == "LAST RETIRE 12:35:04Z"
    assert cases["stoppedDoesNotOverride"]["label"] == "LAST RETIRE 12:35:04Z"
    assert cases["replayPrefix"]["label"] == "LAST RETIRE 12:35:04Z"
    assert cases["replayAtLater"]["label"] == "LAST RETIRE 12:36:00Z"
    spend = cases["spendIgnored"]
    assert spend["label"] == "LAST RETIRE 12:35:04Z"
    assert "$" not in spend["label"]
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]


def test_shell_mounts_a_hidden_last_retired_at_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastRetiredAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert ".hud-chip.last-retire[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-retire")[1].split("}")[0]
    assert "export function lastRetiredAtView" in state
    assert "export function recordedRetiredAtFeed" in state
    assert 'LAST_RETIRE_UNAVAILABLE = "LAST RETIRE unavailable"' in state
    event_set = state[state.index("const RETIRED_AT_EVENTS"):state.index("];", state.index("const RETIRED_AT_EVENTS"))]
    assert '"agent.retired"' in event_set
    assert "agent.killed" not in event_set
    assert "agent.spawned" not in event_set
    assert "agent.updated" not in event_set
    assert "agent.reparented" not in event_set
    assert "planner.proposal" not in event_set
    assert "task.stopped" not in event_set
    render = control[control.index('const retiredAtChip=$("lastRetiredAtChip")'):control.index("const running=")]
    assert "recordedRetiredAtFeed(eventLog,replayCursor,retiredAtFeedLoaded)" in render
    assert "lastRetiredAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "retiredAtFeedLoaded=options.retiredAtFeedLoaded===true" in control
    assert "retiredAtFeedLoaded=true" in control
