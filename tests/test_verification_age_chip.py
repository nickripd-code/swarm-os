"""Read-only Mission Control verification-age chip. No invented timestamps."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "verification_age_cases.mjs"
UNAVAILABLE = "unavailable"
STAMP = "2026-09-23T08:00:00Z"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the verification-age chip harness")
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


def test_no_mission_preview_or_unknown_stamp_stays_hidden(cases):
    for name in ("idle", "noMission", "preview", "llmStartedIgnored", "replayBefore"):
        view = cases[name]
        assert view["hidden"] is True, name
        assert view["label"] == ""
        assert view["known"] is False
        assert view["at"] is None
        assert view["title"] == ""


def test_recorded_verification_stamp_is_relative(cases):
    assert cases["known"] == {
        "hidden": False,
        "label": "Verified 4m ago",
        "known": True,
        "at": STAMP,
        "title": STAMP,
    }
    for name in ("offset", "evidence", "started", "newerWins", "evidenceNewer", "replayAt"):
        assert cases[name]["label"] == "Verified 4m ago", name
        assert cases[name]["known"] is True
        assert cases[name]["hidden"] is False
        assert "08:00:00" not in cases[name]["label"]
    assert cases["seconds"]["label"] == "Verified 59s ago"
    assert cases["justNow"]["label"] == "Verified 0s ago"
    assert "just now" not in cases["justNow"]["label"]
    assert cases["hours"]["label"] == "Verified 2h ago"
    assert cases["oneDay"]["label"] == "Verified 1d ago"
    assert cases["micros"]["label"] == "Verified 59s ago"
    assert cases["skewOk"]["label"] == "Verified 0s ago"
    assert cases["noClock"]["label"] == "Verified " + STAMP
    assert "ago" not in cases["noClock"]["label"]
    assert cases["badNow"]["label"] == "Verified " + STAMP
    assert cases["zeroNow"]["label"] == "Verified " + STAMP
    assert "1970" not in cases["zeroNow"]["label"]


def test_blank_or_invalid_verification_time_is_unavailable(cases):
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


def test_chip_markup_is_hidden_until_a_real_stamp_exists():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert 'id="verificationAgeChip" class="hud-chip verify-age unavailable" hidden' in html
    assert "VERIFICATION_AGE_UNAVAILABLE = \"unavailable\"" in state
    assert "export function verificationAgeChip" in state
    assert "verificationAgeChip" in control
    assert "just now" not in html.lower()
    assert "just now" not in state
    assert "just now" not in control
    assert ".hud-chip.verify-age.unavailable" in css
    block = css.split(".hud-chip.verify-age.unavailable")[1].split("}")[0]
    assert "animation" not in block


def test_static_verification_age_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="verificationAgeChip" class="hud-chip verify-age unavailable" hidden' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function verificationAgeChip" in state.text
