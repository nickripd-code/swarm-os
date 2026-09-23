"""Read-only Mission Control tool-success rate chip. Never invents a ratio."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "tool_success_rate_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the tool-success rate harness")
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


def test_chip_stays_hidden_without_a_loaded_mission_or_in_preview(cases):
    for key in ("hidden", "hiddenDefault", "preview"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["successes"] is None
        assert view["failures"] is None
        assert view["attempts"] is None
        assert view["rate"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["rate"] is None
        assert view["label"] == "SUCCESS RATE " + UNAVAILABLE
        assert view["label"] != "SUCCESS RATE 0%"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_loaded_feed_with_no_completed_attempts_stays_hidden(cases):
    for key in ("empty", "startedOnly", "beforeAny"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["successes"] == 0
        assert view["failures"] == 0
        assert view["attempts"] == 0
        assert view["rate"] is None
        assert view["label"] == ""
    assert cases["explicitEmptyFeed"] == []


def test_ratio_is_tool_completed_over_completed_attempts(cases):
    counted = cases["counted"]
    assert counted["known"] is True
    assert counted["successes"] == 3
    assert counted["failures"] == 2
    assert counted["attempts"] == 5
    assert counted["rate"] == pytest.approx(3 / 5)
    assert counted["label"] == "SUCCESS RATE 60%"
    assert cases["completesOnly"]["successes"] == 2
    assert cases["completesOnly"]["failures"] == 0
    assert cases["completesOnly"]["rate"] == 1
    assert cases["completesOnly"]["label"] == "SUCCESS RATE 100%"
    assert cases["half"]["rate"] == 0.5
    assert cases["half"]["label"] == "SUCCESS RATE 50%"
    assert cases["allFailed"]["rate"] == 0
    assert cases["allFailed"]["label"] == "SUCCESS RATE 0%"
    assert cases["third"]["label"] == "SUCCESS RATE 66.67%"
    started = cases["startedIgnored"]
    assert started["successes"] == 1
    assert started["failures"] == 0
    assert started["attempts"] == 1
    assert started["label"] == "SUCCESS RATE 100%"
    assert cases["skipsHoles"]["successes"] == 1
    assert cases["skipsHoles"]["failures"] == 1
    assert cases["skipsHoles"]["label"] == "SUCCESS RATE 50%"


def test_unreadable_rounded_rates_stay_unavailable(cases):
    tiny = cases["tiny"]
    assert tiny["known"] is False
    assert tiny["successes"] == 1
    assert tiny["failures"] == 1000000
    assert tiny["attempts"] == 1000001
    assert tiny["rate"] is None
    assert tiny["label"] == "SUCCESS RATE " + UNAVAILABLE
    assert tiny["label"] != "SUCCESS RATE 0%"
    near = cases["nearPerfect"]
    assert near["known"] is False
    assert near["successes"] == 1000000
    assert near["failures"] == 1
    assert near["attempts"] == 1000001
    assert near["rate"] is None
    assert near["label"] == "SUCCESS RATE " + UNAVAILABLE
    assert near["label"] != "SUCCESS RATE 100%"


def test_replay_prefix_uses_only_the_visible_tool_outcomes(cases):
    assert cases["prefixFirst"]["hidden"] is True
    assert cases["prefixFirst"]["attempts"] == 0
    assert cases["prefixFirst"]["label"] == ""
    assert cases["prefix"]["successes"] == 1
    assert cases["prefix"]["failures"] == 1
    assert cases["prefix"]["label"] == "SUCCESS RATE 50%"
    assert cases["prefixAll"]["successes"] == 3
    assert cases["prefixAll"]["failures"] == 2
    assert cases["prefixAll"]["label"] == "SUCCESS RATE 60%"


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function toolSuccessRateView" in state
    assert "export function recordedToolSuccessRateFeed" in state
    assert 'event_type === "tool.completed"' in state
    assert 'event_type === "tool.failed"' in state
    view_body = state.split("export function toolSuccessRateView")[1].split("export function applyEvent")[0]
    assert "tool.started" not in view_body
    assert "payload" not in view_body
    assert "llm.failed" not in view_body
    assert "llm.completed" not in view_body
    assert "state.preview?null:recordedToolSuccessRateFeed(eventLog,replayCursor,toolSuccessRateFeedLoaded)" in control
    assert "toolSuccessRateView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "toolSuccessRateFeedLoaded=options.toolSuccessRateFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "toolSuccessRateFeedLoaded=true" in control
    assert 'id="toolSuccessRateChip"' in html
    chip = html.split('id="toolSuccessRateChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert ".hud-chip.tool-success-rate[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.tool-success-rate")[1].split(".hud-stats")[0]


def test_static_tool_success_rate_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="toolSuccessRateChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function toolSuccessRateView" in state.text
