"""Mission Control connection-state chip: header connection vocabulary only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "connection_state_chip_cases.mjs"
UNAVAILABLE = "unavailable"
KNOWN = (
    "Connecting",
    "Preview",
    "Replay",
    "Live connection",
    "Connection interrupted",
    "Reconnecting…",
    "All execution stopped",
    "Ready to think",
    "API key needed",
    "Server unavailable",
    "Mission completed",
    "Mission failed",
    "Mission stopped",
    "Mission blocked",
)


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the connection-state chip harness")
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


def test_known_header_labels_pass_through(cases):
    assert cases["unavailable"] == UNAVAILABLE
    for label in KNOWN:
        view = cases["known"][label]
        assert view == {"known": True, "hidden": False, "label": label}
    assert cases["trimmed"]["label"] == "Live connection"
    assert cases["textField"]["label"] == "Replay"
    assert cases["known"]["Server unavailable"]["label"] == "Server unavailable"


def test_blank_or_invented_labels_stay_unavailable(cases):
    for view in cases["blank"] + cases["bad"]:
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["label"] == UNAVAILABLE
    assert cases["presentBlank"] == {"known": False, "hidden": False, "label": UNAVAILABLE}
    for view in cases["bad"]:
        assert view["label"] not in {"connected", "disconnected"}


def test_missing_shell_or_hidden_preview_clears_the_chip(cases):
    for view in cases["missing"]:
        assert view == {"known": False, "hidden": True, "label": ""}
    assert cases["absent"] == {"known": False, "hidden": True, "label": ""}
    assert cases["emptyObject"] == {"known": False, "hidden": True, "label": ""}
    assert cases["previewHidden"] == {"known": False, "hidden": True, "label": ""}
    assert cases["previewShown"] == {"known": True, "hidden": False, "label": "Preview"}
    assert cases["hiddenButLive"] == {"known": True, "hidden": False, "label": "Live connection"}


def test_shell_chip_uses_header_vocabulary():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    chip = html.split('id="connectionStateChip"', 1)[1].split("</span>", 1)[0]
    assert 'id="objectiveHud"' in html
    assert html.index('id="connectionStateChip"') > html.index('id="objectiveHud"')
    assert html.index('id="connectionStateChip"') < html.index('class="hud-stats"')
    assert chip.endswith(">Connecting")
    assert "connected" not in chip
    assert "disconnected" not in chip
    assert "connectionStateChipView" in control
    assert "renderConnectionStateChip()" in control
    assert "export function connectionStateChipView" in state
    for label in (
        "Preview",
        "Replay",
        "Live connection",
        "Connection interrupted",
        "Reconnecting…",
        "All execution stopped",
        "Ready to think",
        "API key needed",
        "Server unavailable",
    ):
        assert label in control
    view = state.split("export function connectionStateChipView", 1)[1].split("export function applyEvent", 1)[0]
    assert '"connected"' not in view
    assert '"disconnected"' not in view


def test_connection_state_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="connectionStateChip"' in page.text
        assert ">Connecting</span>" in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function connectionStateChipView" in state.text
        script = client.get("/static/control.js")
        assert script.status_code == 200
        assert "connectionStateChipView" in script.text
