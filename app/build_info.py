"""Pass through a version the process already declares.

This module does not read git, package metadata, or a fallback string.
"""
from __future__ import annotations


def reported_version(value: object) -> str | None:
    """Return a declared version, or None when it is missing or blank."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
