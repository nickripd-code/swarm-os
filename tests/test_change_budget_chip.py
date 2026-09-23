"""Mission Control change-budget chip: recorded counts only, otherwise unavailable."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "change_budget_chip_cases.mjs"
UNAVAILABLE = "CHANGE BUDGET unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the change-budget chip harness")
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


def _assert_unavailable(view: dict) -> None:
    assert view["known"] is False
    assert view["used"] is None
    assert view["remaining"] is None
    assert view["cap"] is None
    assert view["label"] == UNAVAILABLE
    assert any(ch.isdigit() for ch in view["label"]) is False


def test_standby_hides_the_chip(cases):
    view = cases["standby"]
    assert view["visible"] is False
    _assert_unavailable(view)


def test_loaded_mission_without_a_record_says_unavailable(cases):
    view = cases["emptyMission"]
    assert view["visible"] is True
    _assert_unavailable(view)


def test_payment_token_and_tool_caps_are_not_a_change_budget(cases):
    _assert_unavailable(cases["otherBudgets"])
    assert cases["otherBudgets"]["visible"] is True


def test_preview_mission_does_not_invent_a_change_budget(cases):
    view = cases["preview"]
    assert view["visible"] is True
    _assert_unavailable(view)


def test_recorded_triple_shows_remaining_used_and_cap(cases):
    view = cases["recorded"]
    assert view["visible"] is True
    assert view["known"] is True
    assert view["used"] == 2
    assert view["remaining"] == 3
    assert view["cap"] == 5
    assert view["label"] == "CHANGE BUDGET 3 remaining · 2 used · cap 5"


def test_recorded_zero_is_shown_as_zero(cases):
    view = cases["zeroRecorded"]
    assert view["known"] is True
    assert view["used"] == 0
    assert view["remaining"] == 0
    assert view["cap"] == 0
    assert view["label"] == "CHANGE BUDGET 0 remaining · 0 used · cap 0"


@pytest.mark.parametrize(
    "name",
    ["inconsistent", "strings", "fraction", "negative", "missingRemaining", "knownFalse", "array", "topLevelCounts"],
)
def test_incomplete_or_inconsistent_records_stay_unavailable(cases, name):
    view = cases[name]
    assert view["visible"] is True
    _assert_unavailable(view)


def test_token_and_tool_events_do_not_create_a_change_budget(cases):
    view = cases["afterEvents"]
    assert view["visible"] is True
    _assert_unavailable(view)


def test_chip_source_does_not_derive_a_budget():
    source = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    fn = source.split("export function changeBudgetView", 1)[1].split("export function applyEvent", 1)[0]
    assert "change_budget" in fn
    assert "token_spent" not in fn
    assert "max_tool_calls" not in fn
    assert "max_token_cost" not in fn
    assert "mission.budget" not in fn
    assert "$" not in fn
    assert "changeBudgetView" in control
    assert 'id="changeBudgetChip"' in html
    assert "CHANGE BUDGET unavailable" in html
    assert "hidden" in html.split('id="changeBudgetChip"', 1)[1].split(">", 1)[0]
    assert ".hud-chip.change-budget[data-known=\"false\"]" in css
    chip_css = css.split(".hud-chip.change-budget", 1)[1].split("}", 1)[0]
    assert "animation" not in chip_css


def test_static_change_budget_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="changeBudgetChip"' in page.text
        assert "CHANGE BUDGET unavailable" in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function changeBudgetView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".hud-chip.change-budget" in css.text
