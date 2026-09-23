"""Read-only Mission Control tool-call count chip. Never invents a count."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "tool_call_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the tool-call chip harness")
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


def test_chip_stays_hidden_without_a_loaded_mission(cases):
    assert cases["hidden"]["hidden"] is True
    assert cases["hidden"]["known"] is False
    assert cases["hidden"]["count"] is None
    assert cases["hidden"]["label"] == ""
    assert cases["hiddenDefault"]["hidden"] is True
    assert cases["hiddenDefault"]["count"] is None


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == "TOOLS " + UNAVAILABLE
        assert view["label"] != "TOOLS 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "TOOLS 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "TOOLS 0"


def test_counts_tool_started_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "TOOLS 3"
    assert cases["ignoresUsedField"]["count"] == 1
    assert cases["skipsHoles"]["count"] == 1


def test_replay_prefix_does_not_include_later_tool_calls(cases):
    assert cases["prefix"]["count"] == 1
    assert cases["prefixFirst"]["count"] == 1
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function toolCallCountView" in state
    assert "export function recordedToolFeed" in state
    assert 'event_type === "tool.started"' in state
    assert "payload.used" not in state.split("export function toolCallCountView")[1]
    assert "state.preview?null:recordedToolFeed(eventLog,replayCursor,toolFeedLoaded)" in control
    assert "toolCallCountView(feed,{visible:!!(state.mission||state.preview)})" in control
    assert "toolFeedLoaded=options.toolFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "toolFeedLoaded=true" in control
    assert 'id="toolCallChip"' in html
    assert "hidden" in html.split('id="toolCallChip"')[1].split(">")[0]
    assert ".hud-chip.tools[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.tools")[1].split(".hud-stats")[0]


def test_static_tool_call_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="toolCallChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function toolCallCountView" in state.text
