"""Read-only Mission Control controller-decision count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "controller_decision_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the controller-decision count chip harness")
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
        assert view["label"] == "CONTROLLER DECISIONS " + UNAVAILABLE
        assert view["label"] != "CONTROLLER DECISIONS 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "CONTROLLER DECISIONS 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "CONTROLLER DECISIONS 0"


def test_counts_controller_decision_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "CONTROLLER DECISIONS 3"
    assert "$" not in view["label"]
    assert "token" not in view["label"].lower()
    assert cases["ignoresProposal"]["count"] == 0
    assert cases["ignoresJudge"]["count"] == 0
    assert cases["ignoresOrg"]["count"] == 0
    assert cases["ignoresMessage"]["count"] == 0
    assert cases["ignoresLlmCompleted"]["count"] == 0
    assert cases["ignoresMissionCompleted"]["count"] == 0
    assert cases["ignoresFallback"]["count"] == 0
    assert cases["countsDecisionWithoutAction"]["count"] == 1
    assert cases["oneDecisionNotPayload"]["count"] == 1
    assert cases["oneDecisionNotPayload"]["label"] == "CONTROLLER DECISIONS 1"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    unreadable = cases["unreadableType"]
    assert unreadable["known"] is False
    assert unreadable["count"] is None
    assert unreadable["label"] == "CONTROLLER DECISIONS " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_decisions(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefix"]["count"] == 1
    assert cases["prefixOne"]["count"] == 2
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function controllerDecisionCountView" in state
    assert "export function recordedControllerDecisionFeed" in state
    assert 'const CONTROLLER_DECISION_EVENT = "controller.decision"' in state
    view_body = state.split("export function controllerDecisionCountView")[1].split("export function applyEvent")[0]
    assert "CONTROLLER_DECISION_EVENT" in view_body
    assert "planner.proposal" not in view_body
    assert "judge.decision" not in view_body
    assert "org.changed" not in view_body
    assert "agent.message" not in view_body
    assert "llm.completed" not in view_body
    assert "mission.completed" not in view_body
    assert "token_spent" not in view_body
    assert "payload.decisions" not in view_body
    assert "state.preview?null:recordedControllerDecisionFeed(eventLog,replayCursor,controllerDecisionFeedLoaded)" in control
    assert "controllerDecisionCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "controllerDecisionFeedLoaded=options.controllerDecisionFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "controllerDecisionFeedLoaded=true" in control
    assert 'id="controllerDecisionCountChip"' in html
    chip = html.split('id="controllerDecisionCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    css_rule = css.split(".hud-chip.controller-decision")[1].split(".hud-stats")[0]
    assert '.hud-chip.controller-decision[data-known="false"]' in css
    assert "animation" not in css_rule


def test_static_controller_decision_count_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="controllerDecisionCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function controllerDecisionCountView" in state.text
