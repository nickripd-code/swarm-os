"""Mission Control cost HUD: truthful token/USD visibility, never invented spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "cost_hud_cases.mjs"
UNAVAILABLE = "estimate unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS cost HUD harness")
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


def test_idle_hud_does_not_invent_dollars(cases):
    view = cases["idle"]
    assert view["known"] is False
    assert view["tokens"] == 0
    assert view["spendLabel"] == UNAVAILABLE
    assert view["note"] == UNAVAILABLE
    assert "$" not in view["spendLabel"]


def test_llm_completed_tokens_show_without_invented_spend(cases):
    usage, view = cases["tokensOnly"]["usage"], cases["tokensOnly"]["view"]
    assert usage["input"] == 11
    assert usage["output"] == 7
    assert usage["reasoning"] == 3
    assert usage["known"] is False
    assert usage["cost"] is None
    assert view["tokens"] == 21
    assert view["spendLabel"] == UNAVAILABLE
    assert "11" in view["tokensLabel"]
    assert "$" not in view["spendLabel"]


def test_known_budget_updated_shows_usd_and_remaining(cases):
    usage, view = cases["known"]["usage"], cases["known"]["view"]
    assert usage["known"] is True
    assert usage["cost"] == 1.5
    assert usage["budget"] == 3
    assert view["known"] is True
    assert view["spendLabel"] == "$1.50"
    assert view["budgetLabel"] == "$3.00"
    assert view["remainingLabel"] == "$1.50"
    assert view["note"] == "Conservative estimate · not an invoice"
    assert UNAVAILABLE not in view["spendLabel"]


def test_unknown_budget_updated_zero_is_not_spend(cases):
    usage, view = cases["unknownZero"]["usage"], cases["unknownZero"]["view"]
    assert usage["input"] == 40
    assert usage["output"] == 10
    assert usage["known"] is False
    assert usage["cost"] is None
    assert usage["budget"] == 3
    assert view["tokens"] == 50
    assert view["spendLabel"] == UNAVAILABLE
    assert view["budgetLabel"] == "$3.00"
    assert view["remainingLabel"] is None


def test_known_without_token_spent_stays_unavailable(cases):
    usage, view = cases["missingSpend"]["usage"], cases["missingSpend"]["view"]
    assert usage["known"] is False
    assert usage["cost"] is None
    assert view["spendLabel"] == UNAVAILABLE


def test_string_token_spent_is_not_parsed_into_dollars(cases):
    usage, view = cases["stringSpend"]["usage"], cases["stringSpend"]["view"]
    assert usage["known"] is False
    assert usage["cost"] is None
    assert view["spendLabel"] == UNAVAILABLE


def test_later_unknown_estimate_does_not_wipe_known_spend(cases):
    usage, view = cases["laterUnknown"]["usage"], cases["laterUnknown"]["view"]
    assert usage["known"] is True
    assert usage["cost"] == 0.5
    assert view["spendLabel"] == "$0.50"


def test_negative_usage_and_spend_are_rejected(cases):
    usage, view = cases["negative"]["usage"], cases["negative"]["view"]
    assert usage["input"] == 0
    assert usage["output"] == 4
    assert usage["known"] is False
    assert usage["cost"] is None
    assert view["spendLabel"] == UNAVAILABLE


def test_mission_token_spent_is_not_seeded_as_known_cost(cases):
    usage, view = cases["fromMission"]["usage"], cases["fromMission"]["view"]
    assert usage["known"] is False
    assert usage["cost"] is None
    assert view["spendLabel"] == UNAVAILABLE


def test_string_known_flag_is_not_truthy_enough(cases):
    usage, view = cases["stringKnown"]["usage"], cases["stringKnown"]["view"]
    assert usage["known"] is False
    assert view["spendLabel"] == UNAVAILABLE


def test_known_zero_spend_is_honest_zero(cases):
    usage, view = cases["zeroKnown"]["usage"], cases["zeroKnown"]["view"]
    assert usage["known"] is True
    assert usage["cost"] == 0
    assert view["spendLabel"] == "$0"


def test_format_usd_never_invents_from_invalid_values(cases):
    assert cases["formatUsd"]["nan"] is None
    assert cases["formatUsd"]["inf"] is None
    assert cases["formatUsd"]["none"] is None
    assert cases["formatUsd"]["zero"] == "$0"
    assert cases["formatUsd"]["small"] == "$0.0012"
    assert cases["tokenTotal"] == 6
    assert cases["ESTIMATE_UNAVAILABLE"] == UNAVAILABLE


def test_markup_is_not_applied_in_the_hud_source():
    source = (ROOT / "app/static/state.mjs").read_text()
    control = (ROOT / "app/static/control.js").read_text()
    html = (ROOT / "app/static/index.html").read_text()
    css = (ROOT / "app/static/control.css").read_text()
    blob = source + control
    assert "price_input" not in blob
    assert "per_million" not in blob
    assert "1.25" not in blob
    assert "costHudView" in control
    assert 'id="costHud"' in html
    assert UNAVAILABLE in html
    assert ".cost-hud{" in css
    cost_block = css.split(".cost-hud{")[1].split(".alert-stack")[0]
    assert "animation" not in cost_block
    assert "@keyframes" not in cost_block


def test_static_cost_hud_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="costHud"' in page.text
        assert UNAVAILABLE in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function costHudView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".cost-hud" in css.text
