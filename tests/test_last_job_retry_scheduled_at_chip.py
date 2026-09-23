"""Read-only Mission Control chip for the newest recorded job.retry_scheduled time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_job_retry_scheduled_at_chip_cases.mjs"
UNAVAILABLE = "LAST JOB RETRY SCHEDULED unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-job-retry-scheduled chip harness")
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
    assert "count" not in view


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
    assert "count" not in view


def test_job_retry_scheduled_is_catalogued_and_absent_names_are_not():
    from app.events import EventType, KNOWN_EVENT_TYPES

    assert EventType.JOB_RETRY_SCHEDULED == "job.retry_scheduled"
    assert "job.retry_scheduled" in KNOWN_EVENT_TYPES
    assert "job.started" not in KNOWN_EVENT_TYPES
    assert "worker.heartbeat" not in KNOWN_EVENT_TYPES


def test_chip_stays_hidden_without_a_mission_or_in_preview(cases):
    _hidden(cases["noMission"])
    _hidden(cases["preview"])


def test_missing_feed_says_last_job_retry_scheduled_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE
    assert cases["notArrayLog"] is None


def test_loaded_feed_without_a_job_retry_scheduled_stays_hidden(cases):
    for name in (
        "empty",
        "cursorBefore",
        "nonRetry",
        "nonObject",
        "enqueuedOnly",
        "completedOnly",
        "failedOnly",
        "leaseReleasedOnly",
        "llmRetryOnly",
        "toolCompletedOnly",
        "missionFailedOnly",
        "taskFailedOnly",
        "otherJobStates",
        "questionIgnored",
        "replayBeforeRetry",
    ):
        _hidden(cases[name])
    assert cases["explicitEmptyFeed"] == []
    assert "$" not in cases["nonRetry"]["label"]
    assert "1.25" not in cases["nonRetry"]["label"]
    assert "enqueued" not in cases["enqueuedOnly"]["label"]
    assert "completed" not in cases["completedOnly"]["label"]
    assert "failed" not in cases["failedOnly"]["label"]
    assert "lease" not in cases["leaseReleasedOnly"]["label"]
    assert "llm" not in cases["llmRetryOnly"]["label"]
    assert "tool" not in cases["toolCompletedOnly"]["label"]
    assert "mission" not in cases["missionFailedOnly"]["label"]
    assert "task" not in cases["taskFailedOnly"]["label"]
    assert "question" not in cases["questionIgnored"]["label"]
    assert "payment" not in cases["questionIgnored"]["label"]
    assert "warning" not in cases["questionIgnored"]["label"]


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
        "payloadStampOnly",
        "newestInvalid",
    ],
)
def test_a_job_retry_scheduled_without_a_valid_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_job_retry_scheduled_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "count" not in view
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert "12:10:00" not in view["label"]
    assert "18:00:00" not in view["label"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert cases["offset"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert cases["newestByTime"]["label"] == "LAST JOB RETRY SCHEDULED 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    assert cases["kinds"]["label"] == "LAST JOB RETRY SCHEDULED 01:02:03Z"
    assert cases["enqueuedDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["completedDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["failedDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["leaseDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["llmRetryDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["toolCompletedDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["missionFailedDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["taskFailedDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["availableAtDoesNotOverride"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert "18:00:00" not in cases["availableAtDoesNotOverride"]["label"]
    assert cases["replayPrefix"]["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert cases["replayAtLater"]["label"] == "LAST JOB RETRY SCHEDULED 12:36:00Z"
    spend = cases["spendIgnored"]
    assert spend["label"] == "LAST JOB RETRY SCHEDULED 12:35:04Z"
    assert "$" not in spend["label"]
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]


def test_shell_mounts_a_hidden_last_job_retry_scheduled_at_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastJobRetryScheduledAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert "jobRetryScheduledCountChip" not in html
    assert ".hud-chip.last-job-retry-scheduled[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-job-retry-scheduled")[1].split("}")[0]
    assert "export function lastJobRetryScheduledAtView" in state
    assert "export function recordedJobRetryScheduledAtFeed" in state
    assert "export function jobRetryScheduledCountView" not in state
    assert 'LAST_JOB_RETRY_SCHEDULED_UNAVAILABLE = "LAST JOB RETRY SCHEDULED unavailable"' in state
    event_set = state[state.index("const JOB_RETRY_SCHEDULED_AT_EVENTS"):state.index("];", state.index("const JOB_RETRY_SCHEDULED_AT_EVENTS"))]
    assert '"job.retry_scheduled"' in event_set
    assert "job.enqueued" not in event_set
    assert "job.completed" not in event_set
    assert "job.failed" not in event_set
    assert "lease.released" not in event_set
    assert "llm.retry" not in event_set
    assert "tool.completed" not in event_set
    assert "mission.failed" not in event_set
    assert "task.failed" not in event_set
    assert "job.started" not in event_set
    assert "worker.heartbeat" not in event_set
    render = control[control.index('const jobRetryScheduledAtChip=$("lastJobRetryScheduledAtChip")'):control.index("const running=")]
    assert "recordedJobRetryScheduledAtFeed(eventLog,replayCursor,jobRetryScheduledAtFeedLoaded)" in render
    assert "lastJobRetryScheduledAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "available_at" not in render
    assert "jobRetryScheduledAtFeedLoaded=options.jobRetryScheduledAtFeedLoaded===true" in control
    assert "jobRetryScheduledAtFeedLoaded=true" in control
    assert "if(Array.isArray(events))" in control


def test_static_last_job_retry_scheduled_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="lastJobRetryScheduledAtChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function lastJobRetryScheduledAtView" in state.text
