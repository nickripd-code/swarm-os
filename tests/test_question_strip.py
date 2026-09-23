"""Mission Control pending-question strip: recorded prompts only, fail-closed empty."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "question_strip_cases.mjs"
GOAL = "DO_NOT_USE_GOAL_AS_PROMPT"
REASON = "DO_NOT_USE_REASON_AS_PROMPT"
ANSWER = "DO_NOT_SHOW_THIS_ANSWER"
MESSAGE = "DO_NOT_USE_AGENT_MESSAGE_AS_PROMPT"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the question strip harness")
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
    assert view == {"pending": False, "questionId": "", "summary": ""}
    blob = json.dumps(view)
    assert GOAL not in blob
    assert REASON not in blob
    assert ANSWER not in blob
    assert MESSAGE not in blob


def test_idle_loaded_and_task_wait_are_empty(cases):
    _assert_empty(cases["idle"])
    _assert_empty(cases["staleRunning"])
    _assert_empty(cases["waitingWithoutQuestion"])
    _assert_empty(cases["taskWait"])
    _assert_empty(cases["idOnly"])
    _assert_empty(cases["blankPrompt"])
    _assert_empty(cases["badId"])
    _assert_empty(cases["preview"])
    _assert_empty(cases["paused"])
    _assert_empty(cases["stopped"])
    _assert_empty(cases["answered"])
    _assert_empty(cases["replayBefore"])
    _assert_empty(cases["replayAfter"])
    _assert_empty(cases["staleThenTaskWait"])
    _assert_empty(cases["clearedByTaskWait"])
    _assert_empty(cases["agentMessage"])


def test_loaded_waiting_mission_shows_recorded_question_only(cases):
    view = cases["loaded"]
    assert view == {"pending": True, "questionId": "q-loaded", "summary": "Which name?"}
    assert REASON not in json.dumps(view)
    assert ANSWER not in json.dumps(view)
    assert GOAL not in json.dumps(view)


def test_question_event_and_human_waiting_payload_are_read_only(cases):
    assert cases["question"] == {
        "pending": True,
        "questionId": "q1",
        "summary": "Need a domain?",
    }
    assert cases["questionThenHumanWait"] == cases["question"] | {"questionId": "q-both"}
    assert cases["waitingOnly"] == {
        "pending": True,
        "questionId": "q-wait",
        "summary": "Approve the finish?",
    }
    blob = json.dumps({"question": cases["question"], "waiting": cases["waitingOnly"]})
    assert REASON not in blob
    assert ANSWER not in blob
    assert "finish" not in blob


def test_later_question_replaces_the_earlier_prompt(cases):
    view = cases["replaced"]
    assert view["questionId"] == "q-new"
    assert view["summary"] == "Second prompt?"
    assert "First prompt" not in view["summary"]


def test_summary_is_capped_and_single_line(cases):
    view = cases["longSummary"]
    assert view["pending"] is True
    assert view["questionId"] == "q-long"
    assert len(view["summary"]) == cases["cap"]
    assert view["summary"].endswith("…")
    assert "\n" not in view["summary"]
    assert REASON not in view["summary"]


def test_replay_cursor_shows_only_the_open_question(cases):
    assert cases["replayOpen"] == {
        "pending": True,
        "questionId": "q-replay",
        "summary": "Before the answer?",
    }
    assert ANSWER not in json.dumps(cases["replayOpen"])


def test_duplicate_event_keeps_the_first_prompt(cases):
    assert cases["duplicate"]["summary"] == "Kept?"
    assert "Replaced" not in cases["duplicate"]["summary"]


def test_strip_is_read_only_and_hidden_when_empty():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    source = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    opening = html.split("<aside", 1)[1]
    opening = "<aside" + opening.split(">", 1)[0]
    assert 'id="questionStrip"' in opening
    assert "hidden" in opening
    strip = html.split('id="questionStrip"', 1)[1].split("</aside>", 1)[0]
    assert "<button" not in strip
    assert "<form" not in strip
    assert "<textarea" not in strip
    assert "questionStripId" in html
    assert "questionStripSummary" in html
    assert "pendingQuestionView" in control
    assert "questionStripId" in control
    render = control.split("pendingQuestionView(state)")[1].split("if($(\"hudElapsed\"))")[0]
    assert "innerHTML" not in render
    assert "fetch(" not in render
    assert "/answers/" not in render
    view_fn = source.split("export function pendingQuestionView")[1].split("export function applyEvent")[0]
    assert "answer" not in view_fn
    assert "goal" not in view_fn
    assert ".question-strip{" in css
    block = css.split(".question-strip{")[1].split(".telemetry-drawer")[0]
    assert "animation" not in block
    assert "@keyframes" not in block


def test_static_question_strip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="questionStrip"' in page.text
        opening = "<aside" + page.text.split("<aside", 1)[1].split(">", 1)[0]
        assert 'id="questionStrip"' in opening
        assert "hidden" in opening
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function pendingQuestionView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".question-strip" in css.text
