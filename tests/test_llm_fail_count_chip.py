"""Read-only Mission Control LLM-fail count chip. Never invents a count."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "llm_fail_count_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the LLM-fail chip harness")
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
        assert view["label"] == "LLM FAILS " + UNAVAILABLE
        assert view["label"] != "LLM FAILS 0"
    assert cases["unloaded"] is None
    assert cases["notArrayLog"] is None


def test_explicit_empty_list_is_zero(cases):
    view = cases["empty"]
    assert view["known"] is True
    assert view["count"] == 0
    assert view["label"] == "LLM FAILS 0"
    assert cases["explicitEmptyFeed"] == []
    before = cases["beforeAny"]
    assert before["known"] is True
    assert before["count"] == 0
    assert before["label"] == "LLM FAILS 0"


def test_counts_llm_failed_only(cases):
    view = cases["counted"]
    assert view["known"] is True
    assert view["count"] == 3
    assert view["label"] == "LLM FAILS 3"
    assert cases["ignoresStarted"]["count"] == 0
    assert cases["ignoresCompleted"]["count"] == 0
    assert cases["ignoresRetry"]["count"] == 0
    assert cases["ignoresFailover"]["count"] == 0
    assert cases["ignoresMissionFailed"]["count"] == 0
    assert cases["skipsHoles"]["count"] == 1


def test_replay_prefix_does_not_include_later_llm_failures(cases):
    assert cases["prefixFirst"]["count"] == 0
    assert cases["prefix"]["count"] == 1
    assert cases["prefixAll"]["count"] == 3


def test_chip_is_wired_to_the_loaded_event_feed():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    assert "export function llmFailCountView" in state
    assert "export function recordedLlmFailFeed" in state
    assert 'event_type === "llm.failed"' in state
    view_body = state.split("export function llmFailCountView")[1].split("export function applyEvent")[0]
    assert "llm.started" not in view_body
    assert "llm.completed" not in view_body
    assert "llm.retry" not in view_body
    assert "payload.failed" not in view_body
    assert "state.preview?null:recordedLlmFailFeed(eventLog,replayCursor,llmFailFeedLoaded)" in control
    assert "llmFailCountView(feed,{visible:!!(state.mission&&!state.preview)})" in control
    assert "llmFailFeedLoaded=options.llmFailFeedLoaded===true" in control
    assert "if(Array.isArray(events))" in control
    assert "llmFailFeedLoaded=true" in control
    assert 'id="llmFailCountChip"' in html
    chip = html.split('id="llmFailCountChip"')[1].split(">")[0]
    assert "hidden" in chip
    assert "unavailable" not in chip
    assert ".hud-chip.llm-fails[data-known=\"false\"]" in css
    assert "animation" not in css.split(".hud-chip.llm-fails")[1].split(".hud-stats")[0]


def test_static_llm_fail_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="llmFailCountChip"' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function llmFailCountView" in state.text
