"""First-run checklist derived from known health fields and local path facts.

Unknown inputs stay ``unavailable``. This module does not call providers.
"""
from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path

PROVIDER_KEYS = (
    "openai", "openrouter", "xai", "anthropic", "mistral", "gemini", "cohere",
    "deepseek", "together", "groq", "fireworks", "azure", "perplexity", "bedrock",
    "huggingface", "cerebras", "sambanova", "vertex", "ollama", "vllm", "llamacpp",
)
_REACHABILITY = frozenset({"healthy", "unavailable", "unconfigured"})
_COMPOSE_NAMES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)
_STATUSES = frozenset({"missing", "present", "unavailable"})


def _item(item_id: str, label: str, status: str, detail: str) -> dict:
    if status not in _STATUSES:
        status, detail = "unavailable", "unavailable"
    return {"id": item_id, "label": label, "status": status, "detail": detail}


def _providers(health: Mapping | None) -> dict:
    if not isinstance(health, Mapping):
        return _item("providers", "Model providers", "unavailable", "unavailable")
    notes: list[str] = []
    for key in PROVIDER_KEYS:
        block = health.get(key)
        configured = block.get("configured") if isinstance(block, dict) else None
        if not isinstance(configured, bool):
            return _item("providers", "Model providers", "unavailable", "unavailable")
        if not configured:
            continue
        reported = block.get("status") if isinstance(block, dict) else None
        if isinstance(reported, str) and reported in _REACHABILITY:
            notes.append(f"{key}: configured; reachability {reported}")
        else:
            notes.append(f"{key}: configured; reachability unavailable")
    if not notes:
        return _item(
            "providers", "Model providers", "missing",
            "No model provider is configured.",
        )
    return _item("providers", "Model providers", "present", " ".join(notes))


def _database(path: str | Path | None) -> dict:
    if not isinstance(path, (str, Path)) or str(path).strip() == "":
        return _item("database", "Database path", "unavailable", "unavailable")
    try:
        resolved = Path(path).expanduser().resolve()
        mode = resolved.stat().st_mode
    except FileNotFoundError:
        try:
            shown = str(Path(path).expanduser().resolve())
        except OSError:
            return _item("database", "Database path", "unavailable", "unavailable")
        return _item("database", "Database path", "missing", shown)
    except OSError:
        return _item("database", "Database path", "unavailable", "unavailable")
    if not stat.S_ISREG(mode):
        return _item("database", "Database path", "unavailable", "unavailable")
    return _item("database", "Database path", "present", str(resolved))


def _compose(root: str | Path | None) -> dict:
    if not isinstance(root, (str, Path)) or str(root).strip() == "":
        return _item("compose", "Docker Compose", "unavailable", "unavailable")
    try:
        base = Path(root).expanduser().resolve()
        if not stat.S_ISDIR(base.stat().st_mode):
            return _item("compose", "Docker Compose", "unavailable", "unavailable")
        found: list[str] = []
        for name in _COMPOSE_NAMES:
            candidate = base / name
            try:
                mode = candidate.stat().st_mode
            except FileNotFoundError:
                continue
            except OSError:
                return _item("compose", "Docker Compose", "unavailable", "unavailable")
            if stat.S_ISREG(mode):
                found.append(name)
    except OSError:
        return _item("compose", "Docker Compose", "unavailable", "unavailable")
    if not found:
        return _item(
            "compose", "Docker Compose", "missing",
            "No compose file is in the install tree.",
        )
    return _item("compose", "Docker Compose", "present", found[0])


def first_run_checklist(
    health: Mapping | None,
    *,
    database_path: str | Path | None = None,
    compose_root: str | Path | None = None,
) -> dict:
    """Return providers, database path, and compose-file rows.

    ``health`` is an existing ``GET /api/health`` payload. Provider rows use
    the ``configured`` flag only. A missing or non-boolean flag fails closed.
    Reachability is copied only when that payload already includes an
    allowlisted status; otherwise the row says ``unavailable``.
    """
    return {
        "items": [
            _providers(health),
            _database(database_path),
            _compose(compose_root),
        ],
    }
