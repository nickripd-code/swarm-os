"""Read-only Mission Control shell mode chip: live, replay, or preview — never invented."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "shell_mode_cases.mjs"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS shell-mode harness")
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


def test_mode_is_unavailable_until_preview_or_a_real_mission(cases):
    assert cases["unavailable"] == "unavailable"
    for key in ("standby", "missingLog", "blankId", "strayLog"):
        view = cases[key]
        assert view["known"] is False
        assert view["mode"] is None
        assert view["label"] == "unavailable"
        assert view["hidden"] is False


def test_provider_mode_is_not_treated_as_shell_mode(cases):
    view = cases["providerModeIgnored"]
    assert view == {"known": True, "mode": "replay", "label": "REPLAY", "hidden": False}


def test_recorded_cursor_selects_live_or_replay(cases):
    assert cases["emptyLive"]["label"] == "LIVE"
    assert cases["emptyLive"]["mode"] == "live"
    assert cases["scrubbed"] == {"known": True, "mode": "replay", "label": "REPLAY", "hidden": False}
    assert cases["liveEnd"]["label"] == "LIVE"
    assert cases["replayAgrees"] == "REPLAY"


def test_preview_flag_wins_and_does_not_require_a_log(cases):
    assert cases["preview"] == {"known": True, "mode": "preview", "label": "PREVIEW", "hidden": False}
    assert cases["previewWithoutMission"]["label"] == "PREVIEW"
    assert cases["previewWithoutMission"]["mode"] == "preview"


def test_chip_markup_is_read_only_and_starts_unavailable():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert '<span id="shellModeChip" class="hud-chip mode unavailable">unavailable</span>' in html
    assert "<button" not in html.split('id="shellModeChip"')[1].split("</span>")[0]
    assert "shellModeView" in state
    assert "SHELL_MODE_UNAVAILABLE" in state
    assert "shellModeView(" in control
    chip_render = control.split('if($("shellModeChip"))')[1].split("const running")[0]
    assert "onclick" not in chip_render
    assert "shell.label" in chip_render
    assert "LIVE" not in chip_render
    assert "PREVIEW" not in chip_render
    assert "REPLAY" not in chip_render
