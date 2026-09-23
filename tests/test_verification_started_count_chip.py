"""Read-only Mission Control verification-started count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "verification_started_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the verification-started chip harness")
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
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == "VERIFICATION STARTED " + UNAVAILABLE
        assert view["label"] != "VERIFICATION STARTED 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "VERIFICATION STARTED 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "VERIFICATION STARTED 0"


def test_counts_verification_started_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "VERIFICATION STARTED 3"
    assert "$" not in view["label"]
    assert "token" not in view["label"].lower()
    assert cases["ignoresPassed"]["count"] == 0
    assert cases["ignoresFailed"]["count"] == 0
    assert cases["ignoresEvidenceStarted"]["count"] == 0
    assert cases["ignoresEvidencePassed"]["count"] == 0
    assert cases["ignoresEvidenceFailed"]["count"] == 0
    assert cases["ignoresTool"]["count"] == 0
    assert cases["ignoresLlm"]["count"] == 0
    assert cases["ignoresMissionCompleted"]["count"] == 0
    assert cases["oneStartNotPayload"]["count"] == 1
    assert cases["oneStartNotPayload"]["label"] == "VERIFICATION STARTED 1"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    unreadable = cases["unreadableType"]
    assert unreadable["known"] is False
    assert unreadable["count"] is None
    assert unreadable["label"] == "VERIFICATION STARTED " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_verification_starts(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefix"]["count"] == 1
    assert cases["prefixOne"]["count"] == 2
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function verificationStartedCountView" in state
    assert "export function recordedVerificationStartedFeed" in state
    assert 'const VERIFICATION_STARTED_EVENT = "verification.started"' in state
    view_body = state.split("export function verificationStartedCountView")[1].split("export function applyEvent")[0]
    assert "VERIFICATION_STARTED_EVENT" in view_body
    assert "verification.passed" not in view_body
    assert "verification.failed" not in view_body
    assert "verification.evidence" not in view_body
    assert "tool.started" not in view_body
    assert "llm.started" not in view_body
    assert "token_spent" not in view_body
    assert "payload.starts" not in view_body
    assert "state.preview?null:recordedVerificationStartedFeed(eventLog,replayCursor,verificationStartedFeedLoaded)" in control
    assert "verificationStartedCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "verificationStartedFeedLoaded=options.verificationStartedFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "verificationStartedFeedLoaded=true" in control
    assert 'id="verificationStartedCountChip"' in html
    chip = html.split('id="verificationStartedCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    assert '.hud-chip.verification-started[data-known="false"]' in css
    assert "animation" not in css.split(".hud-chip.verification-started")[1].split(".hud-stats")[0]


def test_static_verification_started_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="verificationStartedCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function verificationStartedCountView" in state.text
