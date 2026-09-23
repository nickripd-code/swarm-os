"""Read-only Mission Control tool-fail rate chip. Never invents a ratio."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "tool_fail_rate_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the tool-fail rate harness")
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
        assert view["fails"] is None
        assert view["completes"] is None
        assert view["rate"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["rate"] is None
        assert view["label"] == "FAIL RATE " + UNAVAILABLE
        assert view["label"] != "FAIL RATE 0%"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_loaded_feed_with_no_tool_outcomes_is_zero_percent(cases):
    for key in ("empty", "noToolsYet", "beforeAny"):
        view = cases[key]
        assert view["known"] is True
        assert view["fails"] == 0
        assert view["completes"] == 0
        assert view["rate"] == 0
        assert view["label"] == "FAIL RATE 0%"
    assert cases["explicitEmptyFeed"] == []


def test_ratio_is_tool_failed_over_tool_completed(cases):
    counted = cases["counted"]
    assert counted["known"] is True
    assert counted["fails"] == 2
    assert counted["completes"] == 3
    assert counted["rate"] == pytest.approx(2 / 3)
    assert counted["label"] == "FAIL RATE 66.67%"
    assert cases["completesOnly"]["rate"] == 0
    assert cases["completesOnly"]["label"] == "FAIL RATE 0%"
    assert cases["half"]["rate"] == 0.5
    assert cases["half"]["label"] == "FAIL RATE 50%"
    assert cases["double"]["rate"] == 2
    assert cases["double"]["label"] == "FAIL RATE 200%"
    assert cases["third"]["label"] == "FAIL RATE 33.33%"
    assert cases["skipsHoles"]["fails"] == 1
    assert cases["skipsHoles"]["completes"] == 1
    assert cases["skipsHoles"]["label"] == "FAIL RATE 100%"


def test_fails_without_completes_stay_unavailable(cases):
    view = cases["failsWithoutCompletes"]
    assert view["known"] is False
    assert view["fails"] == 1
    assert view["completes"] == 0
    assert view["rate"] is None
    assert view["label"] == "FAIL RATE " + UNAVAILABLE
    tiny = cases["tiny"]
    assert tiny["known"] is False
    assert tiny["fails"] == 1
    assert tiny["completes"] == 50001
    assert tiny["rate"] is None
    assert tiny["label"] == "FAIL RATE " + UNAVAILABLE


def test_replay_prefix_uses_only_the_visible_tool_outcomes(cases):
    assert cases["prefixFirst"]["fails"] == 0
    assert cases["prefixFirst"]["completes"] == 0
    assert cases["prefixFirst"]["label"] == "FAIL RATE 0%"
    assert cases["prefix"]["fails"] == 1
    assert cases["prefix"]["completes"] == 1
    assert cases["prefix"]["label"] == "FAIL RATE 100%"
    assert cases["prefixAll"]["fails"] == 2
    assert cases["prefixAll"]["completes"] == 3
    assert cases["prefixAll"]["label"] == "FAIL RATE 66.67%"


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function toolFailRateView" in state
    assert "export function recordedToolFailRateFeed" in state
    assert 'event_type === "tool.failed"' in state
    assert 'event_type === "tool.completed"' in state
    view_body = state.split("export function toolFailRateView")[1].split("export function applyEvent")[0]
    assert "tool.started" not in view_body
    assert "payload" not in view_body
    assert "agent.online" not in state
    assert "agent.offline" not in state
    assert "state.preview?null:recordedToolFailRateFeed(eventLog,replayCursor,toolFailRateFeedLoaded)" in control
    assert "toolFailRateView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "toolFailRateFeedLoaded=options.toolFailRateFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "toolFailRateFeedLoaded=true" in control
    assert 'id="toolFailRateChip"' in html
    chip = html.split('id="toolFailRateChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert ".hud-chip.tool-fail-rate[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.tool-fail-rate")[1].split(".hud-stats")[0]


def test_static_tool_fail_rate_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="toolFailRateChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function toolFailRateView" in state.text
