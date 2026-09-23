"""Read-only Mission Control event-rate chip. Never invents a rate."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "event_rate_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the event-rate chip harness")
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
        assert view["rate"] is None
        assert view["label"] == ""


def test_unread_or_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["rate"] is None
        assert view["label"] == UNAVAILABLE
        assert view["label"] != "0/min"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_empty_feed_is_zero_only_with_a_known_window(cases):
    for key in ("emptyNoWindow", "emptyNegativeWindow", "emptyBadWindow", "beforeAnyNoWindow", "holesOnlyNoWindow"):
        view = cases[key]
        assert view["known"] is False
        assert view["rate"] is None
        assert view["label"] == UNAVAILABLE
    for key in ("emptyZeroWindow", "emptyKnownWindow", "beforeAny", "holesOnlyKnownWindow"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is True
        assert view["rate"] == 0
        assert view["label"] == "0/min"
    assert cases["explicitEmptyFeed"] == []


def test_missing_timestamps_do_not_invent_a_rate(cases):
    for key in ("oneStamp", "sameStamp", "missingTimestamp", "badTimestamp", "nonObject", "prefixFirst"):
        view = cases[key]
        assert view["known"] is False
        assert view["rate"] is None
        assert view["label"] == UNAVAILABLE
        assert "0" not in view["label"]


def test_rate_uses_event_log_timestamp_span(cases):
    two = cases["twoPerMinute"]
    assert two["known"] is True
    assert two["rate"] == 2
    assert two["label"] == "2/min"
    pace = cases["onePointFive"]
    assert pace["known"] is True
    assert pace["rate"] == 1.5
    assert pace["label"] == "1.5/min"
    assert cases["skipsHoles"]["rate"] == 2
    assert cases["skipsHoles"]["label"] == "2/min"
    assert cases["prefix"]["rate"] == 2
    assert cases["prefixAll"]["rate"] == 1.5
    assert cases["withHoleInLog"]["rate"] == 2
    tiny = cases["tinyRate"]
    assert tiny["known"] is False
    assert tiny["rate"] is None
    assert tiny["label"] == UNAVAILABLE


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function eventRateView" in state
    assert "export function recordedEventRateFeed" in state
    assert "export const EVENT_RATE_UNAVAILABLE" in state
    assert "state.preview?null:recordedEventRateFeed(eventLog,replayCursor,eventRateFeedLoaded)" in control
    assert "eventRateView(feed,{visible:!!(state.mission&&!state.preview),windowMs:knownEventRateWindowMs()})" in control
    assert "eventRateFeedLoaded=options.eventRateFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "eventRateFeedLoaded=true" in control
    assert 'id="eventRateChip"' in html
    chip = html.split('id="eventRateChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert ".hud-chip.event-rate[data-known=\"false\"]" in css
    rule = css.split(".hud-chip.event-rate")[1].split(".hud-stats")[0]
    assert "animation" not in rule


def test_static_event_rate_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="eventRateChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function eventRateView" in state.text
