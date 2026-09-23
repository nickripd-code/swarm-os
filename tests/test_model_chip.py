"""Read-only Mission Control model chip: recorded model ids only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "model_chip_cases.mjs"
LONG_ID = "accounts/fireworks/models/llama-v3p1-8b-instruct"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS model chip harness")
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


def test_hidden_without_a_mission(cases):
    assert cases["noMission"] == {"visible": False, "model": None, "label": ""}


def test_preview_stays_hidden_even_with_a_model_string(cases):
    assert cases["preview"]["visible"] is False
    assert cases["preview"]["model"] is None
    assert cases["preview"]["label"] == ""


def test_loaded_mission_without_a_model_field_stays_hidden(cases):
    assert cases["missing"]["visible"] is False
    assert cases["blank"]["lastModel"] is None
    assert cases["blank"]["chip"]["visible"] is False
    assert "gpt-6-astra" not in json.dumps(cases["blank"])


def test_current_call_then_completed_model_id(cases):
    assert cases["started"]["chip"] == {
        "visible": True, "model": "gpt-6-astra", "label": "gpt-6-astra",
    }
    assert cases["completed"]["lastModel"] == "gpt-6-astra-2026-09"
    assert cases["completed"]["chip"]["label"] == "gpt-6-astra-2026-09"


def test_later_model_replaces_the_chip_and_blank_does_not_erase_it(cases):
    assert cases["failover"]["lastModel"] == LONG_ID
    assert cases["failover"]["chip"]["visible"] is True
    assert cases["failover"]["chip"]["model"] == LONG_ID
    assert cases["failover"]["chip"]["label"].endswith("…")
    assert cases["failover"]["chip"]["label"] != LONG_ID
    assert cases["blankDoesNotErase"]["chip"]["model"] == LONG_ID


def test_replay_hides_the_chip_until_the_recorded_model_event(cases):
    assert cases["beforeModel"]["visible"] is False
    assert cases["atModel"] == {
        "visible": True, "model": "command-a-03-2025", "label": "command-a-03-2025",
    }


def test_recorded_model_id_rejects_invented_or_unsafe_values(cases):
    assert cases["recorded"]["spaces"] == "grok-3"
    assert cases["recorded"]["empty"] is None
    assert cases["recorded"]["nullish"] is None
    assert cases["recorded"]["object"] is None
    assert cases["recorded"]["newline"] is None


def test_truncate_keeps_code_points_intact(cases):
    assert cases["truncate"]["short"] == "gpt-6-astra"
    assert cases["truncate"]["long"].endswith("…")
    assert cases["truncate"]["longFullLength"] > 32
    assert len(cases["truncate"]["pairChars"]) == 6
    assert cases["truncate"]["pairChars"][-1] == "…"
    assert cases["truncate"]["pair"] == "model…"


def test_chip_markup_is_hidden_and_does_not_read_the_health_model():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="missionModel" class="hud-chip model" hidden' in html
    assert ".hud-chip.model{max-width:12rem;overflow:hidden;text-overflow:ellipsis" in css
    assert "max-width:6.5rem" in css
    assert "missionModelChip" in control
    assert "health?.openai?.model" not in control.split("missionModelChip(state)")[1].split("const running")[0]
    assert "gpt-6-astra" not in state
    assert 'lastModel: null' in state


def test_static_model_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="missionModel"' in page.text
        assert 'class="hud-chip model" hidden' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function missionModelChip" in state.text
