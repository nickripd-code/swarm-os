"""Mission Control last-verification strip: recorded verdicts only, fail-closed empty."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "verification_strip_cases.mjs"
EMPTY = "No verification recorded"
ROLE_UNAVAILABLE = "role unavailable"
SUMMARY_UNAVAILABLE = "summary unavailable"
EVIDENCE = "DO_NOT_SHOW_THIS_EVIDENCE_DUMP"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the verification strip harness")
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


def _assert_empty(view: dict) -> None:
    assert view["recorded"] is False
    assert view["outcome"] is None
    assert view["outcomeLabel"] == EMPTY
    assert view["role"] == ""
    assert view["roleLabel"] == ROLE_UNAVAILABLE
    assert view["summary"] == ""
    assert view["summaryLabel"] == SUMMARY_UNAVAILABLE
    assert "PASS" not in view["outcomeLabel"]
    blob = json.dumps(view)
    assert EVIDENCE not in blob
    assert "evidence" not in view


def test_idle_and_loaded_missions_have_no_verification(cases):
    _assert_empty(cases["idle"])
    _assert_empty(cases["loaded"])
    assert cases["labels"]["NO_VERIFICATION"] == EMPTY


def test_started_and_evidence_events_are_not_a_verdict(cases):
    _assert_empty(cases["started"])
    _assert_empty(cases["evidenceOnly"])
    _assert_empty(cases["restarted"])


def test_passed_event_shows_role_and_short_summary_only(cases):
    view = cases["passed"]
    assert view["recorded"] is True
    assert view["outcome"] == "pass"
    assert view["outcomeLabel"] == "PASS"
    assert view["role"] == "mission_controller"
    assert view["roleLabel"] == "mission controller"
    assert view["summary"] == "Grounded in the worker artifact."
    assert view["summaryLabel"] == view["summary"]
    assert EVIDENCE not in json.dumps(view)
    assert "evidence" not in view


def test_later_failure_replaces_an_earlier_pass(cases):
    view = cases["replaced"]
    assert view["outcome"] == "fail"
    assert view["outcomeLabel"] == "FAIL"
    assert view["summary"] == "Objective is unmet"
    assert "First pass" not in view["summary"]


def test_inconclusive_is_not_shown_as_pass(cases):
    view = cases["inconclusive"]
    assert view["outcome"] == "inconclusive"
    assert view["outcomeLabel"] == "INCONCLUSIVE"
    assert view["summary"] == "Not enough evidence"
    assert view["outcomeLabel"] != "PASS"


def test_mismatched_verdict_fails_closed(cases):
    _assert_empty(cases["mismatchPass"])
    _assert_empty(cases["mismatchFail"])


def test_missing_or_blank_summary_stays_unavailable(cases):
    missing = cases["missingSummary"]
    assert missing["outcome"] == "fail"
    assert missing["summary"] == ""
    assert missing["summaryLabel"] == SUMMARY_UNAVAILABLE
    assert EVIDENCE not in json.dumps(missing)
    blank = cases["blankSummary"]
    assert blank["outcome"] == "pass"
    assert blank["summaryLabel"] == SUMMARY_UNAVAILABLE


def test_summary_is_capped_and_does_not_include_evidence(cases):
    view = cases["longSummary"]
    assert view["outcome"] == "pass"
    assert len(view["summary"]) == 160
    assert view["summary"].endswith("…")
    assert EVIDENCE not in view["summary"]
    assert "\n" not in view["summary"]


def test_preview_and_unknown_or_unsafe_role_fail_closed(cases):
    _assert_empty(cases["preview"])
    unknown = cases["unknownActor"]
    assert unknown["outcome"] == "pass"
    assert unknown["roleLabel"] == ROLE_UNAVAILABLE
    assert unknown["summary"] == "Recorded without a role"
    newline = cases["newlineRole"]
    assert newline["outcome"] == "fail"
    assert newline["role"] == ""
    assert newline["roleLabel"] == ROLE_UNAVAILABLE
    assert "\n" not in json.dumps(newline["roleLabel"])


def test_duplicate_event_id_does_not_replace_the_recorded_verdict(cases):
    view = cases["duplicate"]
    assert view["outcome"] == "pass"
    assert view["summary"] == "Kept"


def test_replay_projection_uses_only_events_through_the_cursor(cases):
    before = cases["replayBefore"]
    assert before["outcome"] == "fail"
    assert before["summary"] == "Too early"
    after = cases["replayAfter"]
    assert after["outcome"] == "pass"
    assert after["summary"] == "Later pass"
    assert after["roleLabel"] == "mission controller"


def test_strip_source_does_not_render_evidence_payloads():
    source = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    view_fn = source.split("export function lastVerificationView")[1].split("export function applyEvent")[0]
    assert "evidence" not in view_fn
    assert "lastVerificationView" in control
    assert "verifySummary" in control
    assert "innerHTML" not in control.split("verifySummary")[0].split("lastVerificationView")[-1]
    assert 'id="verifyStrip"' in html
    assert EMPTY in html
    assert ROLE_UNAVAILABLE in html
    assert SUMMARY_UNAVAILABLE in html
    assert ".verify-strip{" in css
    block = css.split(".verify-strip{")[1].split(".telemetry-drawer")[0]
    assert "animation" not in block
    assert "@keyframes" not in block


def test_static_verification_strip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="verifyStrip"' in page.text
        assert EMPTY in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function lastVerificationView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".verify-strip" in css.text
