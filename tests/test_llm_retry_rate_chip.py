"""Read-only Mission Control LLM retry-rate chip. Never invents a ratio."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "llm_retry_rate_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the LLM retry-rate harness")
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
        assert view["retries"] is None
        assert view["completed"] is None
        assert view["failed"] is None
        assert view["attempts"] is None
        assert view["rate"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["rate"] is None
        assert view["label"] == "LLM RETRY RATE " + UNAVAILABLE
        assert view["label"] != "LLM RETRY RATE 0%"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_loaded_feed_with_no_completed_attempts_stays_hidden(cases):
    for key in ("empty", "startedOnly", "retriesOnly", "beforeAny"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["attempts"] == 0
        assert view["rate"] is None
        assert view["label"] == ""
    assert cases["retriesOnly"]["retries"] == 2
    assert cases["explicitEmptyFeed"] == []


def test_ratio_is_llm_retry_over_completed_attempts(cases):
    counted = cases["counted"]
    assert counted["known"] is True
    assert counted["retries"] == 2
    assert counted["completed"] == 2
    assert counted["failed"] == 2
    assert counted["attempts"] == 4
    assert counted["rate"] == pytest.approx(2 / 4)
    assert counted["label"] == "LLM RETRY RATE 50%"
    assert cases["zero"]["retries"] == 0
    assert cases["zero"]["attempts"] == 2
    assert cases["zero"]["rate"] == 0
    assert cases["zero"]["label"] == "LLM RETRY RATE 0%"
    assert cases["half"]["retries"] == 1
    assert cases["half"]["attempts"] == 2
    assert cases["half"]["rate"] == 0.5
    assert cases["half"]["label"] == "LLM RETRY RATE 50%"
    over = cases["over"]
    assert over["retries"] == 2
    assert over["completed"] == 1
    assert over["failed"] == 0
    assert over["attempts"] == 1
    assert over["rate"] == 2
    assert over["label"] == "LLM RETRY RATE 200%"
    assert cases["third"]["retries"] == 1
    assert cases["third"]["attempts"] == 3
    assert cases["third"]["label"] == "LLM RETRY RATE 33.33%"
    ignored = cases["failoverIgnored"]
    assert ignored["retries"] == 0
    assert ignored["completed"] == 1
    assert ignored["failed"] == 0
    assert ignored["attempts"] == 1
    assert ignored["label"] == "LLM RETRY RATE 0%"
    assert cases["skipsHoles"]["retries"] == 1
    assert cases["skipsHoles"]["failed"] == 1
    assert cases["skipsHoles"]["label"] == "LLM RETRY RATE 100%"


def test_unreadable_tiny_rate_stays_unavailable(cases):
    tiny = cases["tiny"]
    assert tiny["known"] is False
    assert tiny["retries"] == 1
    assert tiny["completed"] == 1000000
    assert tiny["attempts"] == 1000001
    assert tiny["rate"] is None
    assert tiny["label"] == "LLM RETRY RATE " + UNAVAILABLE
    assert tiny["label"] != "LLM RETRY RATE 0%"


def test_replay_prefix_uses_only_the_visible_llm_outcomes(cases):
    assert cases["prefixFirst"]["hidden"] is True
    assert cases["prefixFirst"]["retries"] == 1
    assert cases["prefixFirst"]["attempts"] == 0
    assert cases["prefixFirst"]["label"] == ""
    assert cases["prefix"]["retries"] == 1
    assert cases["prefix"]["failed"] == 1
    assert cases["prefix"]["completed"] == 0
    assert cases["prefix"]["label"] == "LLM RETRY RATE 100%"
    assert cases["prefixAll"]["retries"] == 2
    assert cases["prefixAll"]["completed"] == 2
    assert cases["prefixAll"]["failed"] == 2
    assert cases["prefixAll"]["label"] == "LLM RETRY RATE 50%"


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function llmRetryRateView" in state
    assert "export function recordedLlmRetryRateFeed" in state
    assert 'event_type === "llm.retry"' in state
    assert 'event_type === "llm.completed"' in state
    assert 'event_type === "llm.failed"' in state
    view_body = state.split("export function llmRetryRateView")[1].split("export function applyEvent")[0]
    assert "llm.started" not in view_body
    assert "llm.failover" not in view_body
    assert "payload" not in view_body
    assert "tool.failed" not in view_body
    assert "tool.completed" not in view_body
    assert "state.preview?null:recordedLlmRetryRateFeed(eventLog,replayCursor,llmRetryRateFeedLoaded)" in control
    assert "llmRetryRateView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "llmRetryRateFeedLoaded=options.llmRetryRateFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "llmRetryRateFeedLoaded=true" in control
    assert 'id="llmRetryRateChip"' in html
    chip = html.split('id="llmRetryRateChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert ".hud-chip.llm-retry-rate[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.llm-retry-rate")[1].split(".hud-stats")[0]


def test_static_llm_retry_rate_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="llmRetryRateChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function llmRetryRateView" in state.text
