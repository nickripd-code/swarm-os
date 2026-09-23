"""Read-only Mission Control question-age chip. No invented timestamps."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "question_age_chip_cases.mjs"
UNAVAILABLE = "unavailable"
STAMP = "2026-09-23T08:00:00Z"
OLDER = "2026-09-23T07:00:00Z"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the question-age chip harness")
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


def _assert_hidden(view: dict, name: str) -> None:
    assert view["hidden"] is True, name
    assert view["label"] == "", name
    assert view["known"] is False, name
    assert view["at"] is None, name
    assert view["title"] == "", name


def test_no_mission_preview_or_no_pending_stays_hidden(cases):
    for name in (
        "idle",
        "noMission",
        "preview",
        "previewOption",
        "explicitNone",
        "missingKey",
        "agentMessageIgnored",
        "replayBefore",
        "replayAnswered",
    ):
        _assert_hidden(cases[name], name)
    for name, view in cases["controlsIgnored"].items():
        _assert_hidden(view, name)


def test_recorded_question_stamp_is_relative(cases):
    assert cases["known"] == {
        "hidden": False,
        "label": "Asked 4m ago",
        "known": True,
        "at": STAMP,
        "title": STAMP,
    }
    for name in ("approval", "otherIdIgnored", "replayAt", "newestPending"):
        assert cases[name]["label"] == "Asked 4m ago", name
        assert cases[name]["known"] is True
        assert cases[name]["hidden"] is False
        assert cases[name]["at"] == STAMP
        assert "07:00:00" not in cases[name]["label"]
    assert cases["offset"]["label"] == "Asked 4m ago"
    assert cases["offset"]["at"] == "2026-09-23T09:00:00+01:00"
    assert cases["oldestWins"]["label"] == "Asked 1h ago"
    assert cases["oldestWins"]["at"] == OLDER
    assert cases["seconds"]["label"] == "Asked 59s ago"
    assert cases["justNow"]["label"] == "Asked 0s ago"
    assert "just now" not in cases["justNow"]["label"]
    assert cases["hours"]["label"] == "Asked 2h ago"
    assert cases["oneDay"]["label"] == "Asked 1d ago"
    assert cases["micros"]["label"] == "Asked 59s ago"
    assert cases["skewOk"]["label"] == "Asked 0s ago"
    assert cases["noClock"]["label"] == "Asked " + STAMP
    assert "ago" not in cases["noClock"]["label"]
    assert cases["badNow"]["label"] == "Asked " + STAMP
    assert cases["zeroNow"]["label"] == "Asked " + STAMP
    assert "1970" not in cases["zeroNow"]["label"]


def test_blank_or_invalid_question_time_is_unavailable(cases):
    for name, view in cases["bad"].items():
        assert view["hidden"] is False, name
        assert view["known"] is False, name
        assert view["label"] == UNAVAILABLE, name
        assert view["at"] is None
        assert view["title"] == ""
        assert "1970" not in view["label"]
        assert STAMP not in view["label"]
        assert "just now" not in view["label"]
        assert "0s" not in view["label"]
        assert "ago" not in view["label"]
    assert cases["waitingIsNotAsk"]["label"] == UNAVAILABLE
    assert cases["waitingIsNotAsk"]["known"] is False


def test_chip_markup_is_hidden_until_a_real_pending_question_exists():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert 'id="questionAgeChip" class="hud-chip question-age unavailable" hidden' in html
    assert "QUESTION_AGE_UNAVAILABLE = \"unavailable\"" in state
    assert "export function questionAgeChip" in state
    assert 'event.event_type !== "mission.question"' in state
    assert "questionAgeChip" in control
    assert "just now" not in html.lower()
    assert "just now" not in state
    assert "just now" not in control
    assert ".hud-chip.question-age.unavailable" in css
    block = css.split(".hud-chip.question-age.unavailable")[1].split("}")[0]
    assert "animation" not in block


def test_static_question_age_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="questionAgeChip" class="hud-chip question-age unavailable" hidden' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function questionAgeChip" in state.text
