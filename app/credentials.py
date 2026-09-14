"""Project-scoped API key storage; never expose credentials through HTTP."""
from __future__ import annotations

import getpass
import hashlib
import os
from pathlib import Path
import sys

TARGET = "AgentSwarm/OpenAI/" + hashlib.sha256(str(Path(__file__).resolve().parent.parent).lower().encode()).hexdigest()[:20]


def get_openrouter_api_key() -> str | None:
    key = os.getenv("OPENROUTER_API_KEY")
    return key.strip() if key else None


def get_xai_api_key() -> str | None:
    key = os.getenv("XAI_API_KEY")
    return key.strip() if key else None


def get_anthropic_api_key() -> str | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    return key.strip() if key else None


def get_mistral_api_key() -> str | None:
    key = os.getenv("MISTRAL_API_KEY")
    return key.strip() if key else None


def get_gemini_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    return key.strip() if key else None


def get_api_key() -> str | None:
    if os.getenv("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"].strip()
    if sys.platform != "win32":
        return None
    import win32cred
    import pywintypes
    try:
        credential = win32cred.CredRead(TARGET, win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as exc:
        if exc.winerror == 1168:  # No credential saved for this project.
            return None
        raise RuntimeError("Windows Credential Manager is unavailable") from None
    blob = credential["CredentialBlob"]
    return blob.decode("utf-16-le") if isinstance(blob, bytes) else blob


def save_api_key(key: str) -> None:
    key = key.strip().replace("\\_", "_")  # Accept Markdown-escaped underscores.
    if not key.startswith("sk-") or any(c.isspace() for c in key):
        raise ValueError("Invalid API key format")
    if sys.platform != "win32":
        raise RuntimeError("Use OPENAI_API_KEY on this platform")
    import win32cred
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC, "TargetName": TARGET,
        "UserName": "OpenAI API", "CredentialBlob": key,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "Local Agent Swarm project API key",
    }, 0)


if __name__ == "__main__":
    secret = sys.stdin.readline() if "--stdin" in sys.argv else getpass.getpass("OpenAI API key (hidden): ")
    save_api_key(secret)
    del secret
    print("API key saved in Windows Credential Manager for this project.")
