"""Read-only Mission Control approval-question count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "approval_question_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the approval-question count chip harness")
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
        assert view["label"] == "APPROVAL QUESTIONS " + UNAVAILABLE
        assert view["label"] != "APPROVAL QUESTIONS 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "APPROVAL QUESTIONS 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "APPROVAL QUESTIONS 0"
    plain = cases["plainQuestions"]
    assert plain["count"] == 0
    assert plain["label"] == "APPROVAL QUESTIONS 0"
    assert cases["missingKind"]["count"] == 0
    assert cases["nullPayload"]["count"] == 0
    assert cases["caseMismatch"]["count"] == 0


def test_counts_approval_kind_mission_question_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 2
    assert view["label"] == "APPROVAL QUESTIONS 2"
    assert "$" not in view["label"]
    assert "spend" not in view["label"].lower()
    assert "approve the next step" not in view["label"].lower()
    assert cases["ignoresAnswered"]["count"] == 0
    assert cases["ignoresConsumed"]["count"] == 0
    assert cases["ignoresWaiting"]["count"] == 0
    assert cases["ignoresPaused"]["count"] == 0
    assert cases["ignoresUnrelated"]["count"] == 0
    assert cases["oneApprovalNotText"]["count"] == 1
    assert cases["oneApprovalNotText"]["label"] == "APPROVAL QUESTIONS 1"
    assert "budget" not in cases["oneApprovalNotText"]["label"].lower()
    assert cases["otherKind"]["count"] == 1
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    for key in ("unreadableType", "unreadableKind", "unreadablePayload"):
        unreadable = cases[key]
        assert unreadable["known"] is False
        assert unreadable["count"] is None
        assert unreadable["label"] == "APPROVAL QUESTIONS " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_approval_questions(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefix"]["count"] == 1
    assert cases["prefixTwo"]["count"] == 2
    assert cases["prefixAll"]["count"] == 2


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function approvalQuestionCountView" in state
    assert "export function recordedApprovalQuestionFeed" in state
    assert 'const APPROVAL_QUESTION_EVENT = "mission.question"' in state
    assert 'const APPROVAL_QUESTION_KIND = "approval"' in state
    view_body = state.split("export function approvalQuestionCountView")[1].split("export function applyEvent")[0]
    assert "APPROVAL_QUESTION_EVENT" in view_body
    assert "APPROVAL_QUESTION_KIND" in view_body
    assert "user.answered" not in view_body
    assert "user.answer_consumed" not in view_body
    assert "mission.waiting" not in view_body
    assert "pending_question" not in view_body
    assert "token_spent" not in view_body
    assert "payload.question" not in view_body
    assert "state.preview?null:recordedApprovalQuestionFeed(eventLog,replayCursor,approvalQuestionFeedLoaded)" in control
    assert "approvalQuestionCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "approvalQuestionFeedLoaded=options.approvalQuestionFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "approvalQuestionFeedLoaded=true" in control
    assert 'id="approvalQuestionCountChip"' in html
    chip = html.split('id="approvalQuestionCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    assert ".hud-chip.approval-question-count[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.approval-question-count")[1].split(".hud-stats")[0]


def test_static_approval_question_count_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="approvalQuestionCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function approvalQuestionCountView" in state.text
