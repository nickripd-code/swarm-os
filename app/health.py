from __future__ import annotations

import os
from .credentials import (
    get_api_key, get_anthropic_api_key, get_cohere_api_key, get_deepseek_api_key,
    get_gemini_api_key, get_groq_api_key, get_mistral_api_key, get_openrouter_api_key,
    get_together_api_key, get_xai_api_key,
)
from .llm import (
    DEFAULT_ANTHROPIC_BASE_URL, DEFAULT_ANTHROPIC_MODEL, DEFAULT_COHERE_BASE_URL,
    DEFAULT_COHERE_MODEL, DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_GEMINI_BASE_URL, DEFAULT_GEMINI_MODEL, DEFAULT_GROQ_BASE_URL,
    DEFAULT_GROQ_MODEL, DEFAULT_LLAMACPP_BASE_URL, DEFAULT_MODEL,
    DEFAULT_MISTRAL_BASE_URL, DEFAULT_MISTRAL_MODEL, DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OPENROUTER_MODEL, DEFAULT_REASONING, DEFAULT_TOGETHER_BASE_URL,
    DEFAULT_TOGETHER_MODEL, DEFAULT_VLLM_BASE_URL,
    DEFAULT_XAI_MODEL, DEFAULT_XAI_BASE_URL,
    LlamaCppModelProvider, OllamaModelProvider, VllmModelProvider,
    llamacpp_opted_in, ollama_opted_in, vllm_opted_in,
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
