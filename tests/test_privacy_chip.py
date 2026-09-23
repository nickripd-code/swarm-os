"""Mission privacy chip: cloud_allowed or local_only from the loaded field only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models import Mission
from app.store import Store

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "privacy_chip_cases.mjs"
UNAVAILABLE = "privacy unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS privacy harness")
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


def test_unreadable_privacy_is_unavailable(cases):
    for name in (
        "missing", "null", "bareString", "list", "noPrivacy", "nullPrivacy",
        "blankPrivacy", "wrongCase", "spaced", "flagOnly", "flagFalse",
        "objectPrivacy", "numberPrivacy", "unknown", "eventDoesNotInvent",
        "replayOmitsUnreadable",
    ):
        view = cases[name]
        assert view["known"] is False, name
        assert view["mode"] is None, name
        assert view["label"] == UNAVAILABLE, name
    assert cases["unavailable"] == UNAVAILABLE


def test_exact_privacy_is_cloud_or_local(cases):
    assert cases["cloudAllowed"] == {"known": True, "mode": "cloud_allowed", "label": "CLOUD ALLOWED"}
    assert cases["localOnly"] == {"known": True, "mode": "local_only", "label": "LOCAL ONLY"}
    assert cases["flagDoesNotOverrideCloud"]["label"] == "CLOUD ALLOWED"
    assert cases["flagDoesNotOverrideLocal"]["label"] == "LOCAL ONLY"
    assert cases["eventDoesNotOverwrite"]["mode"] == "local_only"
    assert cases["replayKeepsLoaded"]["mode"] == "local_only"


def test_chip_reads_privacy_and_hides_without_a_mission_or_in_preview():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert 'id="privacyChip" class="hud-chip privacy" hidden>privacy unavailable</span>' in html
    assert "export function missionPrivacy" in state
    assert "PRIVACY_UNAVAILABLE" in state
    assert 'mission.privacy === "local_only"' in state
    assert 'mission.privacy === "cloud_allowed"' in state
    start = control.index('if($("privacyChip"))')
    snippet = control[start:start + 420]
    assert "missionPrivacy(mission)" in snippet
    assert "state.preview" in snippet
    assert "el.hidden=true" in snippet
    assert "textContent=view.label" in snippet
    assert "local_only" not in snippet
    assert ".hud-chips{display:flex;flex-wrap:wrap;" in css
    assert ".hud-chip.privacy.local_only" in css
    assert ".hud-chips{position:static;justify-content:flex-start}" in css


def test_loaded_mission_privacy_round_trips(tmp_path, monkeypatch):
    import app.main as main

    local = Store(str(tmp_path / "privacy.db"))
    monkeypatch.setattr(main, "store", local)
    local_only = Mission(goal="Stay on this machine", privacy="local_only")
    cloud = Mission(goal="Cloud models are allowed")
    local.save_mission(local_only)
    local.save_mission(cloud)
    with TestClient(main.app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="privacyChip"' in page.text
        assert "privacy unavailable" in page.text
        local_body = client.get(f"/api/missions/{local_only.id}")
        assert local_body.status_code == 200
        assert local_body.json()["privacy"] == "local_only"
        cloud_body = client.get(f"/api/missions/{cloud.id}")
        assert cloud_body.status_code == 200
        assert cloud_body.json()["privacy"] == "cloud_allowed"
        rejected = client.post("/api/missions", json={"goal": "Invent a mode", "privacy": "secret"})
        assert rejected.status_code == 422
