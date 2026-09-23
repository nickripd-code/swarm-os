"""Read-only mission status badge strip: mirror MissionStatus, never invent one."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import MissionStatus

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "status_badge_cases.mjs"
UNAVAILABLE = "unavailable"
CANONICAL = (
    "pending",
    "running",
    "waiting",
    "paused",
    "blocked",
    "completed",
    "failed",
    "stopped",
)


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the status badge harness")
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


def test_labels_match_api_mission_status_enum(cases):
    assert tuple(cases["order"]) == CANONICAL
    assert tuple(status.value for status in MissionStatus) == CANONICAL
    assert cases["labels"] == {
        "pending": "Pending",
        "running": "Running",
        "waiting": "Waiting",
        "paused": "Paused",
        "blocked": "Blocked",
        "completed": "Completed",
        "failed": "Failed",
        "stopped": "Stopped",
    }
    assert "Thinking" not in cases["labels"].values()
    assert "Queued" not in cases["labels"].values()
    assert "Idle" not in cases["labels"].values()


def _assert_unavailable(view: dict):
    assert view["visible"] is False
    assert view["status"] is None
    assert view["label"] is None
    assert view["badges"] == []
    assert view["reason"] == UNAVAILABLE


def test_empty_mission_hides_the_strip(cases):
    _assert_unavailable(cases["empty"])
    _assert_unavailable(cases["missing"])
    _assert_unavailable(cases["blank"])
    _assert_unavailable(cases["nonString"])


def test_unknown_status_is_not_invented(cases):
    _assert_unavailable(cases["idle"])
    _assert_unavailable(cases["unknown"])
    _assert_unavailable(cases["invented"])
    _assert_unavailable(cases["cased"])


def test_preview_does_not_claim_a_loaded_status(cases):
    _assert_unavailable(cases["previewFlag"])
    _assert_unavailable(cases["previewId"])


@pytest.mark.parametrize("status", CANONICAL)
def test_loaded_status_marks_only_that_badge(cases, status):
    view = cases["known"][status]
    assert view["visible"] is True
    assert view["status"] == status
    assert view["label"] == cases["labels"][status]
    assert view["reason"] is None
    assert [badge["status"] for badge in view["badges"]] == list(CANONICAL)
    current = [badge for badge in view["badges"] if badge["current"]]
    assert len(current) == 1
    assert current[0]["status"] == status
    assert current[0]["label"] == cases["labels"][status]
    assert all(badge["label"] == cases["labels"][badge["status"]] for badge in view["badges"])


def test_shell_mounts_a_hidden_read_only_strip():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    assert 'id="statusBadgeStrip" class="status-badge-strip" hidden' in html
    assert ".status-badge-strip[hidden]{display:none}" in css
    assert "missionStatusBadgeStrip" in control
    assert "statusStrip.hidden=!statusBadges.visible" in control
    assert "el.textContent=badge.label" in control
