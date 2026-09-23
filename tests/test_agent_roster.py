"""Read-only Mission Control roster: recorded role, status, and parent only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "roster_cases.mjs"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS roster harness")
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


def test_standby_and_preview_stay_empty(cases):
    standby, preview = cases["standby"], cases["preview"]
    assert standby["empty"] is True
    assert standby["count"] == 0
    assert standby["rows"] == []
    assert standby["message"] == cases["labels"]["noMission"]
    assert standby["note"] == cases["labels"]["live"]
    assert preview["empty"] is True
    assert preview["count"] == 0
    assert preview["rows"] == []
    assert preview["outline"] == []
    assert preview["message"] == cases["labels"]["preview"]
    assert preview["note"] == cases["labels"]["previewNote"]
    assert "mission_controller" not in json.dumps(preview)


def test_loaded_mission_with_no_agents_is_empty(cases):
    empty, replay = cases["emptyMission"], cases["replayEmpty"]
    assert empty["empty"] is True
    assert empty["message"] == cases["labels"]["empty"]
    assert empty["count"] == 0
    assert replay["empty"] is True
    assert replay["message"] == cases["labels"]["replayEmpty"]
    assert replay["note"] == cases["labels"]["replay"]


def test_roster_nests_only_recorded_parent_links(cases):
    view = cases["linked"]
    assert view["empty"] is False
    assert view["count"] == 3
    assert view["unlinked"] == []
    assert [(item["id"], item["depth"]) for item in view["outline"]] == [
        ("root", 0),
        ("child", 1),
        ("leaf", 2),
    ]
    by_id = {row["id"]: row for row in view["rows"]}
    assert by_id["root"]["parentLink"] == "none"
    assert by_id["root"]["parentId"] is None
    assert by_id["root"]["parentRole"] is None
    assert by_id["child"]["parentLink"] == "known"
    assert by_id["child"]["parentId"] == "root"
    assert by_id["child"]["parentRole"] == "mission_controller"
    assert by_id["leaf"]["parentId"] == "child"
    assert by_id["leaf"]["role"] == "reviewer"
    assert "depth" not in by_id["root"]


def test_reparent_and_retire_do_not_invent_agents(cases):
    payload = cases["reparent"]
    assert payload["ids"] == ["root", "other", "child"]
    view = payload["view"]
    by_id = {row["id"]: row for row in view["rows"]}
    assert "ghost" not in by_id
    assert "nobody" not in by_id
    assert by_id["child"]["parentId"] == "other"
    assert by_id["child"]["parentRole"] == "strategist"
    assert by_id["child"]["status"] == "stopped"
    assert by_id["child"]["parentLink"] == "known"
    depths = {item["id"]: item["depth"] for item in view["outline"]}
    assert depths["other"] == 0
    assert depths["child"] == 1


def test_missing_parent_is_not_promoted_to_a_root_node(cases):
    view = cases["missing"]
    assert view["count"] == 1
    assert view["unlinked"] == []
    assert view["outline"] == [{"id": "child", "depth": 0}]
    row = view["rows"][0]
    assert row["parentLink"] == "missing"
    assert row["parentId"] == "not-loaded"
    assert row["parentRole"] is None
    assert row["status"] == "blocked"
    assert all(item["id"] != "not-loaded" for item in view["rows"])


def test_known_child_of_a_missing_parent_stays_on_that_recorded_edge(cases):
    view = cases["island"]
    assert view["unlinked"] == []
    assert [(item["id"], item["depth"]) for item in view["outline"]] == [
        ("mid", 0),
        ("leaf", 1),
    ]
    by_id = {row["id"]: row for row in view["rows"]}
    assert by_id["mid"]["parentLink"] == "missing"
    assert by_id["mid"]["parentRole"] is None
    assert by_id["leaf"]["parentLink"] == "known"
    assert by_id["leaf"]["parentRole"] == "researcher"
    assert "absent" not in by_id


def test_cycles_and_self_parents_stay_flat(cases):
    cycle, loop = cases["cycle"], cases["self"]
    assert cycle["outline"] == []
    assert cycle["unlinked"] == ["a", "b"]
    links = {row["id"]: row["parentLink"] for row in cycle["rows"]}
    assert links == {"a": "known", "b": "known"}
    assert loop["outline"] == [{"id": "loop", "depth": 0}]
    assert loop["rows"][0]["parentLink"] == "self"
    assert loop["rows"][0]["parentRole"] is None
    assert loop["unlinked"] == []


def test_blank_fields_and_duplicates_fail_closed(cases):
    blank = cases["blankRole"]
    ids = [row["id"] for row in blank["rows"]]
    assert ids == ["x", "y"]
    assert "skipped" not in ids
    by_id = {row["id"]: row for row in blank["rows"]}
    assert by_id["x"]["role"] == ""
    assert by_id["x"]["status"] == ""
    assert by_id["x"]["parentLink"] == "none"
    assert by_id["y"]["parentLink"] == "none"
    assert by_id["y"]["parentId"] is None
    assert cases["duplicate"]["count"] == 1
    assert cases["duplicate"]["rows"][0]["role"] == "second"
    assert cases["duplicate"]["rows"][0]["status"] == "running"


def test_agent_updated_can_clear_a_recorded_parent(cases):
    view = cases["updated"]
    by_id = {row["id"]: row for row in view["rows"]}
    assert by_id["child"]["parentLink"] == "none"
    assert by_id["child"]["parentId"] is None
    assert by_id["child"]["status"] == "completed"
    assert view["outline"] == [{"id": "root", "depth": 0}, {"id": "child", "depth": 0}]


def test_roster_markup_is_read_only_and_served(tmp_path, monkeypatch):
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    start = html.index('id="agentRoster"')
    block = html[start:html.index('id="activity"', start)]
    assert "<button" not in block.lower()
    assert "No mission loaded." in block
    assert "agentRosterView" in control
    assert "function renderRoster" in control
    roster_fn = control.split("function renderRoster", 1)[1].split("function render(", 1)[0]
    assert "MISSION CONTROLLER" not in roster_fn
    assert ".roster-panel{" in css
    assert "animation" not in css.split(".roster-panel{")[1].split(".activity-heading{")[0]

    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="agentRoster"' in page.text
        assert "No mission loaded." in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function agentRosterView" in state.text
