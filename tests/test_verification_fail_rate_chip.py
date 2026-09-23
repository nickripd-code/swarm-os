"""Read-only Mission Control verification fail-rate chip. Never invents a ratio."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "verification_fail_rate_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the verification fail-rate harness")
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
        assert view["passed"] is None
        assert view["attempts"] is None
        assert view["rate"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["rate"] is None
        assert view["label"] == "VERIFICATION FAIL RATE " + UNAVAILABLE
        assert view["label"] != "VERIFICATION FAIL RATE 0%"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_loaded_feed_with_no_completed_attempts_stays_hidden(cases):
    for key in ("empty", "startedOnly", "beforeAny"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["fails"] == 0
        assert view["passed"] == 0
        assert view["attempts"] == 0
        assert view["rate"] is None
        assert view["label"] == ""
    assert cases["explicitEmptyFeed"] == []


def test_ratio_is_verification_failed_over_completed_attempts(cases):
    counted = cases["counted"]
    assert counted["known"] is True
    assert counted["fails"] == 2
    assert counted["passed"] == 2
    assert counted["attempts"] == 4
    assert counted["rate"] == pytest.approx(2 / 4)
    assert counted["label"] == "VERIFICATION FAIL RATE 50%"
    assert cases["passesOnly"]["fails"] == 0
    assert cases["passesOnly"]["passed"] == 2
    assert cases["passesOnly"]["rate"] == 0
    assert cases["passesOnly"]["label"] == "VERIFICATION FAIL RATE 0%"
    assert cases["half"]["rate"] == 0.5
    assert cases["half"]["label"] == "VERIFICATION FAIL RATE 50%"
    assert cases["allFailed"]["rate"] == 1
    assert cases["allFailed"]["label"] == "VERIFICATION FAIL RATE 100%"
    assert cases["third"]["label"] == "VERIFICATION FAIL RATE 33.33%"
    evidence = cases["evidenceIgnored"]
    assert evidence["fails"] == 0
    assert evidence["passed"] == 1
    assert evidence["attempts"] == 1
    assert evidence["label"] == "VERIFICATION FAIL RATE 0%"
    assert cases["skipsHoles"]["fails"] == 1
    assert cases["skipsHoles"]["passed"] == 1
    assert cases["skipsHoles"]["label"] == "VERIFICATION FAIL RATE 50%"


def test_unreadable_tiny_rate_stays_unavailable(cases):
    tiny = cases["tiny"]
    assert tiny["known"] is False
    assert tiny["fails"] == 1
    assert tiny["passed"] == 100000
    assert tiny["attempts"] == 100001
    assert tiny["rate"] is None
    assert tiny["label"] == "VERIFICATION FAIL RATE " + UNAVAILABLE
    assert tiny["label"] != "VERIFICATION FAIL RATE 0%"


def test_replay_prefix_uses_only_the_visible_verification_outcomes(cases):
    assert cases["prefixFirst"]["hidden"] is True
    assert cases["prefixFirst"]["attempts"] == 0
    assert cases["prefixFirst"]["label"] == ""
    assert cases["prefix"]["fails"] == 1
    assert cases["prefix"]["passed"] == 1
    assert cases["prefix"]["label"] == "VERIFICATION FAIL RATE 50%"
    assert cases["prefixAll"]["fails"] == 2
    assert cases["prefixAll"]["passed"] == 2
    assert cases["prefixAll"]["label"] == "VERIFICATION FAIL RATE 50%"


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function verificationFailRateView" in state
    assert "export function recordedVerificationFailRateFeed" in state
    assert 'event_type === "verification.failed"' in state
    assert 'event_type === "verification.passed"' in state
    view_body = state.split("export function verificationFailRateView")[1].split("export function applyEvent")[0]
    assert "verification.started" not in view_body
    assert "verification.evidence" not in view_body
    assert "payload" not in view_body
    assert "llm.failed" not in view_body
    assert "llm.completed" not in view_body
    assert "tool.failed" not in view_body
    assert "tool.completed" not in view_body
    assert "state.preview?null:recordedVerificationFailRateFeed(eventLog,replayCursor,verificationFailRateFeedLoaded)" in control
    assert "verificationFailRateView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "verificationFailRateFeedLoaded=options.verificationFailRateFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "verificationFailRateFeedLoaded=true" in control
    assert 'id="verificationFailRateChip"' in html
    chip = html.split('id="verificationFailRateChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert ".hud-chip.verification-fail-rate[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.verification-fail-rate")[1].split(".hud-stats")[0]


def test_static_verification_fail_rate_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="verificationFailRateChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function verificationFailRateView" in state.text
