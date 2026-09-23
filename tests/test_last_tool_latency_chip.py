"""Read-only Mission Control chip for the newest finished tool-call duration."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_tool_latency_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the tool-latency chip harness")
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


def test_chip_mounts_hidden_with_an_empty_label():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    chip = '<span id="lastToolLatencyChip" class="hud-chip" hidden></span>'
    assert chip in html
    assert html.index('id="objectiveHud"') < html.index('id="lastToolLatencyChip"')
    assert html.index('id="lastToolLatencyChip"') < html.index('id="hudElapsed"')
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    assert "lastToolLatencyView" in control
    assert "renderLastToolLatencyChip" in control


def test_no_mission_or_preview_stays_hidden(cases):
    for name in ("noMission", "preview"):
        view = cases[name]
        assert view["hidden"] is True
        assert view["label"] == ""
        assert view["known"] is False
        assert view["ms"] is None


def test_missing_or_unfinished_feed_is_unavailable(cases):
    for name in (
        "missingFeed",
        "notAnArray",
        "emptyFeed",
        "replayBeforeAnyEvent",
        "noToolYet",
        "startedOnly",
        "catalogFieldIgnored",
    ):
        view = cases[name]
        assert view["hidden"] is False, name
        assert view["label"] == UNAVAILABLE, name
        assert view["known"] is False
        assert view["ms"] is None
        assert "0" not in view["label"]


def test_missing_blank_or_invalid_latency_is_unavailable(cases):
    for name in (
        "missingStamps",
        "blankLatency",
        "whitespaceLatency",
        "zeroLatency",
        "negativeLatency",
        "stringLatency",
        "nullLatency",
        "zeroSpan",
        "invalidDoesNotFallback",
        "otherActorIgnored",
        "otherToolIgnored",
        "otherUseIgnored",
    ):
        view = cases[name]
        assert view["label"] == UNAVAILABLE, name
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["ms"] is None
        assert view["label"] != "0ms"
        assert view["label"] != "0s"


def test_explicit_duration_uses_elapsed_chip_formatting(cases):
    assert cases["subSecond"]["label"] == "842ms"
    assert cases["subSecond"]["known"] is True
    assert cases["subSecond"]["ms"] == 842
    assert cases["oneSecond"]["label"] == "1s"
    assert cases["minutes"]["label"] == "1m 30s"
    assert cases["hours"]["label"] == "1h 2m"
    for name in ("subSecond", "oneSecond", "minutes", "hours"):
        assert cases[name]["hidden"] is False
        assert UNAVAILABLE not in cases[name]["label"]


def test_timestamp_span_is_used_only_when_no_explicit_field(cases):
    span = cases["timestampSpan"]
    assert span["known"] is True
    assert span["ms"] == 2500
    assert span["label"] == "2s"
    assert "9" not in span["label"]
    output = cases["outputIsNotLatency"]
    assert output["label"] == "4s"
    assert output["ms"] == 4000
    assert cases["explicitBeatsStamps"]["label"] == "842ms"
    assert cases["explicitBeatsStamps"]["ms"] == 842
    replay = cases["replayAtCompletion"]
    assert replay["label"] == "2s"
    assert replay["ms"] == 2500


def test_newest_finished_call_wins_and_ignores_a_later_start(cases):
    view = cases["newestWins"]
    assert view["known"] is True
    assert view["ms"] == 1800
    assert view["label"] == "1s"
    inflight = cases["inFlightAfterFinish"]
    assert inflight["known"] is True
    assert inflight["ms"] == 400
    assert inflight["label"] == "400ms"
