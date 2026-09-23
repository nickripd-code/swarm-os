from __future__ import annotations

import os
from .credentials import (
    get_api_key, get_anthropic_api_key, get_cerebras_api_key, get_cohere_api_key,
    get_deepseek_api_key,
    get_fireworks_api_key, get_gemini_api_key, get_groq_api_key, get_huggingface_api_key,
    get_mistral_api_key, get_openrouter_api_key, get_perplexity_api_key,
    get_sambanova_api_key, get_together_api_key, get_vertex_project, get_xai_api_key,
)
from .llm import (
    DEFAULT_ANTHROPIC_BASE_URL, DEFAULT_ANTHROPIC_MODEL, DEFAULT_AZURE_OPENAI_API_VERSION,
    DEFAULT_BEDROCK_MODEL, DEFAULT_BEDROCK_REGION, DEFAULT_CEREBRAS_BASE_URL,
    DEFAULT_CEREBRAS_MODEL, DEFAULT_COHERE_BASE_URL, DEFAULT_COHERE_MODEL,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL, DEFAULT_FIREWORKS_BASE_URL, DEFAULT_FIREWORKS_MODEL,
    DEFAULT_GEMINI_BASE_URL, DEFAULT_GEMINI_MODEL, DEFAULT_GROQ_BASE_URL,
    DEFAULT_GROQ_MODEL, DEFAULT_LLAMACPP_BASE_URL, DEFAULT_MODEL,
    DEFAULT_MISTRAL_BASE_URL, DEFAULT_MISTRAL_MODEL, DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_HUGGINGFACE_BASE_URL, DEFAULT_HUGGINGFACE_MODEL,
    DEFAULT_OPENROUTER_MODEL, DEFAULT_PERPLEXITY_BASE_URL, DEFAULT_PERPLEXITY_MODEL,
    DEFAULT_SAMBANOVA_BASE_URL, DEFAULT_SAMBANOVA_MODEL,
    DEFAULT_REASONING, DEFAULT_TOGETHER_BASE_URL,
    DEFAULT_TOGETHER_MODEL, DEFAULT_VERTEX_LOCATION, DEFAULT_VERTEX_MODEL, DEFAULT_VLLM_BASE_URL,
    DEFAULT_XAI_MODEL, DEFAULT_XAI_BASE_URL,
    LlamaCppModelProvider, OllamaModelProvider, VllmModelProvider,
    azure_openai_opted_in, bedrock_opted_in, default_bedrock_base_url, default_vertex_base_url,
    llamacpp_opted_in, ollama_opted_in, vertex_opted_in, vllm_opted_in,
)


def openai_status() -> dict:
    return {"configured": bool(get_api_key()), "model": os.getenv("SWARM_MODEL", DEFAULT_MODEL),
            "reasoning_effort": os.getenv("SWARM_REASONING_EFFORT", DEFAULT_REASONING),
            "provider": "openai", "fallback": False}


def openrouter_status() -> dict:
    return {"configured": bool(get_openrouter_api_key()),
            "model": os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            "provider": "openrouter", "fallback": False}


def xai_status() -> dict:
    return {"configured": bool(get_xai_api_key()),
            "model": os.getenv("XAI_MODEL", DEFAULT_XAI_MODEL),
            "base_url": os.getenv("XAI_BASE_URL", DEFAULT_XAI_BASE_URL),
            "provider": "xai", "fallback": False}


def anthropic_status() -> dict:
    return {"configured": bool(get_anthropic_api_key()),
            "model": os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
            "base_url": os.getenv("ANTHROPIC_BASE_URL", DEFAULT_ANTHROPIC_BASE_URL),
            "provider": "anthropic", "fallback": False}


def mistral_status() -> dict:
    return {"configured": bool(get_mistral_api_key()),
            "model": os.getenv("MISTRAL_MODEL", DEFAULT_MISTRAL_MODEL),
            "base_url": os.getenv("MISTRAL_BASE_URL", DEFAULT_MISTRAL_BASE_URL),
            "provider": "mistral", "fallback": False}


