"""Mission Control live connection chip: socket readyState only, never invented connected."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "connection_chip_cases.mjs"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the connection chip harness")
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


def test_missing_link_stays_unavailable(cases):
    assert cases["unavailable"] == "unavailable"
    for view in cases["missing"]:
        assert view["state"] == "unknown"
        assert view["label"] == "unavailable"
        assert view["connected"] is False
        assert view["transport"] is None


def test_health_and_bare_connected_flag_are_not_a_socket(cases):
    for key in ("health", "claimed"):
        view = cases[key]
        assert view["connected"] is False
        assert view["label"] == "unavailable"
        assert view["state"] == "unknown"


def test_open_websocket_is_the_only_connected_state(cases):
    view = cases["open"]
    assert view == {
        "state": "connected",
        "label": "connected",
        "connected": True,
        "transport": "websocket",
    }


def test_non_open_sockets_never_report_connected(cases):
    for key in ("stringOpen", "openWhileRetry", "connecting", "closing", "closed", "retry",
                "sseClosed", "sseConnecting", "otherTransport", "boolReady", "floatReady", "flagString"):
        view = cases[key]
        assert view["connected"] is False, key
        assert view["label"] != "connected", key
    assert cases["stringOpen"]["label"] == "unavailable"
    assert cases["openWhileRetry"]["label"] == "reconnecting"
    assert cases["connecting"]["label"] == "reconnecting"
    assert cases["closing"]["label"] == "disconnected"
    assert cases["closed"]["label"] == "disconnected"
    assert cases["retry"]["label"] == "reconnecting"
    assert cases["sseClosed"]["label"] == "disconnected"
    assert cases["sseConnecting"]["label"] == "reconnecting"
    assert cases["otherTransport"]["label"] == "unavailable"
    assert cases["boolReady"]["label"] == "unavailable"
    assert cases["floatReady"]["label"] == "unavailable"
    assert cases["flagString"]["label"] == "disconnected"


def test_open_sse_ready_state_is_connected(cases):
    view = cases["sseOpen"]
    assert view["transport"] == "sse"
    assert view["state"] == "connected"
    assert view["connected"] is True


def test_shell_chip_starts_unavailable_and_follows_the_socket():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert 'id="connectionChip"' in html
    assert 'data-connected="false"' in html
    assert 'data-state="unknown"' in html
    assert ">unavailable</span>" in html
    assert 'data-connected="true"' not in html
    assert "EventSource" not in control
    assert 'transport:"sse"' not in control
    assert "connectionChipView" in control
    assert "publishLink(false)" in control
    assert "publishLink(true)" in control
    assert state.count("connected: true") == 1
    assert "export function connectionChipView" in state
    assert ".hud-chip.link.connected" in css
    assert ".hud-chip.link.disconnected" in css
    assert ".hud-chip.link.reconnecting" in css
    health = control.split("async function initialize")[1].split("const missions")[0]
    assert "publishLink" not in health
    assert "connectionChip" not in health
    chip = control.split("function renderConnectionChip")[1].split("function publishLink")[0]
    assert "configured" not in chip
    assert "connectionChipView(liveLink)" in chip


def test_connection_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="connectionChip"' in page.text
        assert "unavailable" in page.text
        assert 'data-connected="false"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function connectionChipView" in state.text
        script = client.get("/static/control.js")
        assert script.status_code == 200
        assert "connectionChipView" in script.text
