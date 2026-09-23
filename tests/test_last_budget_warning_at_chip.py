"""Read-only Mission Control chip for the newest recorded budget-warning time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_budget_warning_at_chip_cases.mjs"
UNAVAILABLE = "LAST BUDGET WARN unavailable"
NONE = "LAST BUDGET WARN none"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-budget-warning chip harness")
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
    assert "$" not in view["label"]


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
    assert "$" not in view["label"]


def _clock_only(view: dict, label: str) -> None:
    assert view["label"] == label
    assert "$" not in view["label"]
    assert "1.25" not in view["label"]
    assert "9.5" not in view["label"]
    assert "0.5" not in view["label"]
    assert "0.8" not in view["label"]
    assert "100" not in view["label"]
    assert "token" not in view["label"].lower()
    assert "USD" not in view["label"]


def test_chip_stays_hidden_without_a_mission_or_in_preview(cases):
    _hidden(cases["noMission"])
    _hidden(cases["preview"])


def test_missing_feed_says_last_budget_warn_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE


def test_loaded_feed_without_an_accepted_warning_says_none(cases):
    for name in ("empty", "cursorBefore", "nonWarning", "nonObject", "replayBeforeWarning"):
        _none(cases[name])
    assert cases["none"] == NONE
    assert "$" not in cases["nonWarning"]["label"]
    assert "1.25" not in cases["nonWarning"]["label"]


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
def test_an_accepted_warning_without_a_valid_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_accepted_warning_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    _clock_only(view, "LAST BUDGET WARN 12:35:04Z")
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert cases["offset"]["label"] == "LAST BUDGET WARN 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert "$" not in cases["offset"]["label"]
    assert "2.5" not in cases["offset"]["label"]
    assert cases["newestByTime"]["label"] == "LAST BUDGET WARN 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    _clock_only(cases["zeroSpend"], "LAST BUDGET WARN 01:02:03Z")
    _clock_only(cases["spendAfterWarning"], "LAST BUDGET WARN 12:35:04Z")
    assert cases["replayPrefix"]["label"] == "LAST BUDGET WARN 12:35:04Z"
    assert cases["replayAtLater"]["label"] == "LAST BUDGET WARN 12:36:00Z"
    amount = cases["amountIgnored"]
    _clock_only(amount, "LAST BUDGET WARN 12:35:04Z")
    assert amount["title"] == "2026-09-23T12:35:04Z"


def test_shell_mounts_a_hidden_last_budget_warning_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastBudgetWarningAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert ".hud-chip.last-budget-warn[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-budget-warn")[1].split("}")[0]
    assert "export function lastBudgetWarningAtView" in state
    assert "export function recordedBudgetWarningAtFeed" in state
    assert 'LAST_BUDGET_WARN_AT_UNAVAILABLE = "LAST BUDGET WARN unavailable"' in state
    assert 'LAST_BUDGET_WARN_AT_NONE = "LAST BUDGET WARN none"' in state
    assert 'event_type !== "budget.warning"' in state
    render = control[control.index('const budgetWarnAtChip=$("lastBudgetWarningAtChip")'):control.index("const running=")]
    assert "recordedBudgetWarningAtFeed(eventLog,replayCursor,budgetWarnAtFeedLoaded)" in render
    assert "lastBudgetWarningAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "token_budget" not in render
    assert "budgetWarnAtFeedLoaded=options.budgetWarnAtFeedLoaded===true" in control
    assert "budgetWarnAtFeedLoaded=true" in control
