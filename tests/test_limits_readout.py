"""Pre-launch limits readout: real caps only, never an invented dollar budget."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "limits_readout_cases.mjs"


def _labels(view: dict) -> dict[str, str]:
    return {chip["kind"]: chip["label"] for chip in view["chips"]}


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS limits readout harness")
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


def test_missing_payload_does_not_invent_caps_or_dollars(cases):
    view = cases["missing"]
    assert view["available"] is False
    assert view["tokenKnown"] is False
    blob = " ".join(chip["label"] for chip in view["chips"])
    assert "$" not in blob
    assert "20" not in blob
    assert "unavailable" in blob


def test_health_create_defaults_render_count_caps_and_known_token_cap(cases):
    view = cases["healthDefaults"]
    labels = _labels(view)
    assert view["available"] is True
    assert view["phase"] == "prelaunch"
    assert view["tokenKnown"] is True
    assert view["tokenSource"] == "server_default"
    assert labels["agents"] == "20 agents"
    assert labels["depth"] == "depth 4"
    assert labels["tools"] == "200 tool calls"
    assert labels["runtime"] == "5m runtime"
    assert labels["token"] == "$3.00 token cap"
    assert "server default" in view["note"]
    assert "read only" in view["note"]


def test_unknown_token_cap_stays_unavailable(cases):
    view = cases["unknownToken"]
    labels = _labels(view)
    assert labels["runtime"] == "90s runtime"
    assert labels["token"] == "token cap unavailable"
    assert view["tokenKnown"] is False
    assert "$" not in labels["token"]


def test_mission_limits_override_create_defaults(cases):
    view = cases["missionListed"]
    labels = _labels(view)
    assert view["phase"] == "mission"
    assert view["tokenSource"] == "listed"
    assert labels["agents"] == "3 agents"
    assert labels["depth"] == "depth 2"
    assert labels["tools"] == "8 tool calls"
    assert labels["runtime"] == "2m runtime"
    assert labels["token"] == "$1.50 token cap"


def test_listed_token_cap_above_hard_cap_shows_the_enforced_cap(cases):
    view = cases["hardCap"]
    labels = _labels(view)
    assert view["tokenSource"] == "hard_cap"
    assert labels["token"] == "$10.00 token cap"
    assert labels["runtime"] == "1h runtime"
    assert "$50" not in labels["token"]
    assert "hard cap" in view["note"]


def test_unset_mission_token_cap_uses_known_server_default(cases):
    view = cases["missionUnsetToken"]
    assert view["phase"] == "mission"
    assert view["tokenSource"] == "server_default"
    assert _labels(view)["token"] == "$3.00 token cap"
    assert "server default" in view["note"]


def test_preview_does_not_adopt_synthetic_limits(cases):
    view = cases["previewIgnoresFakeLimits"]
    labels = _labels(view)
    assert view["phase"] == "prelaunch"
    assert labels["agents"] == "20 agents"
    assert labels["token"] == "$3.00 token cap"
    assert "999" not in labels["agents"]
    assert "$99" not in labels["token"]


def test_corrupt_counts_are_omitted(cases):
    view = cases["corruptCounts"]
    kinds = [chip["kind"] for chip in view["chips"]]
    assert "agents" not in kinds
    assert "depth" not in kinds
    assert "tools" not in kinds
    assert _labels(view)["token"] == "token cap unavailable"


def test_configured_zero_token_cap_is_shown(cases):
    view = cases["zeroListed"]
    labels = _labels(view)
    assert view["tokenSource"] == "listed"
    assert labels["token"] == "$0 token cap"
    assert labels["depth"] == "depth 0"
    assert labels["runtime"] == "1m runtime"


def test_shell_mounts_read_only_limits_readout_inside_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    start = html.index('id="objectiveHud"')
    end = html.index('id="questionPanel"')
    hud = html[start:end]
    assert 'id="limitsReadout"' in hud
    assert 'id="limitsChips"' in hud
    assert 'id="limitsNote"' in hud
    assert "Caps unavailable" in hud
    assert "<form" not in hud[hud.index('id="limitsReadout"'):]
    assert 'id="limitsReadout"' in html
    assert html.index('id="limitsReadout"') < html.index('class="telemetry-drawer"')
    assert ".limits-readout{" in css
    assert ".limits-chip{" in css
    assert "limitsReadoutView" in control
    assert "health.mission_limits" in control
    assert "change-budget" not in control
    assert "/budget" not in control
    assert "/pause" not in control
    assert "/resume" not in control
    render = control.split("function renderLimits()", 1)[1].split("function clearAlerts", 1)[0]
    assert "fetch(" not in render
    assert "POST" not in render


def test_health_reports_create_defaults_from_the_scheduler(monkeypatch):
    monkeypatch.delenv("SWARM_DEFAULT_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("SWARM_TOKEN_BUDGET_HARD_CAP", raising=False)
    from app.health import mission_limits_status
    from app.models import Mission, MissionLimits
    from app.resources import ResourceScheduler

    status = mission_limits_status()
    limits = MissionLimits()
    expected = ResourceScheduler().budget_for(Mission(goal="limits readout", limits=limits))
    assert status["available"] is True
    assert status["phase"] == "create_defaults"
    assert status["max_agents"] == limits.max_agents == 20
    assert status["max_depth"] == limits.max_depth == 4
    assert status["max_tool_calls"] == limits.max_tool_calls == 200
    assert status["max_runtime_seconds"] == limits.max_runtime_seconds == 300
    assert status["max_token_cost"] is None
    assert status["token_cost_known"] is True
    assert status["token_cost_source"] == "server_default"
    assert status["token_cost_cap"] == expected == 3.0
    assert status["token_cost_hard_cap"] == 10.0
    assert "max_payment_amount" not in status


def test_health_token_cap_follows_env_and_hard_cap(monkeypatch):
    monkeypatch.setenv("SWARM_DEFAULT_TOKEN_BUDGET", "1.25")
    monkeypatch.setenv("SWARM_TOKEN_BUDGET_HARD_CAP", "10")
    from app.health import mission_limits_status

    assert mission_limits_status()["token_cost_cap"] == 1.25

    monkeypatch.setenv("SWARM_DEFAULT_TOKEN_BUDGET", "50")
    monkeypatch.setenv("SWARM_TOKEN_BUDGET_HARD_CAP", "4")
    clamped = mission_limits_status()
    assert clamped["token_cost_cap"] == 4.0
    assert clamped["token_cost_hard_cap"] == 4.0
    assert clamped["token_cost_source"] == "server_default"


def test_health_endpoint_includes_mission_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    monkeypatch.delenv("SWARM_DEFAULT_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("SWARM_TOKEN_BUDGET_HARD_CAP", raising=False)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        limits = health.json()["mission_limits"]
        assert limits["max_agents"] == 20
        assert limits["max_depth"] == 4
        assert limits["max_tool_calls"] == 200
        assert limits["max_runtime_seconds"] == 300
        assert limits["token_cost_known"] is True
        assert limits["token_cost_cap"] == 3.0
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="limitsReadout"' in page.text
        assert "Caps unavailable" in page.text
