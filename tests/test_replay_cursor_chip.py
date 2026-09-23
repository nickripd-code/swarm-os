"""Read-only replay cursor chip: existing replayView index/total, or unavailable."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "replay_cursor_cases.mjs"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the replay cursor harness")
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


def test_mid_replay_shows_existing_position_label(cases):
    chip = cases["mid"]
    assert chip["visible"] is True
    assert chip["unavailable"] is False
    assert chip["label"] == cases["midPosition"] == "2 / 5"
    assert chip["index"] == 2
    assert chip["total"] == 5
    assert chip["ariaLabel"] == "Replay cursor 2 / 5"


def test_first_recorded_event_is_one_not_zero(cases):
    chip = cases["first"]
    assert chip["visible"] is True
    assert chip["label"] == "1 / 5"
    assert chip["index"] == 1


def test_hidden_when_live_preview_empty_or_no_mission(cases):
    for key in ("end", "empty", "noMission", "preview"):
        chip = cases[key]
        assert chip["visible"] is False
        assert chip["unavailable"] is False
        assert chip["label"] == ""
        assert chip["index"] is None


def test_unset_cursor_is_unavailable_and_does_not_invent_zero(cases):
    chip = cases["unset"]
    assert cases["unsetPosition"] == "0 / 5"
    assert chip["visible"] is True
    assert chip["unavailable"] is True
    assert chip["label"] == cases["unavailableText"] == "unavailable"
    assert chip["label"] != cases["unsetPosition"]
    assert chip["index"] is None
    assert chip["total"] is None


def test_inconsistent_cursor_fields_fail_closed(cases):
    for key in ("mismatch", "missingLabel", "fractional", "pastEnd", "stringCursor", "notLiveFlag"):
        chip = cases[key]
        assert chip["visible"] is True or key == "notLiveFlag"
        if key == "notLiveFlag":
            assert chip["visible"] is False
            assert chip["label"] == ""
            continue
        assert chip["unavailable"] is True
        assert chip["label"] == "unavailable"
        assert chip["index"] is None


def test_markup_chip_is_hidden_until_replay():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="replayCursorChip" class="hud-chip replay-cursor" hidden' in html
    assert "replayCursorChip" in control
    assert "export function replayCursorChip" in state
    assert "REPLAY_CURSOR_UNAVAILABLE" in state
    rule = css.split("#replayCursorChip")[1].split("}")[0]
    assert "animation" not in rule
