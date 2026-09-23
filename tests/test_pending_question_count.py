"""Read-only Mission Control pending-question count. Never invents a question."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "pending_question_count_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the pending-question count harness")
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


def _unavailable(view: dict) -> None:
    assert view["hidden"] is False
    assert view["known"] is False
    assert view["count"] is None
    assert view["label"] == "QUESTIONS " + UNAVAILABLE
    assert "0" not in view["label"]
    assert "1" not in view["label"]


def test_chip_stays_hidden_without_a_mission_or_in_preview(cases):
    for key in ("hidden", "hiddenDefault", "hiddenPreview"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == ""


def test_null_and_missing_field_are_explicit_zero(cases):
    for key in ("none", "missingKey", "answersIgnored", "agentMessage", "replayBefore", "afterAnswer"):
        view = cases[key]
        assert view == {"hidden": False, "known": True, "count": 0, "label": "QUESTIONS 0"}


def test_one_readable_question_counts_as_one(cases):
    assert cases["one"] == {"hidden": False, "known": True, "count": 1, "label": "QUESTIONS 1"}
    assert cases["approval"] == cases["one"]
    assert cases["afterQuestion"]["count"] == 1
    assert cases["afterQuestion"]["known"] is True
    assert cases["mismatchKeeps"]["count"] == 1
    assert cases["replayOpen"] == {"hidden": False, "known": True, "count": 1, "label": "QUESTIONS 1"}
    assert cases["replayAnswered"]["count"] == 0


def test_unreadable_field_is_unavailable_not_zero(cases):
    for key in (
        "blank", "blankId", "missingText", "missingId", "number", "stringField",
        "boolField", "emptyObject", "array", "unreadableEvent",
    ):
        _unavailable(cases[key])
    assert cases["array"]["count"] is None


def test_chip_is_read_only_and_wired_to_pending_question():
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function pendingQuestionCountView" in state
    assert "export const QUESTIONS_UNAVAILABLE" in state
    view_fn = state.split("export function pendingQuestionCountView")[1].split("export function applyEvent")[0]
    assert "pending_question" in view_fn
    assert "answers" not in view_fn
    assert "event_type" not in view_fn
    assert "agent.message" not in view_fn
    opening = html.split('id="pendingQuestionChip"', 1)[1].split(">", 1)[0]
    assert "hidden" in opening
    assert "button" not in html.split('id="pendingQuestionChip"', 1)[1].split("</span>", 1)[0]
    assert "pendingQuestionCountView" in control
    render = control.split("pendingQuestionCountView(")[1].split("const running")[0]
    assert "hidden" in render
    assert "dataset.known" in render
    assert "fetch(" not in render
    assert "/answers/" not in render
    assert ".hud-chip.questions[data-known=\"false\"]" in css
    block = css.split(".hud-chip.questions")[1].split(".hud-stats")[0]
    assert "animation" not in block


def test_static_pending_question_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        opening = page.text.split('id="pendingQuestionChip"', 1)[1].split(">", 1)[0]
        assert "hidden" in opening
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function pendingQuestionCountView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".hud-chip.questions" in css.text
