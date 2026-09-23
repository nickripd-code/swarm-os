"""Read-only Mission Control failure/park panel. Never invents a cause."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "failure_reason_cases.mjs"
EMPTY = "No recorded failure, park, or blocked approval."


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the failure/park panel harness")
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


def test_empty_constant_matches_the_panel(cases):
    assert cases["EMPTY"] == EMPTY
    assert cases["noMission"]["recorded"] is False
    assert cases["noMission"]["failure_class"] is None
    assert cases["noMission"]["reason"] is None
    assert cases["noMission"]["empty"] == EMPTY


def test_preview_does_not_surface_a_synthetic_failure(cases):
    view = cases["preview"]
    assert view["recorded"] is False
    assert view["failure_class"] is None
    assert view["empty"] == EMPTY


def test_mission_failed_shows_recorded_class_and_error(cases):
    view = cases["failed"]
    assert view["recorded"] is True
    assert view["kind"] == "failure"
    assert view["label"] == "FAILURE"
    assert view["failure_class"] == "PROVIDER_OUTAGE"
    assert view["reason"] == "provider down"
    assert view["source"] == "mission.failed"
    assert view["empty"] is None


def test_class_without_error_is_shown_and_blank_class_is_not_invented(cases):
    only = cases["failedClassOnly"]
    assert only["failure_class"] == "TIMEOUT"
    assert only["reason"] is None
    blank = cases["failedBlank"]
    assert blank["recorded"] is False
    assert blank["failure_class"] is None
    assert blank["empty"] == EMPTY
    numeric = cases["numericClass"]
    assert numeric["recorded"] is False
    assert numeric["failure_class"] is None


def test_approval_park_uses_recorded_reason_and_action(cases):
    view = cases["approval"]
    assert view["kind"] == "approval"
    assert view["label"] == "APPROVAL"
    assert view["reason"] == "Finish requires human approval"
    assert view["approval_action"] == "finish"
    assert view["question"].startswith("Approve completing")
    assert view["failure_class"] is None
    assert view["source"] == "mission.waiting"


def test_question_park_and_inflight_wait_stay_distinct(cases):
    park = cases["parkQuestion"]
    assert park["kind"] == "park"
    assert park["label"] == "PARKED"
    assert park["reason"] == "Need a region before continuing"
    assert park["approval_action"] is None
    waiting = cases["inflightWait"]
    assert waiting["recorded"] is False
    assert waiting["reason"] is None
    assert waiting["empty"] == EMPTY


def test_blocked_reason_is_recorded_and_missing_reason_stays_empty(cases):
    blocked = cases["blocked"]
    assert blocked["kind"] == "blocked"
    assert blocked["reason"] == "No browser is configured"
    assert blocked["failure_class"] is None
    missing = cases["blockedMissing"]
    assert missing["recorded"] is False
    assert missing["reason"] is None
    assert "capability" not in (missing["empty"] or "")
    finding = cases["taskBlockedFinding"]
    assert finding["reason"] == "Needs a listed host"
    empty_task = cases["taskBlockedEmpty"]
    assert empty_task["recorded"] is False
    assert empty_task["reason"] is None


def test_later_success_or_answer_clears_an_older_cause(cases):
    assert cases["completedClears"]["recorded"] is False
    assert cases["answerClearsPark"]["recorded"] is False
    assert cases["runningClearsPark"]["reason"] is None
    assert cases["retryThenSuccess"]["failure_class"] is None
    assert cases["verificationPassedClears"]["recorded"] is False
    stopped = cases["stopped"]
    assert stopped["recorded"] is False
    assert stopped["failure_class"] is None
    assert stopped["reason"] is None


def test_open_retry_llm_failure_and_verification_keep_their_class(cases):
    retry = cases["retryOpen"]
    assert retry["label"] == "CLASS"
    assert retry["failure_class"] == "TIMEOUT"
    assert retry["source"] == "llm.retry"
    failed = cases["llmFailed"]
    assert failed["failure_class"] == "PROVIDER_OUTAGE"
    assert failed["reason"] == "connect failed"
    assert failed["label"] == "CLASS"
    verification = cases["verification"]
    assert verification["failure_class"] == "VERIFICATION_FAILURE"
    assert verification["reason"] == "tests failed"


def test_loaded_mission_fields_are_used_only_when_no_events_exist(cases):
    failed = cases["snapshotFailure"]
    assert failed["failure_class"] == "TIMEOUT"
    assert failed["reason"] == "Mission runtime limit reached"
    assert failed["source"] == "mission.result"
    blocked = cases["snapshotBlocked"]
    assert blocked["reason"] == "Required capability or information is unavailable"
    assert blocked["source"] == "mission.result"
    approval = cases["snapshotApproval"]
    assert approval["kind"] == "approval"
    assert approval["approval_action"] == "org_change"
    assert approval["source"] == "pending_question"
    assert cases["snapshotEmpty"]["recorded"] is False
    stale = cases["eventsIgnoreStaleResult"]
    assert stale["recorded"] is False
    assert stale["failure_class"] is None


def test_replay_prefix_does_not_show_a_future_failure(cases):
    before = cases["replayBefore"]
    assert before["recorded"] is False
    assert before["failure_class"] is None
    at = cases["replayAtFailure"]
    assert at["failure_class"] == "PROVIDER_OUTAGE"
    assert at["reason"] == "down"


def test_panel_markup_is_read_only_and_fail_closed():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="failurePanel"' in html
    assert 'id="failureEmpty"' in html
    assert EMPTY in html
    assert "failureReasonView" in control
    assert '$("failurePanel")' in control
    assert "export function failureReasonView" in state
    block = css.split(".failure-panel{")[1].split(".question-panel")[0]
    assert "animation" not in block
    assert "@keyframes" not in block
    render = control.split("function renderFailure()", 1)[1].split("function renderQuestion()", 1)[0]
    assert "UNKNOWN_FAILURE" not in render
    assert "Required capability" not in render
    assert "Waiting for a human" not in render
    assert "textContent" in render
    assert "fetch(" not in render
    assert "method:" not in render


def test_static_failure_panel_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="failurePanel"' in page.text
        assert EMPTY in page.text
        assert 'id="failureEmpty"' in page.text
        module = client.get("/static/state.mjs")
        assert module.status_code == 200
        assert "export function failureReasonView" in module.text
        js = client.get("/static/control.js")
        assert js.status_code == 200
        assert "renderFailure" in js.text
