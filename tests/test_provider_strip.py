"""Read-only provider connectivity strip: configured vs missing, no live calls."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "provider_strip_cases.mjs"
UNAVAILABLE = "configuration unavailable"

_PROVIDER_ENV = (
    "OPENAI_API_KEY", "OPENROUTER_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY",
    "MISTRAL_API_KEY", "MISTRAL_MODEL", "GEMINI_API_KEY", "COHERE_API_KEY", "COHERE_MODEL",
    "DEEPSEEK_API_KEY", "TOGETHER_API_KEY", "GROQ_API_KEY", "FIREWORKS_API_KEY",
    "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT",
    "PERPLEXITY_API_KEY", "BEDROCK_API_KEY", "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "HUGGINGFACE_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY",
    "VERTEX_API_KEY", "VERTEX_PROJECT", "VERTEX_MODEL", "GOOGLE_CLOUD_PROJECT",
    "OLLAMA_MODEL", "OLLAMA_BASE_URL", "VLLM_MODEL", "VLLM_BASE_URL",
    "LLAMACPP_MODEL", "LLAMACPP_BASE_URL",
    "SWARM_LOCAL_TOOLS", "MCP_SERVER_URL", "MCP_API_KEY",
    "SWARM_BROWSER", "SWARM_SELFMOD", "COMPOSIO_API_KEY",
)


def _clear_provider_env(monkeypatch) -> None:
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def _by_id(snapshot: dict) -> dict[str, dict]:
    return {item["id"]: item for item in snapshot["providers"]}


def test_snapshot_is_missing_without_keys_except_local_workspace(monkeypatch):
    _clear_provider_env(monkeypatch)
    from app.health import connectivity_snapshot

    snapshot = connectivity_snapshot()
    rows = _by_id(snapshot)
    assert snapshot["probed"] is False
    assert rows["workspace"]["configured"] is True
    assert rows["workspace"]["detail"] == "local"
    assert rows["workspace"]["state"] == "configured"
    keyed = [item for item in snapshot["providers"] if item["id"] != "workspace"]
    assert keyed
    assert all(item["configured"] is False and item["state"] == "missing" for item in keyed)
    assert snapshot["configured"] == 1
    assert snapshot["missing"] == len(keyed)
    assert "openai" in rows and "composio" in rows and "browser" in rows


def test_snapshot_marks_only_opted_in_providers(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setenv("COMPOSIO_API_KEY", "composio-test-key")
    monkeypatch.setenv("SWARM_LOCAL_TOOLS", "echo,not-a-tool")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key-only")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-iam")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-secret")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-small-latest")
    from app.health import connectivity_snapshot

    rows = _by_id(connectivity_snapshot())
    assert rows["openai"]["configured"] is True
    assert rows["openai"]["state"] == "configured"
    assert rows["composio"]["configured"] is True
    assert rows["local"]["configured"] is True
    assert rows["azure"]["configured"] is False
    assert rows["bedrock"]["configured"] is False
    assert rows["mistral"]["configured"] is False
    assert rows["openrouter"]["configured"] is False
    blob = json.dumps(rows)
    assert "sk-test-openai" not in blob
    assert "composio-test-key" not in blob
    assert "azure-key-only" not in blob
    assert "ambient-secret" not in blob


def test_snapshot_does_not_open_an_http_client(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LLAMACPP_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MCP_SERVER_URL", "http://127.0.0.1:9/mcp")

    def boom(*_args, **_kwargs):
        raise AssertionError("connectivity snapshot opened an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    monkeypatch.setattr(httpx, "Client", boom)
    from app.health import connectivity_snapshot

    rows = _by_id(connectivity_snapshot())
    assert rows["ollama"]["configured"] is True
    assert rows["vllm"]["configured"] is True
    assert rows["llamacpp"]["configured"] is True
    assert rows["mcp"]["configured"] is True
    assert "127.0.0.1" not in json.dumps(rows)


def test_api_health_includes_non_probing_connectivity(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("SWARM_DATABASE_PATH", str(tmp_path / "swarm.db"))
    monkeypatch.setenv("SWARM_PROCESS_WORKERS", "0")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    connectivity = body["connectivity"]
    assert connectivity["probed"] is False
    rows = _by_id(connectivity)
    assert rows["openai"]["configured"] is False
    assert rows["workspace"]["configured"] is True
    assert rows["workspace"]["detail"] == "local"
    assert "root" not in rows["workspace"]


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the provider strip harness")
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


def test_strip_view_fails_closed_without_connectivity(cases):
    for key in ("empty", "missingField", "emptyList"):
        view = cases[key]
        assert view["known"] is False
        assert view["configured"] == 0
        assert view["items"] == []
        assert view["note"] == UNAVAILABLE


def test_string_configured_is_missing(cases):
    view = cases["stringTrue"]
    assert view["known"] is True
    assert view["configured"] == 0
    assert view["missing"] == 1
    assert view["items"][0]["state"] == "missing"
    assert view["items"][0]["stateLabel"] == "missing"


def test_bool_configured_and_local_workspace_render(cases):
    view = cases["boolTrue"]
    by_id = {item["id"]: item for item in view["items"]}
    assert set(by_id) == {"openai", "openrouter", "workspace"}
    assert by_id["openai"]["stateLabel"] == "configured"
    assert by_id["openrouter"]["stateLabel"] == "missing"
    assert by_id["workspace"]["stateLabel"] == "local"
    assert by_id["workspace"]["configured"] is True
    assert view["configured"] == 2
    assert view["missing"] == 1


def test_non_local_detail_is_not_shown_as_a_label(cases):
    item = cases["secretDetail"]["items"][0]
    assert item["configured"] is True
    assert item["stateLabel"] == "configured"
    assert "sk-live-secret" not in json.dumps(item)


def test_static_strip_is_served_and_does_not_claim_live_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DATABASE_PATH", str(tmp_path / "swarm.db"))
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    assert 'id="providerStrip"' in html
    assert UNAVAILABLE in html
    assert "providerStripView" in control
    assert "renderProviderStrip" in control
    assert ".provider-strip{" in css
    assert "animation" not in css.split(".provider-strip{")[1].split(".telemetry-drawer")[0]
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="providerStrip"' in page.text
        assert UNAVAILABLE in page.text
        state = client.get("/static/state.mjs")
        assert "export function providerStripView" in state.text
