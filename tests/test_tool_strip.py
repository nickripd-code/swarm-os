"""Mission Control tool-call strip: recorded events only, never invented calls."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "tool_strip_cases.mjs"
EMPTY = "No recorded tool calls."
PREVIEW = "Preview runs no tools."


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS tool-strip harness")
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


def test_loaded_mission_with_no_tool_events_is_empty(cases):
    view = cases["empty"]
    assert view["hidden"] is False
    assert view["empty"] is True
    assert view["calls"] == []
    assert view["note"] == EMPTY


def test_standby_hides_the_strip(cases):
    view = cases["standby"]
    assert view["hidden"] is True
    assert view["calls"] == []
    assert view["note"] == EMPTY


def test_preview_never_invents_tool_calls(cases):
    view = cases["preview"]
    assert view["hidden"] is False
    assert view["empty"] is True
    assert view["calls"] == []
    assert view["note"] == PREVIEW
    assert cases["constants"]["preview"] == PREVIEW


def test_strip_lists_name_status_and_agent_without_payloads(cases):
    view = cases["full"]
    assert view["empty"] is False
    assert view["note"] == "Recorded tool events only"
    assert view["calls"] == [
        {"id": "tool-fail", "tool": "echo", "status": "failed", "agent": "unattributed"},
        {"id": "tool-done", "tool": "clock.utc", "status": "completed", "agent": "mission_controller"},
        {"id": "tool-start", "tool": "clock.utc", "status": "started", "agent": "mission_controller"},
    ]
    blob = json.dumps(view)
    assert "secret" not in blob
    assert "boom" not in blob
    assert "arguments" not in blob
    assert "output" not in blob
    assert "failure_class" not in blob
    assert "do not show" not in blob
    assert "invented" not in blob


def test_replay_cursor_hides_later_tool_calls(cases):
    view = cases["atStart"]
    assert view["calls"] == [
        {"id": "tool-start", "tool": "clock.utc", "status": "started", "agent": "mission_controller"},
    ]


def test_strip_is_bounded_and_ignores_nameless_events(cases):
    view = cases["limit"]
    assert len(view["calls"]) == 3
    assert all(set(call) == {"id", "tool", "status", "agent"} for call in view["calls"])
    assert all(call["tool"] == "echo" for call in view["calls"])


def test_markup_does_not_dump_tool_payloads():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="toolStrip"' in html
    assert 'id="toolCalls"' in html
    assert EMPTY in html
    assert "export function toolCallStrip" in state
    assert "toolCallStrip" in control
    start = control.index("function renderToolStrip")
    block = control[start:control.index("function renderActivity")]
    for banned in ("output", "arguments", "JSON.stringify", "failure_class", "payload"):
        assert banned not in block
    strip_css = css.split(".tool-strip{")[1].split(".objective-hud{")[0]
    assert "animation" not in strip_css
    assert "@keyframes" not in strip_css


def test_static_tool_strip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="toolStrip"' in page.text
        assert EMPTY in page.text
        module = client.get("/static/state.mjs")
        assert module.status_code == 200
        assert "export function toolCallStrip" in module.text
        js = client.get("/static/control.js")
        assert js.status_code == 200
        assert "renderToolStrip" in js.text
        styles = client.get("/static/control.css")
        assert styles.status_code == 200
        assert ".tool-strip{" in styles.text
