"""Mission Control last-model-call strip: recorded llm events only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "model_call_strip_cases.mjs"
EMPTY = "No recorded model call."
PREVIEW = "Preview runs no models."
NOTE = "Recorded model events only"
UNKNOWN = "unknown"
FIELDS = {"provider", "model", "role", "status"}


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the vanilla JS model-call harness")
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


def test_standby_hides_the_strip(cases):
    view = cases["standby"]
    assert view["hidden"] is True
    assert view["empty"] is True
    assert view["call"] is None
    assert view["note"] == EMPTY


def test_loaded_mission_with_no_model_events_is_empty(cases):
    view = cases["empty"]
    assert view["hidden"] is False
    assert view["empty"] is True
    assert view["call"] is None
    assert view["note"] == EMPTY


def test_preview_never_invents_a_model_call(cases):
    view = cases["preview"]
    assert view["hidden"] is False
    assert view["empty"] is True
    assert view["call"] is None
    assert view["note"] == PREVIEW
    assert cases["constants"]["preview"] == PREVIEW
    blob = json.dumps(view)
    assert "gpt-6-astra" not in blob
    assert "openai" not in blob


def test_last_completed_call_is_provider_model_role_and_status(cases):
    view = cases["full"]
    assert view["empty"] is False
    assert view["note"] == NOTE
    assert view["call"] == {
        "provider": "openai",
        "model": "gpt-6-astra",
        "role": "decision",
        "status": "completed",
    }
    assert set(view["call"]) == FIELDS
    blob = json.dumps(view)
    assert "resp_secret" not in blob
    assert "SECRET_RESPONSE" not in blob
    assert "secret rationale" not in blob
    assert "do not show" not in blob
    assert "instructions" not in blob
    assert "output" not in blob
    assert "openrouter" not in blob


def test_replay_cursor_keeps_the_in_flight_call(cases):
    view = cases["atStart"]
    assert view["call"] == {
        "provider": UNKNOWN,
        "model": "gpt-6-astra",
        "role": "decision",
        "status": "started",
    }


def test_started_call_does_not_invent_a_provider(cases):
    view = cases["started"]
    assert view["call"]["provider"] == UNKNOWN
    assert view["call"]["status"] == "started"
    assert view["call"]["model"] == "gpt-6-astra"
    assert view["call"]["role"] == "decision"


def test_failure_status_omits_the_error_text(cases):
    view = cases["failed"]
    assert view["call"] == {
        "provider": UNKNOWN,
        "model": "gpt-6-astra",
        "role": "work",
        "status": "failed",
    }
    blob = json.dumps(view)
    assert "RATE_LIMIT" not in blob
    assert "SECRET_RESPONSE" not in blob
    assert "Ignore previous" not in blob


def test_retry_and_failover_use_bounded_status_tokens(cases):
    assert cases["retry"]["call"] == {
        "provider": UNKNOWN,
        "model": "claude-sonnet-4-5",
        "role": "verification",
        "status": "retrying",
    }
    assert cases["failover"]["call"] == {
        "provider": "openrouter",
        "model": "openai/gpt-4o",
        "role": "decision",
        "status": "failover",
    }
    blob = json.dumps(cases["failover"])
    assert "SECRET_RESPONSE" not in blob
    assert "openai" not in cases["failover"]["call"]["provider"]


def test_router_metadata_supplies_provider_and_model_when_top_level_is_absent(cases):
    assert cases["routed"]["call"] == {
        "provider": "fireworks",
        "model": "accounts/fireworks/models/llama-v3p1-8b-instruct",
        "role": "work",
        "status": "completed",
    }
    assert "Ignore previous" not in json.dumps(cases["routed"])


def test_freeform_prompt_fields_fail_closed_to_unknown(cases):
    view = cases["dumped"]
    assert view["call"] == {
        "provider": UNKNOWN,
        "model": UNKNOWN,
        "role": UNKNOWN,
        "status": "completed",
    }
    blob = json.dumps(view)
    assert "Ignore previous" not in blob
    assert "SECRET_RESPONSE" not in blob
    assert "OpenAI" not in blob


def test_catalog_model_ids_with_colon_stay_intact(cases):
    assert cases["bedrock"]["call"]["provider"] == "bedrock"
    assert cases["bedrock"]["call"]["model"] == "amazon.nova-lite-v1:0"
    assert cases["constants"]["unknown"] == UNKNOWN


def test_markup_does_not_dump_model_payloads():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    assert 'id="modelCallStrip"' in html
    assert 'id="modelCallProvider"' in html
    assert 'id="modelCallModel"' in html
    assert 'id="modelCallRole"' in html
    assert 'id="modelCallStatus"' in html
    assert EMPTY in html
    assert "export function lastModelCall" in state
    assert "lastModelCall" in control
    start = control.index("function renderModelCallStrip")
    block = control[start:control.index("function renderActivity")]
    for banned in ("output", "instructions", "response_id", "JSON.stringify", "payload", "error", "rationale"):
        assert banned not in block
    strip_css = css.split(".model-call-strip{")[1].split(".objective-hud{")[0]
    assert "animation" not in strip_css
    assert "@keyframes" not in strip_css


def test_static_model_call_strip_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="modelCallStrip"' in page.text
        assert EMPTY in page.text
        module = client.get("/static/state.mjs")
        assert module.status_code == 200
        assert "export function lastModelCall" in module.text
        js = client.get("/static/control.js")
        assert js.status_code == 200
        assert "renderModelCallStrip" in js.text
        styles = client.get("/static/control.css")
        assert styles.status_code == 200
        assert ".model-call-strip{" in styles.text
