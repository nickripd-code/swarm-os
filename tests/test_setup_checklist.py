"""First-run checklist: known facts only, unknown stays unavailable."""
from __future__ import annotations

import json
from pathlib import Path

from app.setup_checklist import PROVIDER_KEYS, first_run_checklist

ROOT = Path(__file__).resolve().parents[1]


def _health(**overrides) -> dict:
    payload = {key: {"configured": False, "provider": key} for key in PROVIDER_KEYS}
    payload.update(overrides)
    return payload


def _by_id(checklist: dict) -> dict:
    return {item["id"]: item for item in checklist["items"]}


def test_fresh_install_reports_missing_providers_and_compose(tmp_path):
    database = tmp_path / "swarm.db"
    database.write_bytes(b"")
    checklist = first_run_checklist(
        _health(), database_path=database, compose_root=tmp_path,
    )
    items = _by_id(checklist)

    assert [item["id"] for item in checklist["items"]] == [
        "providers", "database", "compose",
    ]
    assert items["providers"] == {
        "id": "providers",
        "label": "Model providers",
        "status": "missing",
        "detail": "No model provider is configured.",
    }
    assert items["database"]["status"] == "present"
    assert items["database"]["detail"] == str(database.resolve())
    assert items["compose"] == {
        "id": "compose",
        "label": "Docker Compose",
        "status": "missing",
        "detail": "No compose file is in the install tree.",
    }


def test_configured_provider_does_not_invent_reachability():
    health = _health()
    health["openai"] = {
        "configured": True,
        "provider": "openai",
        "model": "gpt-secret-model",
        "api_key": "sk-test-secret",
        "base_url": "https://secret.example/v1",
    }
    checklist = first_run_checklist(health)
    blob = json.dumps(checklist)
    item = _by_id(checklist)["providers"]

    assert item["status"] == "present"
    assert item["detail"] == "openai: configured; reachability unavailable"
    assert "sk-test-secret" not in blob
    assert "gpt-secret-model" not in blob
    assert "secret.example" not in blob
    assert "api_key" not in blob


def test_existing_allowlisted_status_is_quoted_not_upgraded():
    health = _health()
    health["ollama"] = {"configured": True, "provider": "ollama", "status": "unavailable"}
    item = _by_id(first_run_checklist(health))["providers"]
    assert item["status"] == "present"
    assert item["detail"] == "ollama: configured; reachability unavailable"


def test_unknown_provider_block_fails_closed():
    health = _health()
    del health["llamacpp"]
    assert _by_id(first_run_checklist(health))["providers"]["status"] == "unavailable"

    health = _health()
    health["openai"] = {"configured": "yes", "provider": "openai"}
    item = _by_id(first_run_checklist(health))["providers"]
    assert item["status"] == "unavailable"
    assert item["detail"] == "unavailable"

    assert _by_id(first_run_checklist(None))["providers"]["detail"] == "unavailable"


def test_workspace_docker_flag_is_not_compose_status():
    health = _health(workspace={"docker": False, "provider": "local", "configured": True})
    item = _by_id(first_run_checklist(health, compose_root=None))["compose"]
    assert item["status"] == "unavailable"
    assert item["detail"] == "unavailable"


def test_database_and_compose_paths_fail_closed(tmp_path):
    missing = tmp_path / "missing.db"
    missing_item = _by_id(first_run_checklist(_health(), database_path=missing))["database"]
    assert missing_item["status"] == "missing"
    assert missing_item["detail"] == str(missing.resolve())

    directory = tmp_path / "not-a-file"
    directory.mkdir()
    directory_item = _by_id(
        first_run_checklist(_health(), database_path=directory),
    )["database"]
    assert directory_item["status"] == "unavailable"
    assert directory_item["detail"] == "unavailable"

    assert _by_id(first_run_checklist(_health(), database_path=None))["database"]["status"] == "unavailable"
    assert _by_id(first_run_checklist(_health(), database_path="  "))["database"]["status"] == "unavailable"

    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n", encoding="utf-8")
    present = _by_id(first_run_checklist(_health(), compose_root=tmp_path))["compose"]
    assert present["status"] == "present"
    assert present["detail"] == "compose.yaml"
    assert "services" not in json.dumps(present)


def test_shell_renders_unavailable_until_health_answers():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    helper = (ROOT / "app/setup_checklist.py").read_text(encoding="utf-8")

    assert 'id="setupChecklist"' in html
    assert html.count(">unavailable<") >= 3
    assert "renderSetup(null)" in control
    assert "payload.setup.items" in control
    assert "httpx" not in helper
    assert "complete(" not in helper


def test_health_route_checklist_with_no_provider_keys():
    from fastapi.testclient import TestClient

    from app.main import app, database_path

    with TestClient(app) as client:
        response = client.get("/api/health")
        page = client.get("/")
    assert response.status_code == 200
    assert page.status_code == 200
    assert 'id="setupChecklist"' in page.text
    body = response.json()
    items = {item["id"]: item for item in body["setup"]["items"]}
    blob = json.dumps(body["setup"])
    assert "api_key" not in blob
    assert "sk-" not in blob
    assert body["active_missions"] == 0
    if all(body[key]["configured"] is False for key in PROVIDER_KEYS):
        assert items["providers"]["status"] == "missing"
        assert items["providers"]["detail"] == "No model provider is configured."
    assert items["database"]["status"] == "present"
    assert items["database"]["detail"] == str(database_path)
    assert items["compose"]["status"] == "missing"
    assert items["compose"]["detail"] == "No compose file is in the install tree."
