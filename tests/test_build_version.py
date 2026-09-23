"""Build version chip: show a declared health version, otherwise unavailable."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "build_version_cases.mjs"
UNAVAILABLE = "unavailable"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS build version harness")
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


def test_missing_version_stays_unavailable(cases):
    for name in ("missingBody", "missingField", "nullVersion", "blank", "number"):
        view = cases[name]
        assert view["known"] is False
        assert view["version"] is None
        assert view["label"] == UNAVAILABLE


def test_declared_version_is_shown_verbatim(cases):
    view = cases["declared"]
    assert view == {"known": True, "version": "0.2.0", "label": "0.2.0"}
    trimmed = cases["trim"]
    assert trimmed["known"] is True
    assert trimmed["version"] == "1.4.2-gabcdef"
    assert trimmed["label"] == trimmed["version"]


def test_reported_version_does_not_invent_a_string():
    from app.build_info import reported_version

    assert reported_version(None) is None
    assert reported_version("") is None
    assert reported_version("  ") is None
    assert reported_version(0.2) is None
    assert reported_version("0.2.0") == "0.2.0"
    assert reported_version("  v1  ") == "v1"


def test_health_passes_through_the_declared_app_version():
    from fastapi.testclient import TestClient

    from app.build_info import reported_version
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/health")
        page = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == reported_version(app.version)
    assert body["version"] == app.version
    assert isinstance(body["version"], str) and body["version"].strip()
    assert 'id="buildVersion"' in page.text
    assert ">unavailable<" in page.text
    assert app.version not in page.text


def test_chip_markup_does_not_hardcode_a_version():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="buildVersion"' in html
    assert "buildVersionView" in control
    assert "export function buildVersionView" in state
    assert "0.2.0" not in html
    assert "0.2.0" not in control
    assert "git describe" not in control
    chip = html.split('id="buildVersion"', 1)[1].split("</span>", 1)[0]
    assert "unavailable" in chip
    assert "0." not in chip
