"""Read-only chronological event-count chip. Never invent a count."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "event_count_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS event-count harness")
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


def test_hidden_without_mission_or_preview(cases):
    for key in ("standby", "standbyMissing"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "missingString", "previewMissing"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE
        assert view["label"] != "0 events"


def test_explicit_empty_list_is_zero(cases):
    view = cases["explicitEmpty"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "0 events"
    preview = cases["previewExplicitEmpty"]
    assert preview["hidden"] is False
    assert preview["count"] == 0
    assert preview["label"] == "0 events"


def test_count_matches_recorded_chronological_feed(cases):
    assert cases["duplicateIgnored"] is False
    assert cases["recordedLength"] == 2
    view = cases["recorded"]
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["count"] == 2
    assert view["label"] == "2 events"
    one = cases["oneEvent"]
    assert one["count"] == 1
    assert one["label"] == "1 event"


def test_chip_is_wired_fail_closed():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="eventCountChip"' in html
    assert 'id="eventCountChip" class="hud-chip event-count" hidden' in html
    chip = html.split('id="eventCountChip"', 1)[1].split("</span>", 1)[0]
    assert "0 events" not in chip
    assert "unavailable" in chip
    assert "eventCountView(eventFeed" in control
    assert "eventFeed=null" in control
    assert "Array.isArray(events)" in control
    assert "}else eventFeed=null;" in control
    assert "}catch{eventFeed=null;}" in control
    assert "reset(m);eventFeed=eventLog;" in control
    fn = state.split("export function eventCountView", 1)[1].split("export function ", 1)[0]
    assert "|| []" not in fn
    assert "? []" not in fn
    assert "EVENT_COUNT_UNAVAILABLE" in fn
