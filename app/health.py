from __future__ import annotations

import os
from .credentials import get_api_key, get_openrouter_api_key
from .llm import DEFAULT_MODEL, DEFAULT_OPENROUTER_MODEL, DEFAULT_REASONING


def openai_status() -> dict:
    return {"configured": bool(get_api_key()), "model": os.getenv("SWARM_MODEL", DEFAULT_MODEL),
            "reasoning_effort": os.getenv("SWARM_REASONING_EFFORT", DEFAULT_REASONING),
            "provider": "openai", "fallback": False}


def openrouter_status() -> dict:
    return {"configured": bool(get_openrouter_api_key()),
            "model": os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            "provider": "openrouter", "fallback": False}
