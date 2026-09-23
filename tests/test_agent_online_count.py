"""Online-agent chip: roster status `running` only, never an invented count."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "agent_online_count_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the agent online-count harness")
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


def test_hidden_with_empty_label_without_a_mission_or_in_preview(cases):
    for key in ("noMission", "preview"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["label"] == ""
        assert view["known"] is False
        assert view["count"] is None


def test_missing_roster_is_unavailable_not_zero(cases):
    for key in (
        "rosterMissing",
        "rosterNull",
        "rosterNotList",
        "explicitZeroIsNotOnline",
        "agentsCountAliasIsNotOnline",
        "missingStatus",
        "unknownStatus",
        "duplicateId",
        "missingId",
    ):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE
        assert view["label"] != "0"


def test_known_zero_only_from_a_readable_roster(cases):
    for key in ("emptyList", "emptyAgentsField", "noneRunning"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is True
        assert view["count"] == 0
        assert view["label"] == "0"


def test_running_status_is_the_only_online_count(cases):
    assert cases["oneRunning"] == {"hidden": False, "label": "1", "known": True, "count": 1}
    assert cases["twoRunning"]["count"] == 2
    assert cases["twoRunning"]["label"] == "2"
    assert cases["listBeatsConflictingCount"]["count"] == 1
    assert cases["listBeatsConflictingCount"]["label"] == "1"
    assert cases["unavailable"] == UNAVAILABLE
