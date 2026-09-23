"""Read-only Mission Control chip for the newest approval-kind mission.question time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_approval_question_at_chip_cases.mjs"
UNAVAILABLE = "LAST APPROVAL QUESTION unavailable"
QUESTION = "Approve finish and spend the remaining budget?"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-approval-question chip harness")
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


def _hidden(view: dict) -> None:
    assert view["hidden"] is True
    assert view["label"] == ""
    assert view["known"] is False
    assert view["at"] is None
    assert view["title"] == ""


def _unavailable(view: dict) -> None:
    assert view["hidden"] is False
    assert view["label"] == UNAVAILABLE
    assert view["known"] is False
    assert view["at"] is None
    assert view["title"] == ""
    assert ":" not in view["label"]
    assert "just now" not in view["label"]
    assert "1970" not in view["label"]
    assert "ago" not in view["label"]
    assert QUESTION not in view["label"]


def test_chip_stays_hidden_without_a_mission_or_in_preview(cases):
    _hidden(cases["noMission"])
    _hidden(cases["preview"])


def test_missing_feed_says_last_approval_question_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE
    assert cases["notArrayLog"] is None


def test_loaded_feed_without_an_approval_question_stays_hidden(cases):
    for name in (
        "empty",
        "cursorBefore",
        "plainQuestion",
        "missingKind",
        "nullKind",
        "nullPayload",
        "waitingApproval",
        "answeredApproval",
        "consumed",
        "nonQuestion",
        "nonObject",
        "replayBefore",
    ):
        _hidden(cases[name])
    assert cases["explicitEmptyFeed"] == []
    assert "$" not in cases["nonQuestion"]["label"]
    assert "1.25" not in cases["nonQuestion"]["label"]
    assert QUESTION not in cases["plainQuestion"]["label"]
    assert "waiting" not in cases["waitingApproval"]["label"]
    assert "yes" not in cases["answeredApproval"]["label"]
    assert "consumed" not in cases["consumed"]["label"]


@pytest.mark.parametrize(
    "name",
    [
        "missingTime",
        "blankTime",
        "whitespace",
        "numericZero",
        "numericNow",
        "stringZero",
        "epoch",
        "epochFraction",
        "naive",
        "garbage",
        "impossibleDay",
        "newestInvalid",
        "badType",
        "badPayload",
        "badKind",
    ],
)
def test_an_unreadable_approval_question_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_approval_question_clock_in_utc(cases):
    view = cases["clock"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert view["title"] == "2026-09-23T12:35:04.123456Z"
    assert view["at"] == "2026-09-23T12:35:04.123456Z"
    assert "08:00:00" not in view["label"]
    assert "12:00:00" not in view["label"]
    assert QUESTION not in view["label"]
    assert QUESTION not in view["title"]
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert cases["offset"]["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert cases["offset"]["at"] == "2026-09-23T08:35:04-04:00"
    assert cases["newestByTime"]["label"] == "LAST APPROVAL QUESTION 12:50:09Z"
    assert cases["newestByTime"]["at"] == "2026-09-23T12:50:09Z"
    assert cases["plainDoesNotOverride"]["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert cases["waitingDoesNotOverride"]["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert cases["answeredDoesNotOverride"]["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert cases["consumedDoesNotOverride"]["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert cases["replayPrefix"]["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert cases["replayAtLater"]["label"] == "LAST APPROVAL QUESTION 12:36:00Z"
    spend = cases["spendIgnored"]
    assert spend["label"] == "LAST APPROVAL QUESTION 12:35:04Z"
    assert "$" not in spend["label"]
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]
    assert QUESTION not in spend["label"]


def test_shell_mounts_a_hidden_last_approval_question_at_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="lastApprovalQuestionAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert ".hud-chip.last-approval-question[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.last-approval-question")[1].split("}")[0]
    assert "export function lastApprovalQuestionAtView" in state
    assert "export function recordedApprovalQuestionAtFeed" in state
    assert 'LAST_APPROVAL_QUESTION_UNAVAILABLE = "LAST APPROVAL QUESTION unavailable"' in state
    assert 'const APPROVAL_QUESTION_AT_EVENT = "mission.question"' in state
    assert 'const APPROVAL_QUESTION_AT_KIND = "approval"' in state
    assert "user.answered" not in state[state.index("const APPROVAL_QUESTION_AT_EVENT"):state.index("const APPROVAL_QUESTION_AT_KIND")]
    assert "mission.waiting" not in state[state.index("APPROVAL_QUESTION_AT_EVENT"):state.index("function hiddenLastApprovalQuestion")]
    render = control[control.index('const approvalQuestionAtChip=$("lastApprovalQuestionAtChip")'):control.index("const running=")]
    assert "recordedApprovalQuestionAtFeed(eventLog,replayCursor,approvalQuestionAtFeedLoaded)" in render
    assert "lastApprovalQuestionAtView(feed,{visible:!!(state.mission&&!state.preview)})" in render
    assert "Date.now" not in render
    assert "just now" not in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "approvalQuestionAtFeedLoaded=options.approvalQuestionAtFeedLoaded===true" in control
    assert "approvalQuestionAtFeedLoaded=true" in control
    assert "if(Array.isArray(events))" in control


def test_static_last_approval_question_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="lastApprovalQuestionAtChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function lastApprovalQuestionAtView" in state.text
