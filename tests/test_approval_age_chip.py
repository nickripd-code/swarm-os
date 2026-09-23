"""Read-only Mission Control approval-age chip. No invented timestamps."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "approval_age_chip_cases.mjs"
UNAVAILABLE = "unavailable"
NONE = "none"
STAMP = "2026-09-23T08:00:00Z"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the approval-age chip harness")
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


def test_no_mission_or_preview_stays_hidden(cases):
    for name in ("idle", "noMission", "preview"):
        view = cases[name]
        assert view["hidden"] is True, name
        assert view["label"] == ""
        assert view["known"] is False
        assert view["at"] is None
        assert view["title"] == ""


def test_zero_pending_approvals_show_none_without_an_age(cases):
    for name in (
        "explicitNull",
        "humanQuestion",
        "answeredHistoryIsNotPending",
        "afterAnswer",
        "inFlightWait",
        "replayBefore",
    ):
        view = cases[name]
        assert view["hidden"] is False, name
        assert view["known"] is True, name
        assert view["label"] == NONE, name
        assert view["at"] is None, name
        assert view["title"] == "", name
        assert "ago" not in view["label"]
        assert "0s" not in view["label"]
        assert STAMP not in view["label"]


def test_recorded_approval_stamp_is_relative(cases):
    assert cases["known"] == {
        "hidden": False,
        "label": "4m ago",
        "known": True,
        "at": STAMP,
        "title": STAMP,
    }
    for name in ("offset", "payment", "secondApproval", "replayAt"):
        assert cases[name]["label"] == "4m ago", name
        assert cases[name]["known"] is True
        assert cases[name]["hidden"] is False
        assert "08:00:00" not in cases[name]["label"]
    assert cases["offset"]["at"] == "2026-09-23T09:00:00+01:00"
    assert cases["offset"]["title"] == "2026-09-23T09:00:00+01:00"
    for name in ("payment", "secondApproval", "replayAt"):
        assert cases[name]["at"] == STAMP, name
    assert cases["seconds"]["label"] == "59s ago"
    assert cases["justNow"]["label"] == "0s ago"
    assert "just now" not in cases["justNow"]["label"]
    assert cases["hours"]["label"] == "2h ago"
    assert cases["oneDay"]["label"] == "1d ago"
    assert cases["micros"]["label"] == "59s ago"
    assert cases["skewOk"]["label"] == "0s ago"
    assert cases["noClock"]["label"] == STAMP
    assert "ago" not in cases["noClock"]["label"]
    assert cases["badNow"]["label"] == STAMP
    assert cases["zeroNow"]["label"] == STAMP
    assert "1970" not in cases["zeroNow"]["label"]


def test_unreadable_approval_time_is_unavailable(cases):
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
        assert view["label"] != NONE
    for name in ("slotWithoutEvent", "payloadClockIgnored", "missionStartIgnored"):
        view = cases[name]
        assert view["label"] == UNAVAILABLE, name
        assert view["known"] is False
        assert view["at"] is None
        assert "ago" not in view["label"]


def test_chip_markup_is_hidden_until_a_real_stamp_exists():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert 'id="approvalAgeChip" class="hud-chip approval-age unavailable" hidden' in html
    assert "APPROVAL_AGE_UNAVAILABLE = \"unavailable\"" in state
    assert "APPROVAL_AGE_NONE = \"none\"" in state
    assert "export function approvalAgeChip" in state
    assert "approvalAgeChip" in control
    assert "just now" not in html.lower()
    assert "just now" not in state
    assert "just now" not in control
    assert ".hud-chip.approval-age.unavailable" in css
    block = css.split(".hud-chip.approval-age.unavailable")[1].split("}")[0]
    assert "animation" not in block
    body = state.split("export function approvalAgeChip", 1)[1].split("export function missionMode", 1)[0]
    assert "fetch(" not in body
    assert "mission.waiting" not in body


def test_static_approval_age_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="approvalAgeChip" class="hud-chip approval-age unavailable" hidden' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function approvalAgeChip" in state.text
