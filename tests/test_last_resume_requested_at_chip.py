"""Read-only Mission Control chip for the newest recorded mission.resume_requested time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_resume_requested_at_chip_cases.mjs"
UNAVAILABLE = "LAST RESUME REQUESTED unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-resume-requested chip harness")
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


def test_missing_feed_says_last_resume_requested_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE
    assert cases["notArrayLog"] is None


def test_loaded_feed_without_a_resume_requested_stays_hidden(cases):
    for name in (
        "empty",
        "cursorBefore",
        "nonRequest",
        "nonObject",
        "resumedOnly",
        "startedOnly",
        "runningOnly",
        "pausedOnly",
        "otherEvents",
        "questionIgnored",
        "replayBeforeRequest",
    ):
        _hidden(cases[name])
    assert cases["explicitEmptyFeed"] == []
    assert "$" not in cases["nonRequest"]["label"]
    assert "1.25" not in cases["nonRequest"]["label"]
    assert "resumed" not in cases["resumedOnly"]["label"]
    assert "started" not in cases["startedOnly"]["label"]
    assert "running" not in cases["runningOnly"]["label"]
    assert "paused" not in cases["pausedOnly"]["label"]
    assert "question" not in cases["questionIgnored"]["label"]
    assert "payment" not in cases["questionIgnored"]["label"]
    assert "warning" not in cases["questionIgnored"]["label"]
    assert "retry" not in cases["questionIgnored"]["label"]


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
def test_a_resume_requested_without_a_valid_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_resume_requested_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert "12:10:00" not in view["label"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert "paused" not in view["label"]
    assert "User" not in view["label"]
    assert cases["offset"]["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert cases["newestByTime"]["label"] == "LAST RESUME REQUESTED 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    assert cases["kinds"]["label"] == "LAST RESUME REQUESTED 01:02:03Z"
    assert "paused" not in cases["kinds"]["label"]
    assert "User" not in cases["kinds"]["label"]
    assert cases["resumedDoesNotOverride"]["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert cases["startedDoesNotOverride"]["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert cases["runningDoesNotOverride"]["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert cases["pausedDoesNotOverride"]["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert cases["replayPrefix"]["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert cases["replayAtLater"]["label"] == "LAST RESUME REQUESTED 12:36:00Z"
    spend = cases["spendIgnored"]
    assert spend["label"] == "LAST RESUME REQUESTED 12:35:04Z"
    assert "$" not in spend["label"]
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]
    assert "User" not in spend["label"]


def test_shell_mounts_a_hidden_last_resume_requested_at_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastResumeRequestedAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert ".hud-chip.last-resume-requested[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-resume-requested")[1].split("}")[0]
    assert "export function lastResumeRequestedAtView" in state
    assert "export function recordedResumeRequestedAtFeed" in state
    assert 'LAST_RESUME_REQUESTED_UNAVAILABLE = "LAST RESUME REQUESTED unavailable"' in state
    event_set = state[state.index("const RESUME_REQUESTED_AT_EVENTS"):state.index("];", state.index("const RESUME_REQUESTED_AT_EVENTS"))]
    assert '"mission.resume_requested"' in event_set
    assert "mission.resumed" not in event_set
    assert "mission.started" not in event_set
    assert "mission.running" not in event_set
    assert "mission.paused" not in event_set
    assert "job.started" not in event_set
    assert "worker.heartbeat" not in event_set
    assert "task.suspended" not in event_set
    render = control[control.index('const resumeRequestedAtChip=$("lastResumeRequestedAtChip")'):control.index("const running=")]
    assert "recordedResumeRequestedAtFeed(eventLog,replayCursor,resumeRequestedAtFeedLoaded)" in render
    assert "lastResumeRequestedAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "resumeRequestedAtFeedLoaded=options.resumeRequestedAtFeedLoaded===true" in control
    assert "resumeRequestedAtFeedLoaded=true" in control
    assert "if(Array.isArray(events))" in control


def test_static_last_resume_requested_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="lastResumeRequestedAtChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function lastResumeRequestedAtView" in state.text
