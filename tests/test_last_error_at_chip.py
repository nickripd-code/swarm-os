"""Read-only Mission Control last-error timestamp chip. Never invents a time."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "last_error_at_cases.mjs"
UNAVAILABLE = "unavailable"
STAMP = "2026-09-23T11:56:00Z"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the last-error chip harness")
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
    assert view["kind"] is None
    assert view["at"] is None
    assert view["title"] == ""


def test_chip_stays_hidden_without_a_recorded_error_or_park(cases):
    for name in (
        "noMission", "preview", "running", "completed", "taskWait", "blocked",
        "clearedLlm", "createdIgnored", "replayBefore", "resumedPark",
    ):
        _hidden(cases[name])
        assert STAMP not in cases[name]["label"]
        assert "just now" not in cases[name]["label"]


def test_known_stamp_is_formatted_from_the_event_only(cases):
    assert cases["known"] == {
        "hidden": False,
        "label": "Error 4m ago",
        "known": True,
        "kind": "error",
        "at": STAMP,
        "title": STAMP,
    }
    assert cases["trimmed"] == cases["known"]
    assert cases["offset"]["label"] == "Error 4m ago"
    assert cases["offset"]["title"] == "2026-09-23T07:56:00-04:00"
    assert cases["offset"]["at"] == "2026-09-23T07:56:00-04:00"
    assert cases["llmFailed"]["label"] == "Error 4m ago"
    assert cases["newerWins"]["at"] == STAMP
    assert cases["newerWins"]["label"] == "Error 4m ago"
    assert cases["parkedQuestion"]["label"] == "Parked 4m ago"
    assert cases["parkedQuestion"]["kind"] == "parked"
    assert cases["parkedQuestion"]["at"] == STAMP
    assert cases["parkedApproval"]["label"] == "Parked 4m ago"
    assert cases["replayAtFailure"]["label"] == "Error 4m ago"
    assert cases["replayAtFailure"]["at"] == STAMP
    assert "08:00:00" not in cases["known"]["label"]
    assert cases["updated"] not in cases["known"]["label"]


def test_relative_buckets_never_say_just_now(cases):
    assert cases["seconds"]["label"] == "Error 59s ago"
    assert cases["justNow"]["label"] == "Error 0s ago"
    assert "just now" not in cases["justNow"]["label"]
    assert cases["hours"]["label"] == "Error 2h ago"
    assert cases["oneDay"]["label"] == "Error 1d ago"
    assert cases["micros"]["label"] == "Error 59s ago"
    assert cases["micros"]["title"] == "2026-09-23T11:59:00.123456Z"
    assert cases["skewOk"]["label"] == "Error 0s ago"
    assert cases["skewOk"]["at"] == STAMP
    assert cases["noClock"]["label"] == "Error " + STAMP
    assert cases["noClock"]["title"] == STAMP
    assert "ago" not in cases["noClock"]["label"]
    assert cases["badNow"]["label"] == "Error " + STAMP
    assert cases["zeroNow"]["label"] == "Error " + STAMP
    assert "1970" not in cases["zeroNow"]["label"]


def test_failed_or_parked_without_a_valid_stamp_is_unavailable(cases):
    for name in (
        "missingResult", "blank", "nullStamp", "numericZero", "epoch", "epochFraction",
        "garbage", "impossibleDay", "naive", "dateOnly", "parkedNoStamp", "parkedBlank",
        "skewHide", "updatedIgnored",
    ):
        view = cases[name]
        assert view["hidden"] is False, name
        assert view["label"] == UNAVAILABLE, name
        assert view["known"] is False, name
        assert view["at"] is None, name
        assert view["title"] == "", name
        assert "1970" not in view["label"]
        assert STAMP not in view["label"]
        assert "just now" not in view["label"]
        assert "0s" not in view["label"]


def test_markup_starts_hidden_and_does_not_invent_a_time():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="lastErrorAtChip" class="hud-chip error-at unavailable" hidden' in html
    assert "lastErrorAtChip(state,{now:Date.now()})" in control
    assert "export function lastErrorAtChip" in state
    assert "LAST_ERROR_AT_UNAVAILABLE = \"unavailable\"" in state
    assert "#lastErrorAtChip[hidden]{display:none}" in css
    assert ".hud-chip.error-at.unavailable" in css
    block = css.split(".hud-chip.error-at.unavailable")[1].split("}")[0]
    assert "animation" not in block
    start = html.index('id="lastErrorAtChip"')
    tag = html[html.rfind("<", 0, start):html.index(">", start) + 1]
    assert tag.startswith("<span ")
    assert "hidden" in tag
    assert ">" + STAMP not in html
    assert "just now" not in html.lower()
    render = control[control.index('if($("lastErrorAtChip"))'):control.index('if($("hudAgents"))')]
    assert "updated_at" not in render
    assert "created_at" not in render
    assert "just now" not in render


def test_static_last_error_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="lastErrorAtChip"' in page.text
        assert 'id="lastErrorAtChip" class="hud-chip error-at unavailable" hidden' in page.text
        module = client.get("/static/state.mjs")
        assert module.status_code == 200
        assert "export function lastErrorAtChip" in module.text
        js = client.get("/static/control.js")
        assert js.status_code == 200
        assert "lastErrorAtChip(state,{now:Date.now()})" in js.text
        styles = client.get("/static/control.css")
        assert styles.status_code == 200
        assert "#lastErrorAtChip[hidden]{display:none}" in styles.text
