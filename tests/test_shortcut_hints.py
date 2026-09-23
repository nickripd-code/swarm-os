"""Read-only Mission Control shortcut hints: list only documented key chords."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "shortcut_hint_cases.mjs"
INVENTED = ("Ctrl+K", "Ctrl+S", "Cmd+K", "Meta+K", "Alt+S", "Escape")


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS shortcut hint harness")
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


def test_missing_listener_or_literal_stays_unavailable(cases):
    for name in (
        "empty",
        "noListener",
        "listenerFlagWithoutSource",
        "unwired",
        "missingAction",
        "chordNotLiteral",
        "commandVerbs",
    ):
        assert cases[name]["available"] is False
        assert cases[name]["status"] == cases["unavailable"]
        assert cases[name]["items"] == []


def test_documented_listener_chord_is_listed_once(cases):
    view = cases["documented"]
    assert view["available"] is True
    assert view["items"] == [
        {"chord": "Ctrl+K", "action": "Focus command"},
        {"chord": "Escape", "action": "Dismiss"},
    ]


def test_static_strip_is_unavailable_and_does_not_invent_chords():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="shortcutHints"' in html
    assert 'data-available="false"' in html
    assert 'id="shortcutHintStatus"' in html
    assert ">unavailable</p>" in html
    assert 'id="shortcutHintList"' in html
    assert "hidden" in html.split('id="shortcutHintList"', 1)[1].split(">", 1)[0]
    assert "export function shortcutHintView" in state
    assert 'shortcutHintView({bindings:[],hasKeyListener:false,source:""})' in control
    for listener in ("keydown", "keyup", "keypress"):
        assert f'addEventListener("{listener}"' not in control
        assert f"addEventListener('{listener}'" not in control
    surface = html + control
    for chord in INVENTED:
        assert chord not in surface
    assert ".shortcut-hints{" in css
    assert "animation" not in css.split(".shortcut-hints{")[1].split(".command-drawer{")[0]
    assert "react" not in (html + css + control + state).lower()
    assert "pixi" not in (html + css + control + state).lower()


def test_shortcut_strip_is_served_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="shortcutHints"' in page.text
        assert 'data-available="false"' in page.text
        assert ">unavailable</p>" in page.text
        for chord in INVENTED:
            assert chord not in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function shortcutHintView" in state.text
        script = client.get("/static/control.js")
        assert script.status_code == 200
        assert 'hasKeyListener:false' in script.text
        assert 'addEventListener("keydown"' not in script.text
