"""Read-only Mission Control agent-spawned count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "agent_spawned_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the agent-spawned chip harness")
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
        assert view["label"] == "SPAWNED " + UNAVAILABLE
        assert view["label"] != "SPAWNED 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "SPAWNED 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "SPAWNED 0"


def test_counts_agent_spawned_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "SPAWNED 3"
    assert "$" not in view["label"]
    assert "token" not in view["label"].lower()
    assert cases["ignoresUpdated"]["count"] == 0
    assert cases["ignoresKilled"]["count"] == 0
    assert cases["ignoresRetired"]["count"] == 0
    assert cases["ignoresReparented"]["count"] == 0
    assert cases["ignoresMessage"]["count"] == 0
    assert cases["ignoresTaskStarted"]["count"] == 0
    assert cases["ignoresMissionStarted"]["count"] == 0
    assert cases["ignoresBudget"]["count"] == 0
    assert cases["oneSpawnNotPayload"]["count"] == 1
    assert cases["oneSpawnNotPayload"]["label"] == "SPAWNED 1"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    unreadable = cases["unreadableType"]
    assert unreadable["known"] is False
    assert unreadable["count"] is None
    assert unreadable["label"] == "SPAWNED " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_spawns(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefix"]["count"] == 1
    assert cases["prefixOne"]["count"] == 2
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function agentSpawnedCountView" in state
    assert "export function recordedAgentSpawnedCountFeed" in state
    assert 'const AGENT_SPAWNED_COUNT_EVENT = "agent.spawned"' in state
    view_body = state.split("export function agentSpawnedCountView")[1].split("export function applyEvent")[0]
    assert "AGENT_SPAWNED_COUNT_EVENT" in view_body
    assert "agent.updated" not in view_body
    assert "agent.killed" not in view_body
    assert "agent.retired" not in view_body
    assert "agent.reparented" not in view_body
    assert "agent.message" not in view_body
    assert "task.started" not in view_body
    assert "mission.started" not in view_body
    assert "token_spent" not in view_body
    assert "payload.spawned" not in view_body
    assert "state.preview?null:recordedAgentSpawnedCountFeed(eventLog,replayCursor,agentSpawnedFeedLoaded)" in control
    assert "agentSpawnedCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "agentSpawnedFeedLoaded=options.agentSpawnedFeedLoaded===true" in control
    assert "spawnedChip.textContent=spawnedView.hidden?\"\":spawnedView.label" in control
    assert "if(Array.isArray(events))" in control
    assert "agentSpawnedFeedLoaded=true" in control
    assert 'id="agentSpawnedCountChip"' in html
    chip = html.split('id="agentSpawnedCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    css_rule = css.split(".hud-chip.agent-spawned")[1].split(".hud-stats")[0]
    assert '.hud-chip.agent-spawned[data-known="false"]' in css
    assert "animation" not in css_rule


def test_static_agent_spawned_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="agentSpawnedCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function agentSpawnedCountView" in state.text