def gemini_status() -> dict:
    return {"configured": bool(get_gemini_api_key()),
            "model": os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            "base_url": os.getenv("GEMINI_BASE_URL", DEFAULT_GEMINI_BASE_URL),
            "provider": "gemini", "fallback": False}


def cohere_status() -> dict:
    return {"configured": bool(get_cohere_api_key()),
            "model": os.getenv("COHERE_MODEL", DEFAULT_COHERE_MODEL),
            "base_url": os.getenv("COHERE_BASE_URL", DEFAULT_COHERE_BASE_URL),
            "provider": "cohere", "fallback": False}


def deepseek_status() -> dict:
    return {"configured": bool(get_deepseek_api_key()),
            "model": os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
            "base_url": os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
            "provider": "deepseek", "fallback": False}


def together_status() -> dict:
    return {"configured": bool(get_together_api_key()),
            "model": os.getenv("TOGETHER_MODEL", DEFAULT_TOGETHER_MODEL),
            "base_url": os.getenv("TOGETHER_BASE_URL", DEFAULT_TOGETHER_BASE_URL),
            "provider": "together", "fallback": False}


def groq_status() -> dict:
    return {"configured": bool(get_groq_api_key()),
            "model": os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
            "base_url": os.getenv("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL),
            "provider": "groq", "fallback": False}


def fireworks_status() -> dict:
    return {"configured": bool(get_fireworks_api_key()),
            "model": os.getenv("FIREWORKS_MODEL", DEFAULT_FIREWORKS_MODEL),
            "base_url": os.getenv("FIREWORKS_BASE_URL", DEFAULT_FIREWORKS_BASE_URL),
            "provider": "fireworks", "fallback": False}


def azure_status() -> dict:
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip().rstrip("/") or None
    deployment = (os.getenv("AZURE_OPENAI_DEPLOYMENT") or "").strip() or None
    return {"configured": azure_openai_opted_in(),
            "model": deployment,
            "endpoint": endpoint,
            "deployment": deployment,
            "api_version": os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_OPENAI_API_VERSION),
            "provider": "azure", "fallback": False}


def perplexity_status() -> dict:
    return {"configured": bool(get_perplexity_api_key()),
            "model": os.getenv("PERPLEXITY_MODEL", DEFAULT_PERPLEXITY_MODEL),
            "base_url": os.getenv("PERPLEXITY_BASE_URL", DEFAULT_PERPLEXITY_BASE_URL),
            "provider": "perplexity", "fallback": False}


def bedrock_status() -> dict:
    region = (os.getenv("BEDROCK_REGION") or DEFAULT_BEDROCK_REGION).strip() or DEFAULT_BEDROCK_REGION
    base_url = (os.getenv("BEDROCK_BASE_URL") or default_bedrock_base_url(region)).rstrip("/")
    return {"configured": bedrock_opted_in(),
            "model": os.getenv("BEDROCK_MODEL", DEFAULT_BEDROCK_MODEL),
            "region": region,
            "base_url": base_url,
            "provider": "bedrock", "fallback": False}


def huggingface_status() -> dict:
    return {"configured": bool(get_huggingface_api_key()),
            "model": os.getenv("HUGGINGFACE_MODEL", DEFAULT_HUGGINGFACE_MODEL),
            "base_url": os.getenv("HUGGINGFACE_BASE_URL", DEFAULT_HUGGINGFACE_BASE_URL),
            "provider": "huggingface", "fallback": False}


def cerebras_status() -> dict:
    return {"configured": bool(get_cerebras_api_key()),
            "model": os.getenv("CEREBRAS_MODEL", DEFAULT_CEREBRAS_MODEL),
            "base_url": os.getenv("CEREBRAS_BASE_URL", DEFAULT_CEREBRAS_BASE_URL),
            "provider": "cerebras", "fallback": False}


def sambanova_status() -> dict:
    return {"configured": bool(get_sambanova_api_key()),
            "model": os.getenv("SAMBANOVA_MODEL", DEFAULT_SAMBANOVA_MODEL),
            "base_url": os.getenv("SAMBANOVA_BASE_URL", DEFAULT_SAMBANOVA_BASE_URL),
            "provider": "sambanova", "fallback": False}


