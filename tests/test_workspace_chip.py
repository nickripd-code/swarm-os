"""Mission Control workspace chip: reported root and provider only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "workspace_chip_cases.mjs"
UNAVAILABLE = "unavailable"
ROOT_PATH = "/tmp/swarm-workspaces"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the workspace chip harness")
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


def test_no_mission_or_preview_stays_empty(cases):
    for name in ("noMission", "preview"):
        view = cases[name]
        assert view["visible"] is False
        assert view["present"] is False
        assert view["path"] is None
        assert view["kind"] is None
        assert view["label"] == "UNAVAILABLE"
        assert view["status"] == UNAVAILABLE


def test_loaded_mission_without_workspace_fields_is_unavailable(cases):
    for name in ("missingHealth", "emptyHealth", "blankRoot"):
        view = cases[name]
        assert view["visible"] is True
        assert view["present"] is False
        assert view["path"] is None
        assert view["label"] == "UNAVAILABLE"
        assert ROOT_PATH not in json.dumps(view)


def test_local_healthy_root_is_shown_verbatim(cases):
    view = cases["localHealthy"]
    assert view["visible"] is True
    assert view["present"] is True
    assert view["kind"] == "local"
    assert view["path"] == ROOT_PATH
    assert view["status"] == "healthy"
    assert view["label"] == "LOCAL"
    assert "mission-1" not in view["path"]


def test_remote_provider_is_labeled_remote(cases):
    view = cases["remoteHealthy"]
    assert view["kind"] == "remote"
    assert view["path"] == "sandbox://box-1"
    assert view["label"] == "REMOTE"
    assert view["present"] is True


def test_reported_unwritable_root_keeps_path_and_unavailable_status(cases):
    view = cases["localUnwritable"]
    assert view["present"] is True
    assert view["kind"] == "local"
    assert view["path"] == ROOT_PATH
    assert view["status"] == "unavailable"
    assert view["label"] == "LOCAL"


def test_unconfigured_or_odd_status_does_not_surface_a_path(cases):
    for name in ("unconfiguredWithRoot", "weirdStatus", "numericRoot"):
        view = cases[name]
        assert view["present"] is False
        assert view["path"] is None
        assert view["label"] == "UNAVAILABLE"


def test_unknown_provider_does_not_become_local_or_remote(cases):
    unknown = cases["unknownProvider"]
    assert unknown["kind"] is None
    assert unknown["label"] == "UNAVAILABLE"
    assert unknown["path"] == ROOT_PATH
    assert unknown["present"] is True
    backend = cases["backendOnly"]
    assert backend["kind"] is None
    assert backend["label"] == "UNAVAILABLE"
    assert backend["path"] == ROOT_PATH
    docker = cases["dockerDoesNotFlipKind"]
    assert docker["kind"] == "local"
    assert docker["label"] == "LOCAL"


def test_missing_root_keeps_known_kind_without_a_path(cases):
    view = cases["missingRoot"]
    assert view["kind"] == "local"
    assert view["present"] is False
    assert view["path"] is None
    assert view["label"] == "UNAVAILABLE"


def test_mission_workspace_record_is_not_filled_from_health(cases):
    winner = cases["missionRecordWins"]
    assert winner["kind"] == "remote"
    assert winner["path"] == "sandbox://mission"
    assert winner["path"] != ROOT_PATH
    empty = cases["emptyMissionRecord"]
    assert empty["path"] is None
    assert empty["present"] is False
    assert empty["label"] == "UNAVAILABLE"
    assert ROOT_PATH not in json.dumps(empty)


def test_provider_token_is_trimmed(cases):
    view = cases["providerCase"]
    assert view["kind"] == "local"
    assert view["label"] == "LOCAL"
    assert view["path"] == ROOT_PATH


def test_chip_source_does_not_invent_a_workspace_path():
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    blob = state + control + html
    assert "export function workspaceChipView" in state
    assert "workspaceChipView" in control
    assert 'id="workspaceChip"' in html
    assert 'id="workspaceChipPath"' in html
    assert ">UNAVAILABLE<" in html
    assert "swarm-workspaces" not in blob
    assert "SWARM_WORKSPACE_ROOT" not in blob
    assert "/tmp/" not in control
    assert "/tmp/" not in state


def test_static_workspace_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="workspaceChip"' in page.text
        assert ">UNAVAILABLE<" in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function workspaceChipView" in state.text
        health = client.get("/api/health")
        assert health.status_code == 200
        workspace = health.json()["workspace"]
        assert workspace["provider"] in {"local", "remote"}
        assert workspace["status"] in {"healthy", "unavailable", "unconfigured"}
        assert workspace["root"] is None or isinstance(workspace["root"], str)
