"""Read-only Mission Control failure-class chip. Never invents a class."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import FailureClass

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "failure_class_chip_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the failure-class chip harness")
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


def test_allowlist_matches_backend_failure_classes(cases):
    assert set(cases["classes"]) == {item.value for item in FailureClass}
    assert cases["unavailable"] == UNAVAILABLE
    assert UNAVAILABLE not in cases["classes"]


def _hidden(view: dict) -> None:
    assert view["hidden"] is True
    assert view["label"] == ""
    assert view["known"] is False
    assert view["failure_class"] is None


def test_chip_stays_hidden_without_a_failed_mission(cases):
    for name in ("noMission", "preview", "running", "completed", "stopped", "blocked", "waiting", "paused", "parked", "replayBefore"):
        _hidden(cases[name])


def test_known_class_is_shown_verbatim(cases):
    assert cases["known"] == {
        "hidden": False, "label": "TIMEOUT", "known": True, "failure_class": "TIMEOUT",
    }
    assert cases["unknownRecorded"]["label"] == "UNKNOWN_FAILURE"
    assert cases["unknownRecorded"]["known"] is True
    assert cases["fromEvent"]["failure_class"] == "PROVIDER_OUTAGE"
    assert cases["replayAtFailure"]["failure_class"] == "RATE_LIMIT"
    assert cases["replayAtFailure"]["hidden"] is False


def test_failed_without_a_known_class_is_unavailable(cases):
    for name in ("missingResult", "emptyResult", "nullClass", "blankClass", "paddedClass", "lowerClass", "inventedClass", "errorOnly", "eventMissing"):
        view = cases[name]
        assert view["hidden"] is False
        assert view["label"] == UNAVAILABLE
        assert view["known"] is False
        assert view["failure_class"] is None
        assert "NOT_A_CLASS" not in view["label"]
        assert "timeout" not in view["label"]


def test_markup_starts_hidden_and_does_not_name_a_class():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="failureClassChip" class="hud-chip failure unavailable" hidden' in html
    assert "failureClassChip(state)" in control
    assert "export function failureClassChip" in state
    assert ".hud-chip.failure.known" in css
    assert ".hud-chip.failure.unavailable" in css
    block = css.split(".hud-chip.failure.unavailable")[1].split("}")[0]
    assert "animation" not in block
    for name in FailureClass:
        assert f">{name.value}<" not in html


def test_static_failure_class_chip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="failureClassChip"' in page.text
        assert 'id="failureClassChip" class="hud-chip failure unavailable" hidden' in page.text
        module = client.get("/static/state.mjs")
        assert module.status_code == 200
        assert "export function failureClassChip" in module.text
        js = client.get("/static/control.js")
        assert js.status_code == 200
        assert "failureClassChip(state)" in js.text
        styles = client.get("/static/control.css")
        assert styles.status_code == 200
        assert ".hud-chip.failure.unavailable" in styles.text
