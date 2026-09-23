"""Read-only Mission Control task-failed count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "task_failed_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the task-failed chip harness")
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
        assert view["label"] == "TASK FAILS " + UNAVAILABLE
        assert view["label"] != "TASK FAILS 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "TASK FAILS 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "TASK FAILS 0"


def test_counts_task_failed_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "TASK FAILS 3"
    assert "$" not in view["label"]
    assert "token" not in view["label"].lower()
    assert cases["ignoresMissionFailed"]["count"] == 0
    assert cases["ignoresTaskCompleted"]["count"] == 0
    assert cases["ignoresTaskStarted"]["count"] == 0
    assert cases["ignoresToolFailed"]["count"] == 0
    assert cases["ignoresVerificationFailed"]["count"] == 0
    assert cases["ignoresLlmFailed"]["count"] == 0
    assert cases["ignoresAgentUpdated"]["count"] == 0
    assert cases["ignoresAgentKilled"]["count"] == 0
    assert cases["ignoresBudget"]["count"] == 0
    assert cases["oneFailureNotPayload"]["count"] == 1
    assert cases["oneFailureNotPayload"]["label"] == "TASK FAILS 1"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    unreadable = cases["unreadableType"]
    assert unreadable["known"] is False
    assert unreadable["count"] is None
    assert unreadable["label"] == "TASK FAILS " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_failures(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefix"]["count"] == 1
    assert cases["prefixOne"]["count"] == 2
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function taskFailedCountView" in state
    assert "export function recordedTaskFailedCountFeed" in state
    assert 'const TASK_FAILED_COUNT_EVENT = "task.failed"' in state
    view_body = state.split("export function taskFailedCountView")[1].split("export function applyEvent")[0]
    assert "TASK_FAILED_COUNT_EVENT" in view_body
    assert "mission.failed" not in view_body
    assert "task.completed" not in view_body
    assert "task.started" not in view_body
    assert "tool.failed" not in view_body
    assert "verification.failed" not in view_body
    assert "llm.failed" not in view_body
    assert "agent.updated" not in view_body
    assert "agent.killed" not in view_body
    assert "budget.updated" not in view_body
    assert "token_spent" not in view_body
    assert "payload.failed" not in view_body
    assert "state.preview?null:recordedTaskFailedCountFeed(eventLog,replayCursor,taskFailedFeedLoaded)" in control
    assert "taskFailedCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "taskFailedFeedLoaded=options.taskFailedFeedLoaded===true" in control
    assert 'taskFailChip.textContent=taskFailView.hidden?"":taskFailView.label' in control
    assert "if(Array.isArray(events))" in control
    assert "taskFailedFeedLoaded=true" in control
    assert 'id="taskFailedCountChip"' in html
    chip = html.split('id="taskFailedCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    css_rule = css.split(".hud-chip.task-failed")[1].split(".hud-stats")[0]
    assert '.hud-chip.task-failed[data-known="false"]' in css
    assert "animation" not in css_rule


def test_static_task_failed_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="taskFailedCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function taskFailedCountView" in state.text
