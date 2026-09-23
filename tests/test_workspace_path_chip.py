"""Mission Control workspace path chip: reported root only, never invented."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "workspace_path_chip_cases.mjs"
REPORTED = "/var/lib/swarm/workspaces/sandbox-root"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the workspace path chip harness")
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
    assert view["path"] is None
    assert view["label"] == ""


def test_no_mission_preview_or_missing_path_stays_hidden(cases):
    for name in (
        "noMission",
        "preview",
        "previewMission",
        "missingHealth",
        "emptyHealth",
        "blankRoot",
        "numericRoot",
        "detailOnly",
        "controlChar",
    ):
        _hidden(cases[name])
        assert REPORTED not in json.dumps(cases[name])


def test_short_reported_root_is_shown_unchanged(cases):
    view = cases["shortRoot"]
    assert view["visible"] is True
    assert view["path"] == "/tmp/swarm-workspaces"
    assert view["label"] == "/tmp/swarm-workspaces"


def test_long_root_is_shortened_from_the_reported_path(cases):
    view = cases["longRoot"]
    assert view["visible"] is True
    assert view["path"] == REPORTED
    assert view["label"].startswith("…")
    assert view["label"] != view["path"]
    assert len(view["label"]) <= 24
    assert REPORTED.endswith(view["label"][1:])
    assert cases["shortenLimit"] == view["label"]


def test_windows_root_keeps_a_real_suffix(cases):
    view = cases["windowsRoot"]
    full = "C:\\Users\\dev\\AppData\\Local\\Temp\\swarm-workspaces"
    assert view["path"] == full
    assert view["label"].startswith("…")
    assert len(view["label"]) <= 24
    assert full.endswith(view["label"][1:])


def test_surrounding_whitespace_is_trimmed_not_replaced(cases):
    view = cases["whitespacePad"]
    assert view["path"] == "/opt/swarm"
    assert view["label"] == "/opt/swarm"


def test_chip_source_does_not_invent_a_workspace_path():
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    start = state.index("function reportedWorkspaceRoot")
    end = state.index("export function resultMetaText")
    chip = state[start:end]
    assert "tempfile" not in chip
    assert "swarm-workspaces" not in chip
    assert "workspacePathChip" in control
    assert "health?health.workspace:null" in control
    assert 'id="workspacePathChip"' in html
    assert "hidden" in html.split('id="workspacePathChip"')[1].split(">")[0]
    assert ".hud-chip.workspace-path{" in css
    phone = css.split("@media(max-width:620px)")[1]
    assert ".hud-chip.workspace-path{display:block;max-width:min(100%,16ch)}" in phone
