"""Read-only Mission Control org-changed count chip. Never invents a count or spend."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "org_changed_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the org-changed chip harness")
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


def _hidden_unknown(view: dict) -> None:
    assert view["hidden"] is True
    assert view["known"] is False
    assert view["count"] is None
    assert view["label"] == ""


def _hidden_zero(view: dict) -> None:
    assert view["hidden"] is True
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == ""
    assert view["label"] != "ORG CHANGED 0"


def test_chip_stays_hidden_without_a_loaded_mission_or_in_preview(cases):
    for key in ("hidden", "hiddenDefault", "preview"):
        _hidden_unknown(cases[key])


def test_missing_feed_is_unavailable_not_zero(cases):
    for key in ("missingNull", "missingUndefined", "missingObject", "unloadedView"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == "ORG CHANGED " + UNAVAILABLE
        assert view["label"] != "ORG CHANGED 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None
    assert cases["unavailable"] == UNAVAILABLE


def test_explicit_empty_list_stays_hidden(cases):
    _hidden_zero(cases["empty"])
    assert cases["explicitEmptyFeed"] == []
    _hidden_zero(cases["beforeAny"])


def test_counts_org_changed_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["hidden"] is False
    assert view["count"] == 3
    assert view["label"] == "ORG CHANGED 3"
    assert "$" not in view["label"]
    assert "token" not in view["label"].lower()
    for key in (
        "ignoresSpawned",
        "ignoresUpdated",
        "ignoresReparented",
        "ignoresRetired",
        "ignoresKilled",
        "ignoresToolFailed",
        "ignoresBudget",
    ):
        _hidden_zero(cases[key])
    assert cases["oneChangeNotPayload"]["count"] == 1
    assert cases["oneChangeNotPayload"]["label"] == "ORG CHANGED 1"
    assert cases["skipsHoles"]["count"] == 1
    assert cases["missingType"]["count"] == 1
    unreadable = cases["unreadableType"]
    assert unreadable["known"] is False
    assert unreadable["count"] is None
    assert unreadable["label"] == "ORG CHANGED " + UNAVAILABLE


def test_replay_prefix_does_not_include_later_org_changes(cases):
    _hidden_zero(cases["prefixFirst"])
    assert cases["prefix"]["count"] == 1
    assert cases["prefix"]["label"] == "ORG CHANGED 1"
    assert cases["prefixOne"]["count"] == 2
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function orgChangedCountView" in state
    assert "export function recordedOrgChangedCountFeed" in state
    assert 'const ORG_CHANGED_COUNT_EVENT = "org.changed"' in state
    view_body = state.split("export function orgChangedCountView")[1].split("export function applyEvent")[0]
    assert "ORG_CHANGED_COUNT_EVENT" in view_body
    assert "if (count === 0)" in view_body
    assert "agent.spawned" not in view_body
    assert "agent.updated" not in view_body
    assert "agent.reparented" not in view_body
    assert "agent.retired" not in view_body
    assert "agent.killed" not in view_body
    assert "tool.failed" not in view_body
    assert "token_spent" not in view_body
    assert "payload.count" not in view_body
    assert "state.preview?null:recordedOrgChangedCountFeed(eventLog,replayCursor,orgChangedCountFeedLoaded)" in control
    assert "orgChangedCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "orgChangedCountFeedLoaded=options.orgChangedCountFeedLoaded===true" in control
    assert 'orgChangedChip.textContent=orgChangedView.hidden?"":orgChangedView.label' in control
    assert "if(Array.isArray(events))" in control
    assert "orgChangedCountFeedLoaded=true" in control
    assert 'id="orgChangedCountChip"' in html
    chip = html.split('id="orgChangedCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert "0" not in chip
    css_rule = css.split(".hud-chip.org-changed")[1].split(".hud-stats")[0]
    assert '.hud-chip.org-changed[data-known="false"]' in css
    assert "animation" not in css_rule


def test_static_org_changed_count_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="orgChangedCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function orgChangedCountView" in state.text
