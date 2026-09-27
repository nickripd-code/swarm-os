"""Read-only pre-launch cost estimate. Never starts a mission or invents $0."""

import pytest

from app.llm import DEFAULT_MODEL
from app.resources import (
    ESTIMATE_UNAVAILABLE,
    PrelaunchEstimateError,
    ResourceScheduler,
    TokenCostSettings,
    prelaunch_estimate_from_body,
)


def _scheduler(**overrides) -> ResourceScheduler:
    settings = {
        "default_input_per_million": 15,
        "default_output_per_million": 60,
        "markup": 1.25,
        "unknown_price": "fail",
        "default_budget": 3,
        "hard_cap": 10,
    }
    settings.update(overrides)
    return ResourceScheduler(TokenCostSettings(**settings))


def test_known_default_prices_return_a_range():
    estimate = _scheduler().estimate_prelaunch(model="gpt-test", max_tokens=1_000_000)
    assert estimate.known is True
    assert estimate.tokens == 1_000_000
    assert estimate.steps is None
    assert estimate.source == "default"
    assert estimate.estimated_cost_low == 18.75
    assert estimate.estimated_cost_high == 75.0
    assert estimate.label == "Estimated cost: $18.75 – $75"
    assert estimate.currency == "USD"
    assert estimate.estimate is True
    assert estimate.mission_started is False
    assert estimate.estimated_cost_low != 0
    assert "invoice" in (estimate.reason or "")


def test_listed_prices_and_steps_scale_the_ceiling():
    estimate = _scheduler(markup=1.0).estimate_prelaunch(
        model="gpt-test", max_tokens=1_000_000, steps=2, listed_input=2, listed_output=8,
    )
    assert estimate.tokens == 2_000_000
    assert estimate.source == "listed"
    assert estimate.known is True
    assert estimate.estimated_cost_low == 4.0
    assert estimate.estimated_cost_high == 16.0
    assert estimate.label == "Estimated cost: $4 – $16"


def test_equal_prices_are_a_single_estimate_not_a_fake_span():
    estimate = _scheduler(markup=1.0).estimate_prelaunch(
        model="gpt-test", max_tokens=1_000_000, listed_input=10, listed_output=10,
    )
    assert estimate.known is True
    assert estimate.estimated_cost_low == 10.0
    assert estimate.estimated_cost_high == 10.0
    assert estimate.label == "Estimated cost: $10"


def test_unknown_price_fail_closed_does_not_invent_zero():
    estimate = _scheduler(
        default_input_per_million=None,
        default_output_per_million=None,
        unknown_price="fail",
    ).estimate_prelaunch(model="gpt-test", max_tokens=1000, steps=3)
    assert estimate.known is False
    assert estimate.tokens == 3000
    assert estimate.estimated_cost_low is None
    assert estimate.estimated_cost_high is None
    assert estimate.label == ESTIMATE_UNAVAILABLE
    assert estimate.reason == "missing price metadata"
    assert estimate.unknown_price == "fail"
    assert estimate.source == "unknown"
    assert estimate.mission_started is False


def test_unknown_price_skip_still_omits_dollars():
    estimate = _scheduler(
        default_input_per_million=None,
        default_output_per_million=None,
        unknown_price="skip",
    ).estimate_prelaunch(model="gpt-test", max_tokens=1000)
    assert estimate.known is False
    assert estimate.estimated_cost_low is None
    assert estimate.estimated_cost_high is None
    assert estimate.label == ESTIMATE_UNAVAILABLE
    assert estimate.unknown_price == "skip"


def test_missing_token_ceiling_is_unavailable():
    steps_only = _scheduler().estimate_prelaunch(model="gpt-test", steps=4)
    assert steps_only.tokens is None
    assert steps_only.known is False
    assert steps_only.label == ESTIMATE_UNAVAILABLE
    assert steps_only.reason == "step count without a token ceiling cannot price a launch"
    assert steps_only.estimated_cost_low is None

    empty = _scheduler().estimate_prelaunch(model="gpt-test")
    assert empty.tokens is None
    assert empty.label == ESTIMATE_UNAVAILABLE
    assert empty.reason == "planned token volume is unknown"


def test_invalid_plan_inputs_fail_closed():
    scheduler = _scheduler()
    rejected = [
        {"max_tokens": 0},
        {"max_tokens": -1},
        {"max_tokens": True},
        {"max_tokens": 1.5},
        {"max_tokens": "100"},
        {"steps": 0},
        {"steps": 1001},
        {"max_tokens": 10_000_001},
        {"model": ""},
        {"model": "   "},
        {"model": "bad\nid"},
        {"model": 12},
        {"model": "x" * 201},
    ]
    for kwargs in rejected:
        with pytest.raises(PrelaunchEstimateError):
            scheduler.estimate_prelaunch(**kwargs)


