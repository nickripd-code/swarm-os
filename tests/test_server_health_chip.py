"""Read-only Mission Control server health chip. Never invents uptime."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "server_health_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the server health chip harness")
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


def test_missing_health_is_unavailable(cases):
    assert cases["missing"]["known"] is False
    assert cases["missing"]["label"] == UNAVAILABLE
    assert cases["empty"]["label"] == UNAVAILABLE
    assert cases["unavailable"] == UNAVAILABLE


def test_null_or_invalid_clock_does_not_invent_uptime(cases):
    for name in ("nullClock", "negativeUptime", "stringUptime", "nanUptime", "futureStart", "badStart"):
        view = cases[name]
        assert view["known"] is False, name
        assert view["label"] == UNAVAILABLE, name
        assert view["uptimeLabel"] is None, name


def test_reported_uptime_is_formatted_without_using_started_at(cases):
    zero = cases["zero"]
    assert zero["known"] is True
    assert zero["label"] == "up 0s · v0.2.0"
    ninety = cases["ninety"]
    assert ninety["label"] == "up 1m 30s · v0.2.0"
    assert ninety["uptimeLabel"] == "1m 30s"
    assert cases["versionPrefixed"]["label"] == "up 1h 1m · v0.2.0"
    assert cases["noVersion"]["label"] == "up 45s"
    assert cases["blankVersion"]["label"] == "up 12s"


def test_age_uses_started_at_only_when_uptime_is_absent(cases):
    age = cases["ageFromStart"]
    assert age["known"] is True
    assert age["label"] == "up 1m 30s · v0.2.0"
    assert cases["format"]["negative"] is None
    assert cases["format"]["text"] is None
    assert cases["format"]["zero"] == "0s"
    assert cases["format"]["day"] == "1d 1h"


def test_shell_chip_defaults_to_unavailable():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert 'id="serverHealth"' in html
    assert ">unavailable</span>" in html
    assert "serverHealthChip" in control
    assert "renderServerHealth(null)" in control
    assert "setInterval" not in control.split("function renderServerHealth")[1].split("function renderHud")[0]
    assert ".header-actions .hud-chip[data-known=\"false\"]" in css


def test_api_health_reports_process_clock(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DATABASE_PATH", str(tmp_path / "swarm.db"))
    monkeypatch.setenv("SWARM_PROCESS_WORKERS", "0")
    from fastapi.testclient import TestClient

    import app.main as main
    from app.main import app

    previous = main._server_started_at
    started = datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc)
    try:
        with TestClient(app) as client:
            main._server_started_at = started
            response = client.get("/api/health")
            assert response.status_code == 200
            body = response.json()
            assert body["started_at"].startswith("2026-09-23T11:00:00")
            assert isinstance(body["uptime"], (int, float))
            assert body["uptime"] >= 0
            assert body["version"] == app.version
            assert body["uptime"] != ""
    finally:
        main._server_started_at = previous


def test_server_liveness_does_not_invent_uptime():
    import app.main as main
    from app.main import app, server_liveness

    previous = main._server_started_at
    try:
        main._server_started_at = None
        unknown = server_liveness()
        assert unknown == {"started_at": None, "uptime": None, "version": app.version}

        started = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        main._server_started_at = started
        negative = server_liveness(now=started - timedelta(seconds=5))
        assert negative["started_at"].startswith("2026-09-23T12:00:00")
        assert negative["uptime"] is None
        assert negative["version"] == app.version

        exact = server_liveness(now=started + timedelta(seconds=90))
        assert exact["uptime"] == 90
    finally:
        main._server_started_at = previous
