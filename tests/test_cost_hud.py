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


def test_idle_burn_rate_is_unavailable(cases):
    view = cases["burnIdle"]
    assert view["state"] == "unavailable"
    assert view["tokensAvailable"] is False
    assert view["usdKnown"] is False
    assert view["tokensLabel"] == "unavailable"
    assert view["usdLabel"] == UNAVAILABLE
    assert view["tokensPerMin"] is None
    assert view["usdPerMin"] is None
    assert "$" not in view["tokensLabel"]
    assert "$" not in view["usdLabel"]


def test_llm_completed_burn_shows_tokens_per_min_without_dollars(cases):
    view = cases["burnTokensOnly"]
    assert view["tokensAvailable"] is True
    assert view["tokensPerMin"] == 125
    assert view["tokensLabel"] == "125 tokens/min"
    assert view["usdKnown"] is False
    assert view["usdLabel"] == UNAVAILABLE
    assert "$" not in view["usdLabel"]
    assert "USD estimate unavailable" in view["note"]


def test_burn_window_sums_live_samples_and_drops_stale_ones(cases):
    assert cases["burnSummed"]["tokensPerMin"] == 70
    assert cases["burnSummed"]["tokensLabel"] == "70 tokens/min"
    stale = cases["burnStale"]
    assert stale["samples"] == 1
    assert stale["view"]["tokensPerMin"] == 32
    assert stale["view"]["usdLabel"] == UNAVAILABLE


def test_known_budget_updates_show_usd_per_min_from_recorded_increments(cases):
    view = cases["burnUsd"]
    assert view["tokensPerMin"] == 10
    assert view["usdKnown"] is True
    assert view["usdPerMin"] == 0.4
    assert view["usdLabel"] == "$0.40/min"
    assert "not an invoice" in view["note"]
    assert view["windowMs"] == 60000


def test_unknown_or_non_numeric_spend_does_not_invent_usd_per_min(cases):
    unknown = cases["burnUnknownSpend"]
    assert unknown["sample"] is None
    assert unknown["view"]["tokensPerMin"] == 10
    assert unknown["view"]["usdKnown"] is False
    assert unknown["view"]["usdLabel"] == UNAVAILABLE
    string_spend = cases["burnStringSpend"]
    assert string_spend["sample"] is None
    assert string_spend["view"]["tokensLabel"] == "unavailable"
    assert string_spend["view"]["usdLabel"] == UNAVAILABLE
    assert cases["burnStringKnown"]["usdKnown"] is False
    assert cases["burnStringKnown"]["usdLabel"] == UNAVAILABLE
    assert cases["burnStringKnown"]["tokensPerMin"] == 5


def test_negative_usage_does_not_invent_burn(cases):
    view = cases["burnNegative"]
    assert view["tokensPerMin"] == 6
    assert view["usdKnown"] is False
    assert view["usdLabel"] == UNAVAILABLE
    assert "$" not in view["usdLabel"]


def test_cumulative_spend_needs_two_in_window_samples(cases):
    lone = cases["burnLoneCumulative"]
    assert lone["tokensAvailable"] is True
    assert lone["tokensPerMin"] == 0
    assert lone["tokensLabel"] == "0 tokens/min"
    assert lone["usdKnown"] is False
    assert lone["usdLabel"] == UNAVAILABLE
    assert "$" not in lone["usdLabel"]
    pair = cases["burnCumulativePair"]
    assert pair["usdKnown"] is True
    assert pair["usdPerMin"] == 0.2
    assert pair["usdLabel"] == "$0.20/min"
    straddle = cases["burnStraddle"]
    assert straddle["usdKnown"] is False
    assert straddle["usdLabel"] == UNAVAILABLE
    assert "$" not in straddle["usdLabel"]


def test_known_zero_increment_is_honest_zero_burn(cases):
    view = cases["burnZeroKnown"]
    assert view["usdKnown"] is True
    assert view["usdPerMin"] == 0
    assert view["usdLabel"] == "$0/min"


def test_preview_and_replay_do_not_fabricate_burn(cases):
    for key in ("burnPreview", "burnReplay"):
        view = cases[key]
        assert view["tokensAvailable"] is False
        assert view["usdKnown"] is False
        assert view["tokensPerMin"] is None
        assert view["usdPerMin"] is None
        assert view["tokensLabel"] == "unavailable"
        assert view["usdLabel"] == UNAVAILABLE
        assert "$" not in view["tokensLabel"]
        assert "$" not in view["usdLabel"]
        assert "$" not in view["note"]
    assert cases["burnPreview"]["state"] == "preview"
    assert cases["burnReplay"]["state"] == "replay"
    assert "Preview" in cases["burnPreview"]["note"]
    assert "Replay" in cases["burnReplay"]["note"]


def test_live_burn_clock_rejects_stale_and_future_events(cases):
    clock = cases["burnLiveAt"]
    assert clock["missing"] == 1_700_000_000_000
    assert clock["stale"] is None
    assert clock["future"] is None
    assert clock["fresh"] == 1_700_000_000_000 - 1000
    assert cases["BURN_WINDOW_MS"] == 60000
    assert cases["BURN_UNAVAILABLE"] == "unavailable"


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
    assert "burnRateView" in control
    assert "noteLiveBurn" in control
    assert 'id="costHud"' in html
    assert 'id="burnRateHud"' in html
    assert UNAVAILABLE in html
    assert ".cost-hud{" in css
    assert ".burn-hud{" in css
    cost_block = css.split(".cost-hud{")[1].split(".alert-stack")[0]
    assert "animation" not in cost_block
    assert "@keyframes" not in cost_block
    onmessage = control.split("ws.onmessage", 1)[1].split("ws.onerror", 1)[0]
    assert "noteLiveBurn" in onmessage
    loaded = control.split("async function loadMission", 1)[1].split("async function refreshHistory", 1)[0]
    assert "noteLiveBurn" not in loaded
    assert "burnSamples=[]" in control


def test_static_cost_hud_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="costHud"' in page.text
        assert 'id="burnRateHud"' in page.text
        assert UNAVAILABLE in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function costHudView" in state.text
        assert "export function burnRateView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".cost-hud" in css.text
        assert ".burn-hud" in css.text
