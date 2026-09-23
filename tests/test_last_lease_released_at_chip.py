"""Read-only Mission Control chip for the newest recorded lease.released time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_lease_released_at_chip_cases.mjs"
UNAVAILABLE = "LAST LEASE RELEASE unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-lease-released chip harness")
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


def test_missing_feed_says_last_lease_release_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE
    assert cases["notArrayLog"] is None


def test_loaded_feed_without_a_lease_released_stays_hidden(cases):
    for name in (
        "empty",
        "cursorBefore",
        "nonRelease",
        "nonObject",
        "claimedOnly",
        "expiredOnly",
        "jobOnly",
        "toolStartedOnly",
        "toolCompletedOnly",
        "otherLeaseStates",
        "questionIgnored",
        "replayBeforeRelease",
    ):
        _hidden(cases[name])
    assert cases["explicitEmptyFeed"] == []
    assert "$" not in cases["nonRelease"]["label"]
    assert "1.25" not in cases["nonRelease"]["label"]
    assert "claimed" not in cases["claimedOnly"]["label"]
    assert "expired" not in cases["expiredOnly"]["label"]
    assert "job" not in cases["jobOnly"]["label"]
    assert "tool" not in cases["toolStartedOnly"]["label"]
    assert "completed" not in cases["toolCompletedOnly"]["label"]
    assert "question" not in cases["questionIgnored"]["label"]
    assert "payment" not in cases["questionIgnored"]["label"]
    assert "warning" not in cases["questionIgnored"]["label"]
    assert "enqueued" not in cases["questionIgnored"]["label"]


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
def test_a_lease_released_without_a_valid_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_lease_released_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert "12:10:00" not in view["label"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert cases["offset"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert cases["newestByTime"]["label"] == "LAST LEASE RELEASE 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    assert cases["kinds"]["label"] == "LAST LEASE RELEASE 01:02:03Z"
    assert cases["claimedDoesNotOverride"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["expiredDoesNotOverride"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["jobDoesNotOverride"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["toolStartedDoesNotOverride"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["toolCompletedDoesNotOverride"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["claimedDoesNotOverrideLate"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["expiredDoesNotOverrideLate"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["replayPrefix"]["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert cases["replayAtLater"]["label"] == "LAST LEASE RELEASE 12:36:00Z"
    spend = cases["spendIgnored"]
    assert spend["label"] == "LAST LEASE RELEASE 12:35:04Z"
    assert "$" not in spend["label"]
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]


def test_shell_mounts_a_hidden_last_lease_released_at_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastLeaseReleasedAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert ".hud-chip.last-lease-released[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-lease-released")[1].split("}")[0]
    assert "export function lastLeaseReleasedAtView" in state
    assert "export function recordedLeaseReleasedAtFeed" in state
    assert 'LAST_LEASE_RELEASE_UNAVAILABLE = "LAST LEASE RELEASE unavailable"' in state
    event_set = state[state.index("const LEASE_RELEASED_AT_EVENTS"):state.index("];", state.index("const LEASE_RELEASED_AT_EVENTS"))]
    assert '"lease.released"' in event_set
    assert "lease.claimed" not in event_set
    assert "lease.expired" not in event_set
    assert "job.enqueued" not in event_set
    assert "tool.started" not in event_set
    assert "tool.completed" not in event_set
    assert "mission.question" not in event_set
    assert "user.answered" not in event_set
    assert "payment.created" not in event_set
    assert "budget.warning" not in event_set
    assert "mission.resumed" not in event_set
    assert "agent.spawned" not in event_set
    render = control[control.index('const leaseReleasedAtChip=$("lastLeaseReleasedAtChip")'):control.index("const running=")]
    assert "recordedLeaseReleasedAtFeed(eventLog,replayCursor,leaseReleasedAtFeedLoaded)" in render
    assert "lastLeaseReleasedAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "leaseReleasedAtFeedLoaded=options.leaseReleasedAtFeedLoaded===true" in control
    assert "leaseReleasedAtFeedLoaded=true" in control
    assert "if(Array.isArray(events))" in control


def test_static_last_lease_released_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="lastLeaseReleasedAtChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function lastLeaseReleasedAtView" in state.text
