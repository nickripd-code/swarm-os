"""Read-only Mission Control spend-remaining chip: known cost-HUD dollars only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "spend_remaining_chip_cases.mjs"
UNAVAILABLE = "estimate unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS spend-remaining chip harness")
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
    assert view["visible"] is False
    assert view["known"] is False
    assert view["remaining"] is None
    assert view["spent"] is None
    assert view["budget"] is None
    assert view["label"] == ""
    assert "$" not in view["label"]


def _unavailable(view: dict) -> None:
    assert view["visible"] is True
    assert view["known"] is False
    assert view["remaining"] is None
    assert view["spent"] is None
    assert view["budget"] is None
    assert view["label"] == UNAVAILABLE
    assert "$" not in view["label"]


def test_empty_and_preview_hide_the_chip(cases):
    _hidden(cases["none"])
    _hidden(cases["missingMission"])
    _hidden(cases["idle"])
    _hidden(cases["preview"])


def test_string_preview_flag_does_not_hide_known_spend(cases):
    view = cases["stringPreviewFlag"]
    assert view["visible"] is True
    assert view["known"] is True
    assert view["remaining"] == 1.5
    assert view["label"] == "$1.50 left · $1.50 spent"


def test_loaded_mission_without_known_dollars_is_unavailable(cases):
    _unavailable(cases["loaded"])
    _unavailable(cases["walletOnly"])
    _unavailable(cases["tokensOnly"])
    _unavailable(cases["unknownZero"])
    _unavailable(cases["missingSpend"])
    _unavailable(cases["stringSpend"])
    _unavailable(cases["negative"])
    _unavailable(cases["spendOnly"])
    _unavailable(cases["nullUsage"])


def test_known_budget_updated_shows_remaining_versus_spent(cases):
    view = cases["known"]
    assert view["visible"] is True
    assert view["known"] is True
    assert view["spent"] == 1.5
    assert view["budget"] == 3
    assert view["remaining"] == 1.5
    assert view["label"] == "$1.50 left · $1.50 spent"
    assert UNAVAILABLE not in view["label"]


def test_known_zero_spend_is_honest_zero(cases):
    view = cases["zeroKnown"]
    assert view["known"] is True
    assert view["spent"] == 0
    assert view["remaining"] == 3
    assert view["label"] == "$3.00 left · $0 spent"


def test_known_overspend_is_not_clamped_to_zero(cases):
    view = cases["over"]
    assert view["known"] is True
    assert view["spent"] == 4
    assert view["budget"] == 3
    assert view["remaining"] == -1
    assert view["label"].endswith("spent")
    assert "$0 left" not in view["label"]
    assert "$4.00 spent" in view["label"]


def test_chip_source_does_not_invent_spend_or_animate():
    source = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    fn = source.split("export function spendRemainingChip", 1)[1].split("export function applyEvent", 1)[0]
    assert "token_spent" not in fn
    assert "max_token_cost" not in fn
    assert ".spent" not in fn
    assert "stripe" not in fn.lower()
    assert "costHudView" in fn
    assert "spendRemainingChip" in control
    assert 'id="spendRemainingChip"' in html
    assert "hidden" in html.split('id="spendRemainingChip"', 1)[1].split(">", 1)[0]
    assert ".hud-chip.spend{" in css
    block = css.split(".hud-chip.spend{", 1)[1].split(".hud-chips{", 1)[0]
    assert "animation" not in block
    assert "@keyframes" not in block
