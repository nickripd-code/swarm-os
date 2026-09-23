"""Read-only Mission Control error/park snippet. Never invents a reason."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "error_park_snippet_cases.mjs"
INVENTED = (
    "Waiting for a human answer",
    "Waiting for in-flight work",
    "Required capability or information is unavailable",
    "Execution stopped",
    "Unknown error",
    "No recorded",
)


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the error/park snippet harness")
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
    assert view["visible"] is False
    assert view["kind"] is None
    assert view["label"] == ""
    assert view["text"] == ""
    assert view["failureClass"] is None


def test_no_mission_preview_and_other_statuses_stay_hidden(cases):
    for key in (
        "noMission", "noState", "previewFailed", "runningIgnoresError",
        "blockedHidden", "stoppedHidden", "completedHidden", "pausedHidden",
        "runningClearsPark", "inconsistentFailed", "inconsistentPark",
    ):
        _hidden(cases[key])
    assert "provider down" not in cases["previewFailed"]["text"]
    assert cases["runningClearsPark"]["text"] != "In-flight work finished; controller will continue"
    assert cases["inconsistentPark"]["text"] != "Finish requires human approval"


def test_loaded_failure_uses_recorded_class_and_error(cases):
    view = cases["loadedFailed"]
    assert view["visible"] is True
    assert view["kind"] == "failed"
    assert view["label"] == "FAILED"
    assert view["failureClass"] == "TIMEOUT"
    assert view["text"] == "TIMEOUT · Mission runtime limit reached"

    event = cases["failedEvent"]
    assert event["visible"] is True
    assert event["failureClass"] == "PROVIDER_OUTAGE"
    assert event["text"] == "PROVIDER_OUTAGE · provider down"
    assert cases["failedPayloadNotStaleResult"]["text"] == "PROVIDER_OUTAGE · provider down"
    assert "stale" not in cases["failedPayloadNotStaleResult"]["text"]


def test_partial_or_blank_failure_fields_do_not_invent_a_reason(cases):
    assert cases["classOnly"]["visible"] is True
    assert cases["classOnly"]["text"] == "POLICY_REFUSAL"
    assert cases["classOnly"]["failureClass"] == "POLICY_REFUSAL"
    assert cases["errorOnly"]["text"] == "Unexpected runtime error"
    assert cases["errorOnly"]["failureClass"] is None
    assert cases["reasonOnlyFailed"]["text"] == "Verification did not accept the claimed result"
    for key in ("blankFailed", "numericFailed", "summaryIsNotReason", "emptyFailedPayload"):
        _hidden(cases[key])
        assert cases[key]["text"] != "Looks done"
        assert "stale" not in cases[key]["text"]


def test_park_reason_comes_only_from_recorded_fields(cases):
    parked = cases["loadedPark"]
    assert parked["visible"] is True
    assert parked["kind"] == "parked"
    assert parked["label"] == "PARKED"
    assert parked["text"] == "Finish requires human approval"
    assert parked["failureClass"] is None
    assert "Approve finish?" not in parked["text"]
    assert "finish" not in parked["text"]

    waiting = cases["waitingEvent"]
    assert waiting["visible"] is True
    assert waiting["kind"] == "parked"
    assert waiting["text"] == "Waiting for in-flight work"

    recorded = cases["recordedFallbackIsShown"]
    assert recorded["text"] == "Waiting for a human answer"

    for key in (
        "questionWithoutReason", "missingParkReason", "whitespacePark",
        "blankWaiting", "questionClearsOlderPark",
    ):
        _hidden(cases[key])
    assert cases["questionWithoutReason"]["text"] != "Which region?"
    assert cases["missingParkReason"]["text"] != "Waiting for a human answer"
    assert cases["questionClearsOlderPark"]["text"] != "Waiting for in-flight work"


def test_snippet_source_has_no_fallback_reason():
    source = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    snippet = source.split("export function errorParkSnippet", 1)[1].split("export function alertFromEvent", 1)[0]
    for phrase in INVENTED:
        assert phrase not in snippet
    assert "export function errorParkSnippet" in source
    assert "errorParkSnippet" in control
    render = control.split("function renderErrorPark()", 1)[1].split("function clearAlerts()", 1)[0]
    assert "view.visible?view.text" in render
    assert 'textContent=view.visible?view.label:""' in render
    assert 'id="errorParkSnippet"' in html
    assert 'id="errorParkText"></span>' in html
    assert "error-park-snippet" in css
    block = css.split(".error-park-snippet{")[1].split(".hud-chips{")[0]
    assert "animation" not in block
    assert "@keyframes" not in block


def test_snippet_markup_is_hidden_and_empty():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    opening = html.index('id="errorParkSnippet"')
    tag_start = html.rfind("<p", 0, opening)
    tag_end = html.index(">", opening) + 1
    tag = html[tag_start:tag_end]
    section = html[tag_start:html.index('id="questionPanel"')]
    assert tag.endswith("hidden>")
    assert 'id="errorParkLabel"></span>' in section
    assert 'id="errorParkText"></span>' in section
    assert "Unknown" not in section
    assert "Waiting for" not in section


def test_static_error_park_snippet_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="errorParkSnippet"' in page.text
        assert 'id="errorParkText"></span>' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function errorParkSnippet" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".error-park-snippet" in css.text
