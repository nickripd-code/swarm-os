"""Read-only org-map node chip: count only an explicit map, never invent 0."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "org_map_nodes_cases.mjs"
UNAVAILABLE = "org map unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the org-map node harness")
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


def test_chip_is_hidden_without_a_loaded_mission(cases):
    assert cases["hidden"] == {"hidden": True, "known": False, "count": None, "label": ""}
    assert cases["hiddenWithMap"]["hidden"] is True
    assert cases["hiddenWithMap"]["count"] is None


def test_missing_map_is_unavailable_not_zero(cases):
    for key in ("missing", "nullMap", "emptyObject", "numericZero", "stringZero", "loneId", "countField", "junk"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE
        assert view["label"] != "0 nodes"


def test_explicit_empty_structure_is_zero(cases):
    for key in ("emptyList", "emptyAgents", "emptyTopology"):
        view = cases[key]
        assert view["known"] is True
        assert view["count"] == 0
        assert view["label"] == "0 nodes"


def test_counts_unique_org_tree_nodes(cases):
    assert cases["agents"]["count"] == 2
    assert cases["agents"]["label"] == "2 nodes"
    assert cases["topology"]["count"] == 2
    assert cases["list"]["count"] == 3
    assert cases["list"]["label"] == "3 nodes"
    assert cases["explicitNodes"] == 1


def test_chip_is_read_only_and_fail_closed_in_the_shell():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="orgMapNodes"' in html
    assert "hidden" in html.split('id="orgMapNodes"', 1)[1].split(">", 1)[0]
    assert UNAVAILABLE in html
    assert "export function orgMapNodeView" in state
    assert "orgMapNodeView" in control
    assert 'request("/api/missions/"+missionId+"/agents")' in control
    chip = control.split("function renderOrgMapChip()", 1)[1].split("function clearOrgMap()", 1)[0]
    assert "state.agents.size" not in chip
    assert "orgMapNodeView" in chip
