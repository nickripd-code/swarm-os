"""Mission Control evidence HUD: real verification.evidence.* events only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "evidence_hud_cases.mjs"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS evidence HUD harness")
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


def test_idle_hud_has_no_evidence(cases):
    view = cases["idle"]
    assert view["visible"] is False
    assert view["steps"] == []
    assert view["summary"] == "No evidence checks"


def test_unknown_event_types_stay_ignored(cases):
    assert cases["unknownType"]["skipped"] is None
    assert cases["unknownType"]["activity"] == ""
    assert cases["unknownType"]["verdictActivity"] == ""
    view = cases["unknownType"]["view"]
    assert view["visible"] is False
    assert view["steps"] == []


def test_started_lists_catalogued_kinds_without_a_pass(cases):
    view = cases["started"]["view"]
    assert view["visible"] is True
    assert view["summary"] == "Checking 2 checks · pytest, http"
    assert view["steps"] == [{
        "kind": "pytest, http",
        "status": "checking",
        "detail": "",
        "failure_class": "",
    }]
    assert "passed" not in view["summary"]
    assert "browser" not in view["summary"]
    assert cases["started"]["activity"] == "started · 2 checks · pytest, http"
    usage = cases["started"]["usage"]
    assert usage["known"] is False
    assert usage["cost"] is None
    assert usage["input"] == 0


def test_passed_step_shows_kind_without_inventing_spend(cases):
    view = cases["passed"]["view"]
    assert view["summary"] == "1 passed · 0 failed"
    assert view["steps"] == [{
        "kind": "pytest",
        "status": "passed",
        "detail": "",
        "failure_class": "",
    }]
    assert cases["passed"]["activity"] == "pytest passed"
    assert "12 passed" not in cases["passed"]["activity"]
    assert cases["passed"]["usage"]["known"] is False
    assert cases["passed"]["usage"]["cost"] is None
    assert "$" not in json.dumps(view)


def test_failed_step_shows_kind_and_short_error(cases):
    view = cases["failed"]["view"]
    step = view["steps"][0]
    assert step["kind"] == "http"
    assert step["status"] == "failed"
    assert step["failure_class"] == "VERIFICATION_FAILURE"
    assert "503" in step["detail"]
    assert "\n" not in step["detail"]
    assert cases["failed"]["activity"].startswith("http failed · VERIFICATION_FAILURE · ")
    assert "503" in cases["failed"]["activity"]


def test_long_failure_detail_is_truncated(cases):
    detail = cases["truncated"]["steps"][0]["detail"]
    assert len(detail) == 160
    assert detail.endswith("…")


def test_uncatalogued_kinds_are_not_shown_as_success(cases):
    assert cases["badKind"]["view"]["visible"] is False
    assert cases["badKind"]["passActivity"] == ""


def test_event_type_does_not_invent_a_pass_when_ok_is_false(cases):
    view = cases["disagree"]
    assert view["summary"] == "0 passed · 1 failed"
    assert view["steps"][0]["kind"] == "file"
    assert view["steps"][0]["status"] == "failed"
    assert "hash mismatch" in view["steps"][0]["detail"]


def test_runtime_unknown_kind_failure_stays_visible(cases):
    step = cases["runtimeUnknown"]["steps"][0]
    assert step["kind"] == "unknown"
    assert step["status"] == "failed"
    assert "pytest, http, file" in step["detail"]


def test_preview_hides_evidence_even_after_a_real_event(cases):
    view = cases["preview"]
    assert view["visible"] is False
    assert view["steps"] == []


def test_replay_projects_only_events_through_the_cursor(cases):
    early = cases["replayEarly"]
    assert early["steps"][0]["status"] == "checking"
    assert early["summary"].startswith("Checking")
    late = cases["replayLate"]
    assert late["steps"][0]["status"] == "failed"
    assert late["steps"][0]["kind"] == "http"


def test_static_evidence_hud_is_vanilla_and_preview_safe():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="evidenceHud" hidden' in html
    assert 'id="evidenceSteps"' in html
    assert html.index('id="evidenceHud"') < html.index('id="mapViewport"')
    assert "evidenceHudView" in control
    assert "verification.evidence.started" in control
    assert "verification.evidence.passed" in control
    assert "verification.evidence.failed" in control
    preview = control.split("function preview()", 1)[1].split("$(\"preview\").onclick", 1)[0]
    assert "verification.evidence" not in preview
    assert "react" not in (html + css + control + state).lower()
    assert "pixi" not in (html + css + control + state).lower()
    block = css.split(".evidence-strip{")[1].split("@media(max-width:980px)")[0]
    assert "animation" not in block
    assert "@keyframes" not in block
    assert "flex-direction:column" in block
    assert "overflow-wrap:anywhere" in block
    assert "export function evidenceHudView" in state


def test_static_evidence_hud_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="evidenceHud"' in page.text
        assert "No evidence checks" in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function evidenceHudView" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".evidence-strip" in css.text