def test_model_defaults_to_swarm_model(monkeypatch):
    monkeypatch.delenv("SWARM_MODEL", raising=False)
    assert _scheduler().estimate_prelaunch(max_tokens=10).model == DEFAULT_MODEL
    monkeypatch.setenv("SWARM_MODEL", "custom-router-model")
    assert _scheduler().estimate_prelaunch(max_tokens=10).model == "custom-router-model"
    monkeypatch.setenv("SWARM_MODEL", "   ")
    with pytest.raises(PrelaunchEstimateError, match="SWARM_MODEL is empty"):
        _scheduler().estimate_prelaunch(max_tokens=10)


def test_body_rejects_fields_that_would_start_a_mission():
    with pytest.raises(PrelaunchEstimateError, match="invalid estimate request"):
        prelaunch_estimate_from_body({"max_tokens": 10, "goal": "ship it", "live_payments": True})
    with pytest.raises(PrelaunchEstimateError):
        prelaunch_estimate_from_body(["max_tokens"])


def test_estimate_route_known_unknown_and_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DATABASE_PATH", str(tmp_path / "swarm.db"))
    monkeypatch.setenv("SWARM_TOKEN_PRICE_INPUT_PER_MILLION", "15")
    monkeypatch.setenv("SWARM_TOKEN_PRICE_OUTPUT_PER_MILLION", "60")
    monkeypatch.setenv("SWARM_TOKEN_COST_MARKUP", "1.25")
    monkeypatch.setenv("SWARM_TOKEN_UNKNOWN_PRICE", "fail")
    monkeypatch.setenv("SWARM_MODEL", "route-model")
    from fastapi.testclient import TestClient

    from app.main import app, runtime, store

    with TestClient(app) as client:
        def refuse_save(*_args, **_kwargs):
            raise AssertionError("estimate must not save a mission")

        async def refuse_start(*_args, **_kwargs):
            raise AssertionError("estimate must not start a mission")

        monkeypatch.setattr(store, "save_mission", refuse_save)
        monkeypatch.setattr(runtime, "start", refuse_start)
        before = len(store.list_missions())
        runs_before = len(runtime.runs)

        known = client.post("/api/cost/estimate", json={"max_tokens": 1_000_000, "steps": 1})
        assert known.status_code == 200
        body = known.json()
        assert body["model"] == "route-model"
        assert body["tokens"] == 1_000_000
        assert body["known"] is True
        assert body["estimated_cost_low"] == 18.75
        assert body["estimated_cost_high"] == 75.0
        assert body["label"] == "Estimated cost: $18.75 – $75"
        assert body["mission_started"] is False
        assert body["estimate"] is True
        assert "mission_id" not in body

        monkeypatch.setenv("SWARM_TOKEN_PRICE_INPUT_PER_MILLION", "")
        monkeypatch.setenv("SWARM_TOKEN_PRICE_OUTPUT_PER_MILLION", "")
        unknown = client.post("/api/cost/estimate", json={"model": "route-model", "max_tokens": 500})
        assert unknown.status_code == 200
        unknown_body = unknown.json()
        assert unknown_body["known"] is False
        assert unknown_body["tokens"] == 500
        assert unknown_body["estimated_cost_low"] is None
        assert unknown_body["estimated_cost_high"] is None
        assert unknown_body["label"] == ESTIMATE_UNAVAILABLE
        assert unknown_body["reason"] == "missing price metadata"
        assert unknown_body["unknown_price"] == "fail"
        assert unknown_body["mission_started"] is False

        for payload in (
            {"max_tokens": 0},
            {"max_tokens": -3},
            {"max_tokens": True},
            {"max_tokens": 1.5},
            {"model": ""},
            {"model": "bad\nid"},
            {"goal": "do not launch", "live_payments": True},
        ):
            rejected = client.post("/api/cost/estimate", json=payload)
            assert rejected.status_code == 400, payload
            assert rejected.json()["detail"]
            assert "mission_id" not in rejected.json()

        steps_only = client.post("/api/cost/estimate", json={"steps": 4, "model": "route-model"})
        assert steps_only.status_code == 200
        assert steps_only.json()["tokens"] is None
        assert steps_only.json()["known"] is False
        assert steps_only.json()["label"] == ESTIMATE_UNAVAILABLE
        assert steps_only.json()["estimated_cost_low"] is None
        assert steps_only.json()["mission_started"] is False

        empty = client.post("/api/cost/estimate", json={})
        assert empty.status_code == 200
        assert empty.json()["label"] == ESTIMATE_UNAVAILABLE
        assert empty.json()["tokens"] is None
        assert empty.json()["known"] is False

        garbage = client.post(
            "/api/cost/estimate",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert garbage.status_code == 400

        spec = client.get("/openapi.json").json()
        assert "post" in spec["paths"]["/api/cost/estimate"]
        assert "/api/missions" in spec["paths"]
        assert len(store.list_missions()) == before
        assert len(runtime.runs) == runs_before
