"""Read-only Mission Control lease-released count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "lease_released_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the lease-released chip harness")
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


def test_chip_stays_hidden_without_a_loaded_mission_or_in_preview(cases):
    for key in ("hidden", "hiddenDefault", "preview"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == ""


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == "LEASE RELEASES " + UNAVAILABLE
        assert view["label"] != "LEASE RELEASES 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "LEASE RELEASES 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "LEASE RELEASES 0"


def test_counts_lease_released_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "LEASE RELEASES 3"
    assert "$" not in view["label"]
    assert "token" not in view["label"].lower()
    assert cases["ignoresClaimed"]["count"] == 0
    assert cases["ignoresExpired"]["count"] == 0
    assert cases["ignoresJob"]["count"] == 0
    assert cases["ignoresTool"]["count"] == 0
    assert cases["ignoresBudget"]["count"] == 0
    assert cases["oneReleaseNotPayload"]["count"] == 1
    assert cases["oneReleaseNotPayload"]["label"] == "LEASE RELEASES 1"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    unreadable = cases["unreadableType"]
    assert unreadable["known"] is False
    assert unreadable["count"] is None
    assert unreadable["label"] == "LEASE RELEASES " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_releases(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefix"]["count"] == 1
    assert cases["prefixOne"]["count"] == 2
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function leaseReleasedCountView" in state
    assert "export function recordedLeaseReleasedCountFeed" in state
    assert 'const LEASE_RELEASED_COUNT_EVENT = "lease.released"' in state
    view_body = state.split("export function leaseReleasedCountView")[1].split("export function applyEvent")[0]
    assert "LEASE_RELEASED_COUNT_EVENT" in view_body
    assert "lease.claimed" not in view_body
    assert "lease.expired" not in view_body
    assert "job.enqueued" not in view_body
    assert "tool.started" not in view_body
    assert "token_spent" not in view_body
    assert "payload.releases" not in view_body
    assert "state.preview?null:recordedLeaseReleasedCountFeed(eventLog,replayCursor,leaseReleasedFeedLoaded)" in control
    assert "leaseReleasedCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "leaseReleasedFeedLoaded=options.leaseReleasedFeedLoaded===true" in control
    assert "leaseChip.textContent=leaseView.hidden?\"\":leaseView.label" in control
    assert "if(Array.isArray(events))" in control
    assert "leaseReleasedFeedLoaded=true" in control
    assert 'id="leaseReleasedCountChip"' in html
    chip = html.split('id="leaseReleasedCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    css_rule = css.split(".hud-chip.lease-released")[1].split(".hud-stats")[0]
    assert '.hud-chip.lease-released[data-known="false"]' in css
    assert "animation" not in css_rule


def test_static_lease_released_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="leaseReleasedCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function leaseReleasedCountView" in state.text
