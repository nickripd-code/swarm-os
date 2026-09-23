"""Read-only Mission Control chip for the age of the newest recorded evidence event."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "evidence_age_cases.mjs"
UNAVAILABLE = "EVIDENCE AGE unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the evidence-age chip harness")
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
    assert view["hidden"] is True
    assert view["label"] == ""
    assert view["known"] is False
    assert view["at"] is None
    assert view["title"] == ""


def _unavailable(view: dict) -> None:
    assert view["hidden"] is False
    assert view["label"] == UNAVAILABLE
    assert view["known"] is False
    assert view["at"] is None
    assert view["title"] == ""
    assert "ago" not in view["label"]
    assert "just now" not in view["label"]
    assert "1970" not in view["label"]
    assert "$" not in view["label"]


def _aged(view: dict, label: str, stamp: str) -> None:
    assert view["hidden"] is False
    assert view["known"] is True
    assert view["label"] == label
    assert view["at"] == stamp
    assert view["title"] == stamp
    assert "$" not in view["label"]
    assert "just now" not in view["label"]
    assert "1970" not in view["label"]


def test_chip_stays_hidden_without_a_mission_or_in_preview(cases):
    _hidden(cases["noMission"])
    _hidden(cases["preview"])


def test_missing_feed_says_evidence_age_unavailable(cases):
    for name in ("missingNull", "missingUndefined", "missingObject", "feedNotLoaded"):
        _unavailable(cases[name])
    assert cases["unavailable"] == UNAVAILABLE


def test_loaded_feed_without_an_evidence_event_stays_hidden(cases):
    for name in ("empty", "cursorBefore", "nonEvidence", "nonObject", "verdictIgnored"):
        _hidden(cases[name])
    assert "$" not in cases["nonEvidence"]["label"]
    assert "1.25" not in cases["nonEvidence"]["label"]
    assert "started" not in cases["verdictIgnored"]["label"]


@pytest.mark.parametrize(
    "name",
    [
        "missingTime",
        "blankTime",
        "whitespace",
        "numericZero",
        "numericNow",
        "stringZero",
        "epoch",
        "epochFraction",
        "naive",
        "garbage",
        "impossibleDay",
        "newestInvalid",
        "future",
    ],
)
def test_an_evidence_event_without_a_readable_stamp_is_unavailable(cases, name):
    _unavailable(cases[name])


def test_chip_shows_the_newest_evidence_event_age(cases):
    _aged(cases["clock"], "Evidence 3m ago", "2026-09-23T12:35:04.123456Z")
    _aged(cases["offset"], "Evidence 4m ago", "2026-09-23T08:35:04-04:00")
    _aged(cases["newestByTime"], "Evidence 4m ago", "2026-09-23T12:35:04Z")
    _aged(cases["kinds"], "Evidence 4m ago", "2026-09-23T12:35:04Z")
    _aged(cases["verdictDoesNotOverride"], "Evidence 4m ago", "2026-09-23T12:35:04Z")
    _aged(cases["replayPrefix"], "Evidence 4m ago", "2026-09-23T12:35:04Z")
    _aged(cases["replayAtLater"], "Evidence 3m ago", "2026-09-23T12:36:00Z")
    _aged(cases["seconds"], "Evidence 59s ago", "2026-09-23T12:38:05Z")
    _aged(cases["justNow"], "Evidence 0s ago", "2026-09-23T12:39:04Z")
    _aged(cases["hours"], "Evidence 2h ago", "2026-09-23T10:39:04Z")
    _aged(cases["oneDay"], "Evidence 1d ago", "2026-09-22T12:39:04Z")
    _aged(cases["micros"], "Evidence 59s ago", "2026-09-23T12:38:04.100000Z")
    _aged(cases["skewOk"], "Evidence 0s ago", "2026-09-23T12:39:34Z")
    _aged(cases["noClock"], "Evidence 2026-09-23T12:35:04Z", "2026-09-23T12:35:04Z")
    _aged(cases["badNow"], "Evidence 2026-09-23T12:35:04Z", "2026-09-23T12:35:04Z")
    _aged(cases["zeroNow"], "Evidence 2026-09-23T12:35:04Z", "2026-09-23T12:35:04Z")
    assert "ago" not in cases["noClock"]["label"]
    spend = cases["spendIgnored"]
    _aged(spend, "Evidence 4m ago", "2026-09-23T12:35:04Z")
    assert "100" not in spend["label"]
    assert "9" not in spend["label"]


def test_shell_mounts_a_hidden_evidence_age_chip_on_the_objective_hud():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    start = html.index('id="evidenceAgeChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert "hud-chip" in tag
    assert tag.endswith("hidden>")
    assert html[html.index(">", start) + 1:].startswith("</span>")
    assert html.index('id="objectiveHud"') < start < html.index('id="hudElapsed"')
    assert '.hud-chip.evidence-age[data-known="false"]' in css
    assert "animation" not in css.split(".hud-chip.evidence-age")[1].split("}")[0]
    assert "export function evidenceAgeChip" in state
    assert "export function recordedEvidenceAgeFeed" in state
    assert 'EVIDENCE_AGE_UNAVAILABLE = "EVIDENCE AGE unavailable"' in state
    assert '"verification.evidence.started"' in state
    assert '"verification.evidence.passed"' in state
    assert '"verification.evidence.failed"' in state
    render = control[control.index('const evidenceAgeEl=$("evidenceAgeChip")'):control.index("const running=")]
    assert "recordedEvidenceAgeFeed(eventLog,replayCursor,evidenceAgeFeedLoaded)" in render
    assert "evidenceAgeChip(feed,{visible:!!(state.mission&&!state.preview),now:Date.now()})" in render
    assert "created_at" not in render
    assert "updated_at" not in render
    assert "token_spent" not in render
    assert "evidenceAgeFeedLoaded=options.evidenceAgeFeedLoaded===true" in control
    assert "evidenceAgeFeedLoaded=true" in control
