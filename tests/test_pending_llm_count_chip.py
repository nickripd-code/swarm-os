"""Read-only Mission Control chip for pending / in-flight model calls."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "pending_llm_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the pending-LLM chip harness")
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
        assert view["label"] != "12"
        assert view["label"] != "4"


def test_explicit_empty_feed_is_known_zero(cases):
    for key in ("empty", "beforeAny", "matchedComplete", "matchedFailed", "retryThenComplete", "ignoresNonLlm", "noModelEvents"):
        view = cases[key]
        assert view == {"hidden": False, "known": True, "count": 0, "label": "0"}


def test_open_starts_count_without_using_token_usage_as_the_total(cases):
    assert cases["oneOpen"] == {"hidden": False, "known": True, "count": 1, "label": "1"}
    assert cases["twoOpen"]["count"] == 2
    assert cases["twoOpen"]["label"] == "2"
    assert cases["retryKeepsOpen"]["count"] == 1
    assert cases["failoverKeepsOpen"]["count"] == 1
    assert cases["sameActorStack"]["count"] == 1
    assert cases["duplicateId"]["count"] == 1
    assert cases["holes"]["label"] == "1"
    assert cases["matchedComplete"]["label"] == "0"
    assert "900" not in cases["matchedComplete"]["label"]
    assert "12" not in cases["oneOpen"]["label"]


def test_replay_prefix_tracks_only_events_through_the_cursor(cases):
    assert cases["prefixOpen"]["count"] == 1
    assert cases["prefixClosed"]["count"] == 0
    assert cases["prefixMid"]["count"] == 1
    assert cases["prefixRetry"]["count"] == 1
    assert cases["prefixAll"]["count"] == 2


def test_unpairable_llm_events_fail_closed(cases):
    for key in (
        "orphanCompleted", "orphanFailed", "orphanRetry", "missingKind",
        "missingActor", "emptyKind", "missingId", "otherKindDoesNotClose",
        "otherActorDoesNotClose",
    ):
        view = cases[key]
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == UNAVAILABLE


def test_chip_is_wired_to_the_objective_hud_only():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")

    assert 'id="pendingLlmCountChip"' in html
    assert "hidden" in html.split('id="pendingLlmCountChip"')[1].split(">")[0]
    assert html.index('id="pendingLlmCountChip"') < html.index('id="hudElapsed"')
    assert "export function pendingLlmCountView" in state
    assert "export function recordedPendingLlmFeed" in state
    assert 'type === "llm.started"' in state
    view_body = state.split("export function pendingLlmCountView")[1].split("export function applyEvent")[0]
    assert "return {hidden: false, known: true, count, label: String(count)}" in view_body
    assert "label: String(event.payload.input_tokens)" not in view_body
    assert "input_tokens" not in view_body
    assert "token_spent" not in view_body
    assert "state.preview?null:recordedPendingLlmFeed(eventLog,replayCursor,pendingLlmFeedLoaded)" in control
    assert "pendingLlmCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "pendingLlmFeedLoaded=options.pendingLlmFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "pendingLlmFeedLoaded=true" in control
    assert ".hud-chip.pending-llm[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.pending-llm")[1].split(".hud-stats")[0]
    for banned in ("WorkQueue", "ProcessWorkerPool", "event-relay"):
        assert banned not in view_body
        assert banned not in control.split("pendingLlmCountChip")[1].split("const running")[0]
