"""Read-only Mission Control average verification-latency chip. Never invents a duration."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "avg_verification_latency_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the average verification-latency harness")
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
        assert view["label"] == "AVG VERIFICATION LATENCY " + UNAVAILABLE
        assert view["label"] != "AVG VERIFICATION LATENCY 0ms"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_loaded_feed_with_no_completed_verification_stays_hidden(cases):
    for key in ("empty", "startedOnly", "evidenceOnly", "beforeAny", "prefixFirst"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] == 0
        assert view["meanMs"] is None
        assert view["label"] == ""
    assert cases["explicitEmptyFeed"] == []


def test_mean_includes_passed_and_failed_not_the_newest(cases):
    counted = cases["counted"]
    assert counted["known"] is True
    assert counted["count"] == 2
    assert counted["meanMs"] == pytest.approx(300)
    assert counted["label"] == "AVG VERIFICATION LATENCY 300ms"
    newest = cases["meanNotNewest"]
    assert newest["count"] == 2
    assert newest["meanMs"] == pytest.approx(300)
    assert newest["label"] == "AVG VERIFICATION LATENCY 300ms"
    assert newest["label"] != "AVG VERIFICATION LATENCY 500ms"
    spans = cases["spans"]
    assert spans["count"] == 2
    assert spans["meanMs"] == pytest.approx(300)
    assert spans["label"] == "AVG VERIFICATION LATENCY 300ms"
    assert cases["explicitBeatsStamps"]["meanMs"] == pytest.approx(40)
    assert cases["explicitBeatsStamps"]["label"] == "AVG VERIFICATION LATENCY 40ms"
    paired = cases["pairedByActor"]
    assert paired["count"] == 2
    assert paired["meanMs"] == pytest.approx(150)
    assert paired["label"] == "AVG VERIFICATION LATENCY 150ms"
    assert cases["includesZero"]["count"] == 2
    assert cases["includesZero"]["meanMs"] == pytest.approx(50)
    assert cases["includesZero"]["label"] == "AVG VERIFICATION LATENCY 50ms"
    assert cases["ignoresOthers"]["count"] == 1
    assert cases["ignoresOthers"]["meanMs"] == pytest.approx(80)
    assert cases["ignoresOthers"]["label"] == "AVG VERIFICATION LATENCY 80ms"
    assert cases["evidenceDoesNotConsume"]["count"] == 1
    assert cases["evidenceDoesNotConsume"]["meanMs"] == pytest.approx(200)
    assert cases["evidenceDoesNotConsume"]["label"] == "AVG VERIFICATION LATENCY 200ms"
    assert cases["failedOnly"]["known"] is True
    assert cases["failedOnly"]["count"] == 1
    assert cases["failedOnly"]["meanMs"] == pytest.approx(250)
    assert cases["failedOnly"]["label"] == "AVG VERIFICATION LATENCY 250ms"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["skipsHoles"]["label"] == "AVG VERIFICATION LATENCY 40ms"
    assert cases["oneSecond"]["meanMs"] == pytest.approx(1500)
    assert cases["oneSecond"]["label"] == "AVG VERIFICATION LATENCY 1s"
    assert cases["minutes"]["label"] == "AVG VERIFICATION LATENCY 1m 30s"
    assert cases["hours"]["label"] == "AVG VERIFICATION LATENCY 1h 2m"


def test_honest_zero_is_shown_only_when_the_mean_is_zero(cases):
    assert cases["zero"]["known"] is True
    assert cases["zero"]["count"] == 1
    assert cases["zero"]["meanMs"] == 0
    assert cases["zero"]["label"] == "AVG VERIFICATION LATENCY 0ms"
    assert cases["zeroSpan"]["known"] is True
    assert cases["zeroSpan"]["meanMs"] == 0
    assert cases["zeroSpan"]["label"] == "AVG VERIFICATION LATENCY 0ms"


def test_unreadable_duration_stays_unavailable(cases):
    for key in (
        "blankLatency", "negativeLatency", "stringLatency", "nullLatency",
        "missingStamps", "negativeSpan", "orphanOutcome", "partialUnreadable",
        "actorMismatch", "subMillisecond",
    ):
        view = cases[key]
        assert view["hidden"] is False, key
        assert view["known"] is False, key
        assert view["meanMs"] is None, key
        assert view["count"] >= 1, key
        assert view["label"] == "AVG VERIFICATION LATENCY " + UNAVAILABLE, key
        assert view["label"] != "AVG VERIFICATION LATENCY 0ms", key
    assert cases["partialUnreadable"]["count"] == 2
    assert cases["orphanOutcome"]["count"] == 2


def test_replay_prefix_uses_only_the_visible_completed_verifications(cases):
    assert cases["prefix"]["count"] == 1
    assert cases["prefix"]["meanMs"] == pytest.approx(200)
    assert cases["prefix"]["label"] == "AVG VERIFICATION LATENCY 200ms"
    assert cases["prefixAll"]["count"] == 2
    assert cases["prefixAll"]["meanMs"] == pytest.approx(300)
    assert cases["prefixAll"]["label"] == "AVG VERIFICATION LATENCY 300ms"


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function avgVerificationLatencyView" in state
    assert "export function recordedAvgVerificationLatencyFeed" in state
    chip = state.split("export const AVG_VERIFICATION_LATENCY_UNAVAILABLE")[1].split("export function applyEvent")[0]
    assert 'event_type === "verification.passed"' in chip
    assert 'event_type === "verification.failed"' in chip
    assert 'event_type === "verification.started"' in chip
    assert "latency_ms" in chip
    assert "duration_ms" in chip
    assert "elapsed_ms" in chip
    assert "verification.evidence" not in chip
    assert "llm.completed" not in chip
    assert "llm.started" not in chip
    assert "tool.completed" not in chip
    assert "state.preview?null:recordedAvgVerificationLatencyFeed(eventLog,replayCursor,avgVerificationLatencyFeedLoaded)" in control
    assert "avgVerificationLatencyView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "avgVerificationLatencyFeedLoaded=options.avgVerificationLatencyFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "avgVerificationLatencyFeedLoaded=true" in control
    assert 'id="avgVerificationLatencyChip"' in html
    tag = html.split('id="avgVerificationLatencyChip"')[1].split(">")[0]
    assert "hidden" in tag
    assert "unavailable" not in tag
    assert ".hud-chip.avg-verification-latency[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.avg-verification-latency")[1].split(".hud-stats")[0]


def test_static_avg_verification_latency_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="avgVerificationLatencyChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function avgVerificationLatencyView" in state.text
