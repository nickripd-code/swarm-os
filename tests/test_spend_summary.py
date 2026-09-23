"""Read-only spend summary: recorded estimates only, never invented dollars."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import Mission, MissionEvent
from app.payments import build_payment_provider
from app.spend_summary import ESTIMATE_UNAVAILABLE, summarize_mission_spend
from app.store import Store

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "spend_summary_cases.mjs"
SECRET = "sk-test-should-not-leak"


def _summary(mission, events, *, providers=False, live=False):
    return summarize_mission_spend(
        mission, events, providers_configured=providers, live_spend_enabled=live,
    )


def test_no_mission_is_unavailable_and_has_no_dollars():
    body = _summary(None, [])
    encoded = json.dumps(body)
    assert body["state"] == "unavailable"
    assert body["reason"] == "no_mission"
    assert body["providers_configured"] is False
    assert body["live_spend_enabled"] is False
    assert body["token_estimate_known"] is False
    assert body["token_estimate"] is None
    assert body["payment_known"] is False
    assert body["payment_spent"] is None
    assert body["label"] == ESTIMATE_UNAVAILABLE
    assert body["burn_known"] is False
    assert "$" not in encoded
    assert "No cost data." in body["note"]
    assert "Model providers are unset." in body["note"]
    assert "Live spend is off." in body["note"]


def test_mission_without_events_does_not_invent_token_spend():
    mission = Mission(goal="Summarize a report", budget=4, token_spent=9.5)
    body = _summary(mission, [], providers=True)
    assert body["reason"] == "no_cost_data"
    assert body["token_estimate_known"] is False
    assert body["token_estimate"] is None
    assert body["tokens_recorded"] is False
    assert body["payment_known"] is True
    assert body["payment_spent"] == 0
    assert body["payment_budget"] == 4
    assert body["live_spend_enabled"] is False
    assert "No cost data." in body["note"]


def test_providers_unset_with_a_mission_is_explicit():
    mission = Mission(goal="Summarize a report")
    body = _summary(mission, [], providers=False)
    assert body["reason"] == "providers_unset"
    assert body["state"] == "unavailable"
    assert body["token_estimate"] is None
    assert "No cost data." in body["note"]
    assert "Model providers are unset." in body["note"]


def test_tokens_without_known_budget_do_not_become_dollars():
    mission = Mission(goal="Count tokens")
    event = MissionEvent(
        mission_id=mission.id,
        event_type="llm.completed",
        payload={"input_tokens": 11, "output_tokens": 7, "reasoning_tokens": 3},
    )
    body = _summary(mission, [event], providers=True)
    assert body["tokens_recorded"] is True
    assert body["tokens"]["total"] == 21
    assert body["token_estimate_known"] is False
    assert body["token_estimate"] is None
    assert body["burn_known"] is False
    assert "$" not in json.dumps({
        "token_estimate": body["token_estimate"],
        "burn": body["burn_usd_per_hour"],
    })


def test_known_budget_event_is_recorded_and_rates_use_that_window():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mission = Mission(goal="Known estimate", created_at=started, budget=2, spent=0.5)
    event = MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": True, "token_spent": 1.5, "token_budget": 3},
        created_at=started + timedelta(hours=1),
    )
    body = _summary(mission, [event], providers=False)
    assert body["state"] == "recorded"
    assert body["reason"] == "recorded"
    assert body["token_estimate"] == 1.5
    assert body["token_budget"] == 3
    assert body["burn_known"] is True
    assert body["burn_usd_per_hour"] == 1.5
    assert body["elapsed_seconds"] == 3600
    assert body["payment_spent"] == 0.5
    assert body["payment_budget"] == 2
    assert "Model providers are unset." in body["note"]
    assert "Recorded token estimate. Not an invoice." in body["note"]


def test_unknown_and_string_spend_do_not_replace_a_known_total():
    mission = Mission(goal="Keep the known total")
    known = MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": True, "token_spent": 0.5, "token_budget": 3},
    )
    unknown = MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": False, "token_spent": 0, "token_budget": 3},
    )
    string_known = MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": "true", "token_spent": 9, "token_budget": 3},
    )
    string_spent = MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": True, "token_spent": "1.25"},
    )
    body = _summary(mission, [known, unknown, string_known, string_spent], providers=True)
    assert body["token_estimate_known"] is True
    assert body["token_estimate"] == 0.5


def test_zero_elapsed_does_not_invent_a_burn_rate():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mission = Mission(goal="Instant", created_at=started)
    event = MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": True, "token_spent": 1},
        created_at=started,
    )
    body = _summary(mission, [event], providers=True)
    assert body["token_estimate"] == 1
    assert body["burn_known"] is False
    assert body["burn_usd_per_hour"] is None


def test_negative_and_bool_token_fields_are_not_spend():
    mission = Mission(goal="Reject junk")
    event = MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": True, "token_spent": -1, "token_budget": True},
    )
    tokens = MissionEvent(
        mission_id=mission.id,
        event_type="llm.completed",
        payload={"input_tokens": -5, "output_tokens": True, "reasoning_tokens": "4"},
    )
    body = _summary(mission, [event, tokens], providers=True)
    assert body["token_estimate_known"] is False
    assert body["token_estimate"] is None
    assert body["token_budget"] is None
    assert body["tokens_recorded"] is False


def test_live_spend_flag_is_reported_and_not_forced_off():
    body = _summary(None, [], live=True, providers=True)
    assert body["live_spend_enabled"] is True
    assert "Live spend is enabled." in body["note"]
    assert build_payment_provider().spend_enabled() is False


def test_live_payment_request_stays_disabled():
    mission = Mission(goal="Asked for live pay", live_payments=True)
    body = _summary(mission, [], providers=True, live=False)
    assert body["live_payments"] is True
    assert body["live_spend_enabled"] is False
    assert "settlement stays disabled" in body["note"]


def test_summary_module_does_not_price_or_settle():
    source = (ROOT / "app/spend_summary.py").read_text(encoding="utf-8")
    assert "estimate_token_cost" not in source
    assert "stripe" not in source.lower()
    assert "price_input" not in source


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    from app import main

    store = Store(str(tmp_path / "swarm.db"))
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main.runtime.controller, "configured", lambda: False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    return main, store


@pytest.mark.asyncio
async def test_spend_summary_endpoint_when_nothing_is_configured(isolated_store):
    main, _store = isolated_store
    body = await main.spend_summary()
    encoded = json.dumps(body)
    assert body["state"] == "unavailable"
    assert body["reason"] == "no_mission"
    assert body["providers_configured"] is False
    assert body["live_spend_enabled"] is False
    assert body["token_estimate"] is None
    assert SECRET not in encoded
    assert "api_key" not in encoded
    assert "$" not in encoded


@pytest.mark.asyncio
async def test_mission_spend_summary_endpoint_reads_recorded_events(isolated_store):
    main, store = isolated_store
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mission = Mission(goal="Endpoint estimate", created_at=started, budget=1)
    store.save_mission(mission)
    store.append(MissionEvent(
        mission_id=mission.id,
        event_type="llm.completed",
        payload={"input_tokens": 4, "output_tokens": 1},
        created_at=started,
    ))
    store.append(MissionEvent(
        mission_id=mission.id,
        event_type="budget.updated",
        payload={"known": True, "token_spent": 0.25, "token_budget": 3},
        created_at=started + timedelta(minutes=30),
    ))
    body = await main.mission_spend_summary(mission.id)
    assert body["mission_id"] == str(mission.id)
    assert body["token_estimate"] == 0.25
    assert body["tokens"]["total"] == 5
    assert body["burn_known"] is True
    assert body["burn_usd_per_hour"] == 0.5
    assert body["live_spend_enabled"] is False
    assert SECRET not in json.dumps(body)


@pytest.mark.asyncio
async def test_mission_spend_summary_missing_mission_is_404(isolated_store):
    main, _store = isolated_store
    with pytest.raises(HTTPException) as caught:
        await main.mission_spend_summary(uuid4())
    assert caught.value.status_code == 404


def test_static_spend_summary_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="spendSummary"' in page.text
        assert "estimate unavailable" in page.text
        block = page.text.split('id="spendSummary"', 1)[1].split("</section>", 1)[0]
        assert "$" not in block
        assert "stripe" not in block.lower()
        script = client.get("/static/spend-summary.mjs")
        assert script.status_code == 200
        assert "export function spendSummaryView" in script.text
        css = client.get("/static/spend-summary.css")
        assert css.status_code == 200
        assert ".spend-summary{" in css.text
        assert "animation" not in css.text


def test_spend_summary_view_cases():
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the spend summary harness")
    result = subprocess.run(
        ["node", str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    cases = json.loads(result.stdout)
    empty = cases["empty"]
    assert empty["state"] == "unavailable"
    assert empty["tokenLabel"] == ESTIMATE_UNAVAILABLE
    assert empty["rateLabel"] == ESTIMATE_UNAVAILABLE
    assert empty["ledgerLabel"] == "no mission"
    assert empty["liveLabel"] == "off"
    assert empty["providersLabel"] == "unset"
    assert "$" not in empty["tokenLabel"]
    assert "$" not in empty["note"]
    recorded = cases["recorded"]
    assert recorded["state"] == "recorded"
    assert recorded["tokenLabel"] == "$1.50 · 21 tokens"
    assert recorded["rateLabel"] == "$1.50/h"
    assert recorded["ledgerLabel"] == "$0 of $0"
    assert recorded["liveLabel"] == "off"
    assert recorded["providersLabel"] == "unset"
    tokens_only = cases["tokensOnly"]
    assert tokens_only["tokenLabel"] == "estimate unavailable · 21 tokens"
    assert "$" not in tokens_only["tokenLabel"]
    assert tokens_only["ledgerLabel"] == "$0 of $2.00"
    preview = cases["preview"]
    assert preview["state"] == "unavailable"
    assert preview["tokenLabel"] == ESTIMATE_UNAVAILABLE
    assert preview["rateLabel"] == ESTIMATE_UNAVAILABLE
    assert preview["ledgerLabel"] == "no mission"
    assert "$" not in preview["tokenLabel"]
    assert preview["note"].startswith("Preview does not report spend.")
    missing = cases["missing"]
    assert missing["tokenLabel"] == ESTIMATE_UNAVAILABLE
    assert missing["liveLabel"] == "unavailable"
    assert missing["providersLabel"] == "unavailable"
    assert "$" not in missing["tokenLabel"]
    assert cases["stringKnown"]["state"] == "unavailable"
    assert "$" not in cases["stringKnown"]["tokenLabel"]
    assert cases["stringSpend"]["state"] == "unavailable"
    assert cases["liveOn"]["liveLabel"] == "on"
    assert cases["formatUsd"]["nan"] is None
    assert cases["formatUsd"]["negative"] is None
    assert cases["formatUsd"]["zero"] == "$0"
    assert cases["formatUsd"]["plain"] == "$1.50"
    assert cases["ESTIMATE_UNAVAILABLE"] == ESTIMATE_UNAVAILABLE
