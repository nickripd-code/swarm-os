"""Read-only Mission Control last-tool-name chip. Never invents a name."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_tool_name_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-tool-name chip harness")
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
    assert view["tool"] is None


def _unavailable(view: dict) -> None:
    assert view["hidden"] is False
    assert view["label"] == UNAVAILABLE
    assert view["known"] is False
    assert view["tool"] is None


def test_chip_stays_hidden_without_a_loaded_mission(cases):
    assert cases["unavailable"] == UNAVAILABLE
    _hidden(cases["noMission"])
    _hidden(cases["preview"])
    assert "workspace.read" not in cases["preview"]["label"]


def test_loaded_mission_without_a_recorded_name_is_unavailable(cases):
    for name in (
        "noEvents", "blank", "missingTool", "nameOnly", "invalid", "tooLong",
        "decision", "queueField",
    ):
        _unavailable(cases[name])
        assert "invented" not in cases[name]["label"]
        assert "queue.fake" not in cases[name]["label"]
        assert "<script>" not in cases[name]["label"]


def test_recorded_tool_name_is_shown_verbatim(cases):
    assert cases["started"] == {
        "hidden": False, "label": "workspace.read", "known": True, "tool": "workspace.read",
    }
    assert cases["completed"]["tool"] == "composio.github_get"
    assert cases["failed"]["tool"] == "browser.navigate"
    assert cases["trimmed"]["tool"] == "workspace.read"
    assert cases["newest"]["tool"] == "composio.github_get"
    assert cases["skipInvalidNewer"]["tool"] == "workspace.read"


def test_replay_cursor_uses_only_projected_tool_events(cases):
    _unavailable(cases["replayBefore"])
    assert cases["replayFirst"]["tool"] == "workspace.read"
    assert cases["replaySecond"]["tool"] == "browser.navigate"


def test_markup_starts_hidden_and_does_not_name_a_tool():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="lastToolNameChip" class="hud-chip tool unavailable" hidden' in html
    assert "lastToolNameChip(state)" in control
    assert "export function lastToolNameChip" in state
    assert ".hud-chip.tool.known" in css
    assert ".hud-chip.tool.unavailable" in css
    block = css.split(".hud-chip.tool.unavailable")[1].split("}")[0]
    assert "animation" not in block
    for fake in ("workspace.read", "composio.github_get", "browser.navigate", "example.tool"):
        assert f">{fake}<" not in html


def test_static_last_tool_name_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="lastToolNameChip"' in page.text
        assert 'id="lastToolNameChip" class="hud-chip tool unavailable" hidden' in page.text
        module = client.get("/static/state.mjs")
        assert module.status_code == 200
        assert "export function lastToolNameChip" in module.text
        js = client.get("/static/control.js")
        assert js.status_code == 200
        assert "lastToolNameChip(state)" in js.text
        styles = client.get("/static/control.css")
        assert styles.status_code == 200
        assert ".hud-chip.tool.unavailable" in styles.text
