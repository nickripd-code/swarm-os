from __future__ import annotations

import os
import time

from app.queue import WorkItem


def echo(item: WorkItem) -> dict:
    return {
        "text": item.payload.get("text"),
        "pid": os.getpid(),
        "attempt": item.attempt,
    }


def slow_echo(item: WorkItem) -> dict:
    time.sleep(float(item.payload.get("sleep_seconds", 0.5)))
    return echo(item)


def fail(item: WorkItem) -> dict:
    raise RuntimeError(str(item.payload.get("error") or "handler failed"))
