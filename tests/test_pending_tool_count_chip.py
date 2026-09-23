"""Read-only Mission Control chip for pending / in-flight tool calls."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "pending_tool_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the pending-tool chip harness")
    result = subprocess.run(
        ["node", str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["unavailable"] == UNAVAILABLE
    return payload["cases"]


@pytest.fixture(scope="module")
def cases() -> dict:
    return _load_cases()


def test_hidden_without_a_visible_mission(cases):
    for key in ("hidden", "hiddenDefault"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloaded", "unloadedMissingFlag"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE
        assert view["label"] != "0"
        assert view["label"] != "4"


def test_explicit_empty_feed_is_known_zero(cases):
    for key in ("empty", "beforeAny", "matchedComplete", "matchedFailed", "closedThenPrestart", "ignoresNonTool"):
        view = cases[key]
        assert view == {"hidden": False, "known": True, "count": 0, "label": "0"}


def test_open_starts_count_without_using_payload_used_as_the_total(cases):
    assert cases["oneOpen"] == {"hidden": False, "known": True, "count": 1, "label": "1"}
    assert cases["twoOpen"]["count"] == 2
    assert cases["twoOpen"]["label"] == "2"
    assert cases["prestartIgnored"]["count"] == 1
    assert cases["otherToolDoesNotClose"]["count"] == 1
    assert cases["holes"]["label"] == "1"
    assert "9" not in cases["oneOpen"]["label"]


def test_replay_prefix_tracks_only_events_through_the_cursor(cases):
    assert cases["prefixOpen"]["count"] == 1
    assert cases["prefixClosed"]["count"] == 0
    assert cases["prefixMid"]["count"] == 1
    assert cases["prefixAll"]["count"] == 2


def test_unpairable_tool_events_fail_closed(cases):
    for key in ("orphanCompleted", "duplicateStart", "missingTool", "stringUsed"):
        view = cases[key]
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE


def test_chip_is_wired_to_the_objective_hud_only():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")

    assert 'id="pendingToolCountChip"' in html
    assert "hidden" in html.split('id="pendingToolCountChip"')[1].split(">")[0]
    assert html.index('id="pendingToolCountChip"') < html.index('id="hudElapsed"')
    assert "export function pendingToolCountView" in state
    assert "export function recordedPendingToolFeed" in state
    assert 'type === "tool.started"' in state
    view_body = state.split("export function pendingToolCountView")[1].split("export function applyEvent")[0]
    assert "return {hidden: false, known: true, count: open.size, label: String(open.size)}" in view_body
    assert "label: String(event.payload.used)" not in view_body
    assert "state.preview?null:recordedPendingToolFeed(eventLog,replayCursor,pendingToolFeedLoaded)" in control
    assert "pendingToolCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "pendingToolFeedLoaded=options.pendingToolFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "pendingToolFeedLoaded=true" in control
    assert ".hud-chip.pending-tools[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.pending-tools")[1].split(".hud-stats")[0]
    for banned in ("WorkQueue", "ProcessWorkerPool", "event-relay"):
        assert banned not in view_body
        assert banned not in control.split("pendingToolCountChip")[1].split("const running")[0]