def vertex_status() -> dict:
    location = (os.getenv("VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip() or DEFAULT_VERTEX_LOCATION
    base_url = (os.getenv("VERTEX_BASE_URL") or default_vertex_base_url(location)).rstrip("/")
    return {"configured": vertex_opted_in(),
            "model": os.getenv("VERTEX_MODEL", DEFAULT_VERTEX_MODEL),
            "project": get_vertex_project(),
            "location": location,
            "base_url": base_url,
            "provider": "vertex", "fallback": False}


def ollama_status() -> dict:
    return {"configured": ollama_opted_in(),
            "model": os.getenv("OLLAMA_MODEL"),
            "base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            "provider": "ollama", "fallback": False}


async def ollama_health_status() -> dict:
    health = await OllamaModelProvider().health()
    return {**ollama_status(), "status": health.status, "detail": health.detail}


def vllm_status() -> dict:
    return {"configured": vllm_opted_in(),
            "model": os.getenv("VLLM_MODEL"),
            "base_url": os.getenv("VLLM_BASE_URL", DEFAULT_VLLM_BASE_URL),
            "provider": "vllm", "fallback": False}


async def vllm_health_status() -> dict:
    health = await VllmModelProvider().health()
    return {**vllm_status(), "status": health.status, "detail": health.detail}


def llamacpp_status() -> dict:
    return {"configured": llamacpp_opted_in(),
            "model": os.getenv("LLAMACPP_MODEL"),
            "base_url": os.getenv("LLAMACPP_BASE_URL", DEFAULT_LLAMACPP_BASE_URL),
            "provider": "llamacpp", "fallback": False}


async def llamacpp_health_status() -> dict:
    health = await LlamaCppModelProvider().health()
    return {**llamacpp_status(), "status": health.status, "detail": health.detail}


async def browser_health_status() -> dict:
    from .browser import BrowserToolProvider
    provider = BrowserToolProvider()
    health = await provider.health()
    return {
        "configured": provider.configured(),
        "provider": "playwright",
        "status": health.status,
        "detail": health.detail,
        "tools": health.tools,
        "fallback": False,
    }


async def selfmod_health_status() -> dict:
    from .selfmod import SelfModToolProvider, selfmod_production_write_opted_in, selfmod_write_opted_in
    provider = SelfModToolProvider()
    health = await provider.health()
    return {
        "configured": provider.configured(),
        "provider": "selfmod",
        "status": health.status,
        "detail": health.detail,
        "tools": health.tools,
        "write_enabled": selfmod_write_opted_in(),
        "production_write": selfmod_production_write_opted_in(),
        "fallback": False,
    }


def mission_limits_status() -> dict:
    """Create-mission caps Mission Control may show before launch.

    Count caps are ``MissionLimits`` defaults — the body ``POST /api/missions``
    applies when the client sends only a goal. The token-cost figure is the
    cap ``ResourceScheduler.budget_for`` will enforce (env default, then hard
    cap). It is never chosen by the UI.
    """
    from .models import Mission, MissionLimits
    from .resources import ResourceScheduler, round_cost

    limits = MissionLimits()
    scheduler = ResourceScheduler()
    listed = limits.max_token_cost
    cap = scheduler.budget_for(Mission(goal="limits readout", limits=limits))
    known = isinstance(cap, (int, float)) and cap >= 0
    return {
        "available": True,
        "phase": "create_defaults",
        "max_agents": limits.max_agents,
        "max_depth": limits.max_depth,
        "max_tool_calls": limits.max_tool_calls,
        "max_runtime_seconds": limits.max_runtime_seconds,
        "max_token_cost": listed,
        "token_cost_cap": round_cost(cap) if known else None,
        "token_cost_known": bool(known),
        "token_cost_source": "listed" if listed is not None else "server_default",
        "token_cost_hard_cap": round_cost(scheduler.settings.hard_cap),
    }


async def workspace_health_status() -> dict:
    from .workspace import build_workspace_provider
    provider = build_workspace_provider()
    health = await provider.health()
    return {
        "configured": True,
        "provider": health.provider,
        "backend": health.backend,
        "status": health.status,
        "detail": health.detail,
        "root": health.root,
        "docker": False,
        "fallback": False,
    }
