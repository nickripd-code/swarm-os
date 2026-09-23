"""Mission Control latency chip: measured pong fields only, never invented milliseconds."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "latency_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the latency chip harness")
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


def _no_milliseconds(view: dict) -> None:
    assert view["known"] is False
    assert view["latencyMs"] is None
    assert view["pongAgeMs"] is None
    assert view["label"] == UNAVAILABLE
    assert "ms" not in view["label"]


def test_missing_link_stays_hidden_without_a_number(cases):
    assert cases["unavailable"] == UNAVAILABLE
    for view in cases["missing"]:
        assert view["visible"] is False
        assert view["connected"] is False
        _no_milliseconds(view)


def test_disconnected_socket_hides_even_if_numbers_are_present(cases):
    for key in ("closedWithNumbers", "reconnecting", "connecting", "stringReady", "sse"):
        view = cases[key]
        assert view["visible"] is False, key
        assert view["connected"] is False, key
        _no_milliseconds(view)


def test_open_socket_without_pong_fields_is_unavailable(cases):
    for key in ("openMissing", "stringLatency", "boolLatency", "negative", "nanLatency", "futurePong", "missingClock"):
        view = cases[key]
        assert view["visible"] is True, key
        assert view["connected"] is True, key
        _no_milliseconds(view)


def test_measured_pong_shows_round_trip_and_age(cases):
    view = cases["measured"]
    assert view["known"] is True
    assert view["latencyMs"] == 42.4
    assert view["pongAgeMs"] == 1_500
    assert view["label"] == "42 ms · pong 1s"
    assert view["visible"] is True


def test_explicit_zero_is_shown_and_not_rewritten(cases):
    view = cases["zero"]
    assert view["known"] is True
    assert view["latencyMs"] == 0
    assert view["pongAgeMs"] == 0
    assert view["label"] == "0 ms · pong 0 ms"


def test_pong_age_without_round_trip_does_not_invent_latency(cases):
    view = cases["pongOnly"]
    assert view["latencyMs"] is None
    assert view["pongAgeMs"] == 1_600
    assert view["label"] == "pong 1s"
    assert not view["label"].startswith("0")


def test_future_pong_does_not_hide_a_real_round_trip(cases):
    view = cases["latencyDespiteFuturePong"]
    assert view["known"] is True
    assert view["latencyMs"] == 10
    assert view["pongAgeMs"] is None
    assert view["label"] == "10 ms"


def test_mission_events_cannot_supply_latency(cases):
    assert cases["missionEventIgnored"]["latencyMs"] == 15
    assert cases["missionEventIgnored"]["lastPongAt"] == 100
    assert cases["notAPong"]["latencyMs"] == 15
    cleared = cases["invalidClears"]
    assert cleared["latencyMs"] is None
    assert cleared["lastPongAt"] is None
    assert cases["omitKeeps"]["latencyMs"] == 15
    assert cases["omitKeeps"]["lastPongAt"] == 100


def test_shell_chip_starts_hidden_and_ignores_model_health():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    match = re.search(r'<span id="latencyChip"[^>]*>[^<]*</span>', html)
    assert match
    tag = match.group(0)
    assert " hidden" in tag
    assert 'data-known="false"' in tag
    assert 'data-connected="false"' in tag
    assert tag.endswith(">unavailable</span>")
    assert "ms" not in tag
    assert "latencyChipView" in control
    assert "applyConnectionSample" in control
    assert 'e.type==="connection.pong"&&!e.event_type' in control
    assert "latencyChipView(liveLink,Date.now())" in control
    assert "performance.now" not in control
    compact = control.replace(" ", "")
    assert "latencyMs:0" not in compact
    assert "latencyMs=0" not in compact
    assert "lastPongAt:Date.now()" not in compact
    health = control.split("async function initialize")[1].split("const missions")[0]
    assert "publishSocket" not in health
    assert "latencyChip" not in health
    assert "connection.pong" not in health
    view = state.split("export function latencyChipView")[1].split("export function applyEvent")[0]
    assert "Date.now" not in view
    assert "performance.now" not in view
    assert ".hud-chip.latency[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.latency")[1].split(".hud-stats")[0]
    server = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "connection.pong" not in server
    assert "latency_ms" not in server


def test_static_latency_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="latencyChip"' in page.text
        assert ">unavailable</span>" in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function latencyChipView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".hud-chip.latency" in css.text
