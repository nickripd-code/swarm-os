"""Read-only mission event timeline: durable tail only, never invented rows."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.models import Mission, MissionEvent
from app.store import Store
from app.timeline import mission_timeline, recent_events

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "timeline_cases.mjs"


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_recent_events_keep_the_tail_and_skip_blank_types():
    created = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    rows = recent_events([
        _Row(id=1, event_type="mission.started", actor_id=None, payload={"note": "hidden"}, created_at=None),
        _Row(id=2, event_type="", actor_id=None, payload={"role": "ghost"}, created_at=None),
        _Row(id=3, event_type="legacy.custom", actor_id=None, payload={"role": "  scribe  "}, created_at=created),
    ], limit=2)
    assert [row["id"] for row in rows] == [3]
    assert rows[0]["event_type"] == "legacy.custom"
    assert rows[0]["summary"] == "scribe"
    assert rows[0]["created_at"] == created.isoformat()
    assert "note" not in rows[0]
    assert "payload" not in rows[0]


def test_summary_uses_only_short_stored_fields():
    rows = recent_events([
        _Row(id=1, event_type="mission.failed", actor_id=None, payload={
            "error": "boom secret", "failure_class": "TIMEOUT", "reason": "a long story",
        }, created_at=None),
    ], limit=5)
    assert rows[0]["summary"] == "TIMEOUT"
    assert "boom" not in json.dumps(rows)
    assert "story" not in json.dumps(rows)


def test_limit_rejects_out_of_range():
    with pytest.raises(ValueError):
        recent_events([], limit=0)
    with pytest.raises(ValueError):
        recent_events([], limit=51)


def test_missing_and_empty_missions_invent_nothing(tmp_path):
    store = Store(str(tmp_path / "timeline.db"))
    missing = mission_timeline(store, uuid4())
    assert missing == {"available": False, "state": "no_mission", "events": []}
    mission = Mission(goal="No events yet")
    store.save_mission(mission)
    empty = mission_timeline(store, mission.id)
    assert empty == {"available": True, "state": "empty", "events": []}


def test_timeline_endpoint_reads_durable_tail(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "timeline.db"))
    mission = Mission(goal="See recent events")
    store.save_mission(mission)
    store.append(MissionEvent(
        mission_id=mission.id, event_type="mission.started", payload={"note": "do not surface"},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    store.append(MissionEvent(
        mission_id=mission.id, event_type="mission.failed",
        payload={"failure_class": "TIMEOUT", "error": "boom secret"},
        created_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
    ))
    monkeypatch.setattr("app.main.store", store)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        missing = client.get(f"/api/missions/{uuid4()}/timeline")
        assert missing.status_code == 200
        assert missing.json() == {"available": False, "state": "no_mission", "events": []}

        quiet = Mission(goal="Empty log")
        store.save_mission(quiet)
        empty = client.get(f"/api/missions/{quiet.id}/timeline")
        assert empty.status_code == 200
        assert empty.json() == {"available": True, "state": "empty", "events": []}

        tail = client.get(f"/api/missions/{mission.id}/timeline", params={"limit": 1})
        assert tail.status_code == 200
        body = tail.json()
        assert body["available"] is True
        assert body["state"] == "ok"
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "mission.failed"
        assert body["events"][0]["summary"] == "TIMEOUT"
        assert "payload" not in body["events"][0]
        assert "boom" not in tail.text
        assert "do not surface" not in tail.text

        full = client.get(f"/api/missions/{mission.id}/timeline")
        assert [item["event_type"] for item in full.json()["events"]] == [
            "mission.started", "mission.failed",
        ]

        assert client.get(f"/api/missions/{mission.id}/timeline", params={"limit": 0}).status_code == 400
        assert client.get(f"/api/missions/{mission.id}/timeline", params={"limit": 51}).status_code == 400

        page = client.get("/")
        assert page.status_code == 200
        assert 'id="eventTimeline"' in page.text
        assert "No mission is loaded." in page.text
        module = client.get("/static/timeline.mjs")
        assert module.status_code == 200
        assert "export function timelinePanel" in module.text
        script = client.get("/static/control.js")
        assert "/timeline?limit=12" in script.text


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the timeline harness")
    result = subprocess.run(
        ["node", str(HARNESS)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_panel_fail_closed_states():
    loaded = _load_cases()
    assert loaded["cases"]["noMission"]["message"] == loaded["NO_MISSION"]
    assert loaded["cases"]["noMission"]["events"] == []
    preview = loaded["cases"]["preview"]
    assert preview["state"] == "no_mission"
    assert preview["events"] == []
    assert loaded["cases"]["pending"]["message"] == loaded["PENDING"]
    assert loaded["cases"]["pending"]["events"] == []
    assert loaded["cases"]["failed"]["state"] == "unavailable"
    assert loaded["cases"]["failed"]["message"] == loaded["UNAVAILABLE"]
    assert loaded["cases"]["serverMissing"]["events"] == []
    assert loaded["cases"]["empty"]["state"] == "empty"
    assert loaded["cases"]["empty"]["message"] == loaded["EMPTY"]
    assert loaded["cases"]["dropsBlank"]["state"] == "empty"
    recorded = loaded["cases"]["recorded"]["events"]
    assert recorded == [{
        "event_type": "mission.failed",
        "created_at": "2026-01-01T00:05:00+00:00",
        "summary": "TIMEOUT",
    }]
    assert "payload" not in recorded[0]
    assert "secret" not in json.dumps(recorded)
