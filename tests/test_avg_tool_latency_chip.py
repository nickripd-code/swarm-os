"""Read-only Mission Control average tool-latency chip. Never invents a duration."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "avg_tool_latency_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the average tool-latency harness")
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
        assert view["count"] is None
        assert view["meanMs"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["meanMs"] is None
        assert view["label"] == "AVG TOOL LATENCY " + UNAVAILABLE
        assert view["label"] != "AVG TOOL LATENCY 0ms"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_loaded_feed_with_no_completed_tool_stays_hidden(cases):
    for key in ("empty", "startedOnly", "failedOnly", "beforeAny", "prefixFirst"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] == 0
        assert view["meanMs"] is None
        assert view["label"] == ""
    assert cases["explicitEmptyFeed"] == []


def test_mean_is_completed_tool_durations_not_the_newest(cases):
    counted = cases["counted"]
    assert counted["known"] is True
    assert counted["count"] == 2
    assert counted["meanMs"] == pytest.approx(300)
    assert counted["label"] == "AVG TOOL LATENCY 300ms"
    newest = cases["meanNotNewest"]
    assert newest["count"] == 2
    assert newest["meanMs"] == pytest.approx(300)
    assert newest["label"] == "AVG TOOL LATENCY 300ms"
    assert newest["label"] != "AVG TOOL LATENCY 500ms"
    spans = cases["spans"]
    assert spans["count"] == 2
    assert spans["meanMs"] == pytest.approx(300)
    assert spans["label"] == "AVG TOOL LATENCY 300ms"
    assert cases["explicitBeatsStamps"]["meanMs"] == pytest.approx(40)
    assert cases["explicitBeatsStamps"]["label"] == "AVG TOOL LATENCY 40ms"
    paired = cases["pairedByTool"]
    assert paired["count"] == 2
    assert paired["meanMs"] == pytest.approx(300)
    assert paired["label"] == "AVG TOOL LATENCY 300ms"
    assert cases["includesZero"]["count"] == 2
    assert cases["includesZero"]["meanMs"] == pytest.approx(50)
    assert cases["includesZero"]["label"] == "AVG TOOL LATENCY 50ms"
    assert cases["ignoresLlm"]["count"] == 1
    assert cases["ignoresLlm"]["meanMs"] == pytest.approx(80)
    assert cases["ignoresLlm"]["label"] == "AVG TOOL LATENCY 80ms"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["skipsHoles"]["label"] == "AVG TOOL LATENCY 40ms"
    assert cases["oneSecond"]["meanMs"] == pytest.approx(1500)
    assert cases["oneSecond"]["label"] == "AVG TOOL LATENCY 1s"
    assert cases["minutes"]["label"] == "AVG TOOL LATENCY 1m 30s"
    assert cases["hours"]["label"] == "AVG TOOL LATENCY 1h 2m"


def test_honest_zero_is_shown_only_when_the_mean_is_zero(cases):
    assert cases["zero"]["known"] is True
    assert cases["zero"]["count"] == 1
    assert cases["zero"]["meanMs"] == 0
    assert cases["zero"]["label"] == "AVG TOOL LATENCY 0ms"
    assert cases["zeroSpan"]["known"] is True
    assert cases["zeroSpan"]["meanMs"] == 0
    assert cases["zeroSpan"]["label"] == "AVG TOOL LATENCY 0ms"


def test_unreadable_duration_stays_unavailable(cases):
    for key in (
        "blankLatency", "negativeLatency", "stringLatency", "nullLatency",
        "missingStamps", "negativeSpan", "failedConsumesStart", "partialUnreadable",
        "subMillisecond",
    ):
        view = cases[key]
        assert view["hidden"] is False, key
        assert view["known"] is False, key
        assert view["meanMs"] is None, key
        assert view["count"] >= 1, key
        assert view["label"] == "AVG TOOL LATENCY " + UNAVAILABLE, key
        assert view["label"] != "AVG TOOL LATENCY 0ms", key
    assert cases["partialUnreadable"]["count"] == 2
    assert cases["failedConsumesStart"]["count"] == 1


def test_replay_prefix_uses_only_the_visible_completed_tools(cases):
    assert cases["prefix"]["count"] == 1
    assert cases["prefix"]["meanMs"] == pytest.approx(200)
    assert cases["prefix"]["label"] == "AVG TOOL LATENCY 200ms"
    assert cases["prefixAll"]["count"] == 2
    assert cases["prefixAll"]["meanMs"] == pytest.approx(300)
    assert cases["prefixAll"]["label"] == "AVG TOOL LATENCY 300ms"


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function avgToolLatencyView" in state
    assert "export function recordedAvgToolLatencyFeed" in state
    chip = state.split("export const AVG_TOOL_LATENCY_UNAVAILABLE")[1].split("export function applyEvent")[0]
    assert 'event_type === "tool.completed"' in chip
    assert 'event_type === "tool.started"' in chip
    assert 'event_type === "tool.failed"' in chip
    assert "latency_ms" in chip
    assert "duration_ms" in chip
    assert "elapsed_ms" in chip
    assert "llm.completed" not in chip
    assert "llm.started" not in chip
    assert "llm.failed" not in chip
    assert "state.preview?null:recordedAvgToolLatencyFeed(eventLog,replayCursor,avgToolLatencyFeedLoaded)" in control
    assert "avgToolLatencyView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "avgToolLatencyFeedLoaded=options.avgToolLatencyFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "avgToolLatencyFeedLoaded=true" in control
    assert 'id="avgToolLatencyChip"' in html
    tag = html.split('id="avgToolLatencyChip"')[1].split(">")[0]
    assert "hidden" in tag
    assert "unavailable" not in tag
    assert ".hud-chip.avg-tool-latency[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.avg-tool-latency")[1].split(".hud-stats")[0]


def test_static_avg_tool_latency_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="avgToolLatencyChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function avgToolLatencyView" in state.text
