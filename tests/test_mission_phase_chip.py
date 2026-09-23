"""Read-only Mission Control phase chip: known status labels only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import MissionStatus

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "mission_phase_chip_cases.mjs"
KNOWN = {status.value for status in MissionStatus}


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS phase chip harness")
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


def test_known_phases_match_mission_status_badge_vocabulary(cases):
    shown = {status: view["label"] for status, view in cases["known"].items() if status in KNOWN}
    assert set(shown) == KNOWN
    for status, label in shown.items():
        view = cases["known"][status]
        assert view["hidden"] is False
        assert label == status.upper()
        assert view["statusClass"] == status
        assert label != "unavailable"


def test_loaded_status_events_use_the_same_labels(cases):
    assert cases["known"]["mixedCase"] == {
        "hidden": False, "label": "PAUSED", "statusClass": "paused",
    }
    assert cases["known"]["afterStart"]["label"] == "RUNNING"
    assert cases["known"]["afterStart"]["hidden"] is False
    assert cases["known"]["afterWaiting"]["label"] == "WAITING"


def test_preview_and_no_mission_hide_the_chip_with_an_empty_label(cases):
    for view in cases["hidden"].values():
        assert view == {"hidden": True, "label": "", "statusClass": ""}


def test_missing_blank_or_unknown_status_is_unavailable(cases):
    for view in cases["unavailable"].values():
        assert view["hidden"] is False
        assert view["label"] == "unavailable"
        assert view["statusClass"] == "unavailable"
        assert view["label"] not in {status.upper() for status in KNOWN}
