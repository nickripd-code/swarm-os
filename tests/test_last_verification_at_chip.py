"""Read-only Mission Control chip for the newest recorded verification-event time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_verification_at_chip_cases.mjs"
UNAVAILABLE = "LAST VERIFY unavailable"
NONE = "LAST VERIFY none"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-verify chip harness")
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


def test_missing_feed_says_last_verify_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE


def test_loaded_feed_without_a_verification_event_says_none(cases):
    for name in ("empty", "cursorBefore", "nonVerification", "nonObject", "evidenceIgnored"):
        _none(cases[name])
    assert cases["none"] == NONE
    assert "$" not in cases["nonVerification"]["label"]
    assert "1.25" not in cases["nonVerification"]["label"]
    assert "evidence" not in cases["evidenceIgnored"]["label"]


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
def test_a_verification_event_without_a_valid_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_verification_event_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == "LAST VERIFY 12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert cases["offset"]["label"] == "LAST VERIFY 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert cases["newestByTime"]["label"] == "LAST VERIFY 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    assert cases["kinds"]["label"] == "LAST VERIFY 01:02:03Z"
    assert cases["evidenceDoesNotOverride"]["label"] == "LAST VERIFY 12:35:04Z"
    assert cases["replayPrefix"]["label"] == "LAST VERIFY 12:35:04Z"
    assert cases["replayAtLater"]["label"] == "LAST VERIFY 12:36:00Z"
    spend = cases["spendIgnored"]
    assert spend["label"] == "LAST VERIFY 12:35:04Z"
    assert "$" not in spend["label"]
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]


def test_shell_mounts_a_hidden_last_verification_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastVerificationAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert ".hud-chip.last-verify[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-verify")[1].split("}")[0]
    assert "export function lastVerificationAtView" in state
    assert "export function recordedVerificationAtFeed" in state
    assert 'LAST_VERIFY_AT_UNAVAILABLE = "LAST VERIFY unavailable"' in state
    assert 'LAST_VERIFY_AT_NONE = "LAST VERIFY none"' in state
    assert '"verification.started"' in state
    assert '"verification.passed"' in state
    assert '"verification.failed"' in state
    render = control[control.index('const verifyAtChip=$("lastVerificationAtChip")'):control.index("const running=")]
    assert "recordedVerificationAtFeed(eventLog,replayCursor,verificationAtFeedLoaded)" in render
    assert "lastVerificationAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "verificationAtFeedLoaded=options.verificationAtFeedLoaded===true" in control
    assert "verificationAtFeedLoaded=true" in control
