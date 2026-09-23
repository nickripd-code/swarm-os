"""Read-only Mission Control mission id chip: loaded id only, never invented."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "mission_id_chip_cases.mjs"
UUID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS mission id chip harness")
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
    assert view["visible"] is False
    assert view["id"] is None
    assert view["label"] == ""


def test_empty_mission_hides_the_chip(cases):
    _hidden(cases["none"])
    _hidden(cases["missing"])
    _hidden(cases["empty"])
    _hidden(cases["blank"])


def test_rewritten_or_non_string_ids_stay_hidden(cases):
    _hidden(cases["padded"])
    _hidden(cases["number"])
    _hidden(cases["objectId"])
    _hidden(cases["control"])


def test_preview_never_shows_an_id(cases):
    _hidden(cases["previewFlag"])
    _hidden(cases["previewSentinel"])


def test_string_preview_flag_does_not_hide_a_loaded_id(cases):
    view = cases["stringPreviewFlag"]
    assert view["visible"] is True
    assert view["id"] == UUID
    assert view["label"] == "11111111…"


def test_loaded_uuid_is_a_prefix_not_a_new_id(cases):
    view = cases["uuid"]
    assert view["visible"] is True
    assert view["id"] == UUID
    assert view["label"] == "11111111…"
    assert UUID.startswith(view["label"].removesuffix("…"))
    assert view["label"] != UUID
    other = cases["other"]
    assert other["id"] == OTHER
    assert other["label"] == "22222222…"
    assert other["label"] != view["label"]


def test_short_ids_are_shown_whole(cases):
    assert cases["short"] == {"visible": True, "id": "abc123", "label": "abc123"}
    assert cases["exact8"] == {"visible": True, "id": "abcd1234", "label": "abcd1234"}
    assert cases["nine"]["visible"] is True
    assert cases["nine"]["id"] == "abcdefghi"
    assert cases["nine"]["label"] == "abcdefgh…"


def test_chip_is_wired_read_only_and_phone_short():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="missionIdChip" class="hud-chip mission-id" hidden' in html
    assert "missionIdChip" in control
    assert "missionIdChip(mission,{preview:!!state.preview})" in control
    assert ".hud-chip.mission-id{letter-spacing:.15px;max-width:12ch;overflow:hidden;text-overflow:ellipsis}" in css
    assert "padding-right:202px" in css
    assert "export function missionIdChip" in state
    assert "missionIdChip" not in (ROOT / "app/runtime.py").read_text(encoding="utf-8")


def test_static_mission_id_chip_is_served_hidden(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="missionIdChip"' in page.text
        assert "hidden" in page.text.split('id="missionIdChip"', 1)[1].split(">", 1)[0]
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function missionIdChip" in state.text
