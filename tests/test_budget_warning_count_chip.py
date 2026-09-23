"""Read-only Mission Control budget-warning count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "budget_warning_count_chip_cases.mjs"
UNAVAILABLE = "BUDGET WARNINGS unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the budget-warning count chip harness")
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


def _no_spend(label: str) -> None:
    assert "$" not in label
    assert "USD" not in label
    assert "token" not in label.lower()
    for amount in ("9.5", "1.25", "2.5", "0.8", "100", "7.5"):
        assert amount not in label


def test_chip_stays_hidden_without_a_loaded_mission_or_in_preview(cases):
    for key in ("hidden", "hiddenDefault", "preview"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE
        _no_spend(view["label"])
        assert view["label"] != "0"
        assert not view["label"].endswith(" 0")
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "BUDGET WARNINGS 0"
    _no_spend(view["label"])
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "BUDGET WARNINGS 0"


def test_counts_accepted_budget_warnings_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "BUDGET WARNINGS 3"
    _no_spend(view["label"])
    assert cases["ignoresUpdated"]["count"] == 0
    assert cases["ignoresPayment"]["count"] == 0
    assert cases["ignoresStringNumbers"]["count"] == 0
    assert cases["ignoresMissingPayload"]["count"] == 0
    assert cases["ignoresArrayPayload"]["count"] == 0
    assert cases["ignoresNaN"]["count"] == 0
    assert cases["ignoresInfinity"]["count"] == 0
    assert cases["ignoresNegative"]["count"] == 0
    assert cases["countsZeroSpend"]["count"] == 1
    assert cases["countsZeroSpend"]["label"] == "BUDGET WARNINGS 1"
    _no_spend(cases["countsZeroSpend"]["label"])
    assert cases["malformedDoesNotPoison"]["count"] == 1
    assert cases["malformedDoesNotPoison"]["known"] is True
    assert cases["malformedDoesNotPoison"]["label"] == "BUDGET WARNINGS 1"
    assert cases["skipsHoles"]["count"] == 1


def test_replay_prefix_does_not_include_later_budget_warnings(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefixFirst"]["label"] == "BUDGET WARNINGS 0"
    assert cases["prefix"]["count"] == 1
    assert cases["prefix"]["label"] == "BUDGET WARNINGS 1"
    assert cases["prefixAll"]["count"] == 3
    _no_spend(cases["prefix"]["label"])


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function budgetWarningCountView" in state
    assert "export function recordedBudgetWarningCountFeed" in state
    assert 'BUDGET_WARNING_COUNT_UNAVAILABLE = "BUDGET WARNINGS unavailable"' in state
    assert 'event_type !== "budget.warning"' in state
    view_body = state.split("export function budgetWarningCountView")[1]
    assert "budget.updated" not in view_body
    assert "payment." not in view_body
    assert "formatUsd" not in view_body
    assert "token_spent" not in view_body
    assert "token_budget" not in view_body
    assert "state.preview?null:recordedBudgetWarningCountFeed(eventLog,replayCursor,budgetWarningCountFeedLoaded)" in control
    assert "budgetWarningCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "budgetWarningCountFeedLoaded=options.budgetWarningCountFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "budgetWarningCountFeedLoaded=true" in control
    assert 'id="budgetWarningCountChip"' in html
    start = html.index('id="budgetWarningCountChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert "aria-label=\"Accepted budget warnings\"" in tag
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert "unavailable" not in tag
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    render = control[control.index('const budgetWarnCountChip=$("budgetWarningCountChip")'):control.index("const running=")]
    assert "formatUsd" not in render
    assert "token_spent" not in render
    assert "token_budget" not in render
    assert "Date.now" not in render
    assert ".hud-chip.budget-warn-count[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.budget-warn-count")[1].split(".hud-stats")[0]


def test_static_budget_warning_count_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="budgetWarningCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function budgetWarningCountView" in state.text
