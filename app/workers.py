"""Spawn-safe OS worker processes backed by the durable :mod:`app.queue`.

Trusted host code configures handlers as ``"module.path:callable"`` references
so the configuration can cross Python's ``spawn`` boundary on every supported OS.
Each child opens its own Store/WorkQueue and owns only the leases it claims.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import multiprocessing
import os
import queue as stdlib_queue
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from .leases import LeaseConflict, LeaseError
from .queue import QueueError, WorkItem, WorkQueue
from .store import Store

DEFAULT_PROCESS_COUNT = 1
DEFAULT_POLL_INTERVAL_SECONDS = 0.05
DEFAULT_LEASE_TTL_SECONDS = 30.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0

WorkHandler = Callable[[WorkItem], dict[str, Any] | None]


class WorkerPoolError(RuntimeError):
    """The process pool configuration or lifecycle is invalid."""


@dataclass(frozen=True)
class WorkerIdentity:
    pid: int
    owner_id: str


@dataclass(frozen=True)
class _WorkerConfig:
    database_path: str
    handlers: tuple[tuple[str, str], ...]
    mission_id: str | None
    poll_interval_seconds: float
    lease_ttl_seconds: float
    heartbeat_interval_seconds: float


def _load_handler(reference: str) -> WorkHandler:
    module_name, separator, attribute_path = reference.partition(":")
    if not separator or not module_name or not attribute_path:
        raise WorkerPoolError(
            f"Handler reference {reference!r} must use 'module.path:callable'"
        )
    try:
        value: Any = importlib.import_module(module_name)
        for name in attribute_path.split("."):
            value = getattr(value, name)
    except (AttributeError, ImportError) as exc:
        raise WorkerPoolError(f"Handler reference {reference!r} cannot be loaded") from exc
    if not callable(value):
        raise WorkerPoolError(f"Handler reference {reference!r} is not callable")
    return value


def _invoke_handler(handler: WorkHandler, item: WorkItem) -> dict[str, Any]:
    result = handler(item)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise WorkerPoolError("Work handler result must be an object or None")
    return result


def _report_failure(queue: WorkQueue, item: WorkItem, owner_id: str, exc: BaseException) -> None:
    """Persist a real failure when the owner still holds a live lease."""
    error = str(exc).strip() or type(exc).__name__
    try:
        queue.fail(
            item.id,
            owner_id,
            {
                "error": error[:1000],
                "failure_class": "TOOL_FAILURE",
            },
            mission_id=item.mission_id,
        )
    except (LeaseConflict, LeaseError, QueueError, OperationalError):
        # A lost/unknown lease must never be converted into a terminal result.
        return


def _execute_claimed(
    queue: WorkQueue,
    item: WorkItem,
    owner_id: str,
    handler: WorkHandler,
    config: _WorkerConfig,
) -> None:
    lease_live = True
    failure: BaseException | None = None
    result: dict[str, Any] | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="swarm-job") as executor:
        future = executor.submit(_invoke_handler, handler, item)
        while True:
            try:
                result = future.result(timeout=config.heartbeat_interval_seconds)
                break
            except FutureTimeout:
                try:
                    renewed = queue.heartbeat(
                        item.id,
                        owner_id,
                        ttl_seconds=config.lease_ttl_seconds,
                    )
                    if renewed.owner_id != owner_id:
                        lease_live = False
                        break
                except (LeaseConflict, LeaseError, QueueError, OperationalError):
                    lease_live = False
                    break
            except BaseException as exc:  # handler errors are durable job failures
                failure = exc
                break

    if not lease_live:
        return
    if failure is not None:
        _report_failure(queue, item, owner_id, failure)
        return
    try:
        queue.complete(item.id, owner_id, result=result)
    except (LeaseConflict, LeaseError, QueueError, OperationalError):
        # Completion is authoritative only when WorkQueue accepts the live owner.
        return


def _worker_main(config: _WorkerConfig, stop_event: Any, ready_queue: Any) -> None:
    pid = os.getpid()
    owner_id = str(uuid4())
    try:
        store = Store(config.database_path)
        queue = WorkQueue(store)
        handlers = {kind: _load_handler(reference) for kind, reference in config.handlers}
        ready_queue.put(("ready", pid, owner_id))
        while not stop_event.is_set():
            try:
                claimed = queue.claim(
                    owner_id=owner_id,
                    mission_id=config.mission_id,
                    kinds=handlers,
                    ttl_seconds=config.lease_ttl_seconds,
                )
            except (LeaseConflict, OperationalError):
                stop_event.wait(config.poll_interval_seconds)
                continue
            if claimed is None:
                stop_event.wait(config.poll_interval_seconds)
                continue
            item = claimed.item
            handler = handlers.get(item.kind)
            if handler is None:
                _report_failure(
                    queue,
                    item,
                    owner_id,
                    WorkerPoolError(f"No handler is registered for work kind {item.kind!r}"),
                )
                continue
            _execute_claimed(queue, item, owner_id, handler, config)
    except BaseException as exc:
        message = str(exc).strip() or type(exc).__name__
        ready_queue.put(("fatal", pid, message[:1000]))
        raise


class ProcessWorkerPool:
    """Manage a fixed set of durable queue consumers in separate OS processes."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        handlers: Mapping[str, str],
        *,
        process_count: int = DEFAULT_PROCESS_COUNT,
        mission_id: str | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        lease_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        start_method: str = "spawn",
    ):
        if str(database_path) == ":memory:":
            raise WorkerPoolError("Out-of-process workers require a filesystem database")
        if process_count <= 0:
            raise WorkerPoolError("Process count must be positive")
        if poll_interval_seconds <= 0:
            raise WorkerPoolError("Poll interval must be positive")
        if lease_ttl_seconds <= 0:
            raise WorkerPoolError("Lease TTL must be positive")
        if heartbeat_interval_seconds <= 0:
            raise WorkerPoolError("Heartbeat interval must be positive")
        if heartbeat_interval_seconds >= lease_ttl_seconds:
            raise WorkerPoolError("Heartbeat interval must be shorter than the lease TTL")
        normalized: list[tuple[str, str]] = []
        for kind, reference in handlers.items():
            clean_kind = str(kind).strip()
            clean_reference = str(reference).strip()
            if not clean_kind or not clean_reference:
                raise WorkerPoolError("Handler kinds and references must be non-empty")
            _load_handler(clean_reference)
            normalized.append((clean_kind, clean_reference))
        if not normalized:
            raise WorkerPoolError("At least one work handler is required")

        self._context = multiprocessing.get_context(start_method)
        self._config = _WorkerConfig(
            database_path=str(Path(database_path).resolve()),
            handlers=tuple(sorted(normalized)),
            mission_id=mission_id,
            poll_interval_seconds=poll_interval_seconds,
            lease_ttl_seconds=lease_ttl_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )
        self._process_count = process_count
        self._stop_event = self._context.Event()
        self._ready_queue = self._context.Queue()
        self._processes: list[Any] = []
        self._workers: list[WorkerIdentity] = []

    @property
    def workers(self) -> tuple[WorkerIdentity, ...]:
        return tuple(self._workers)

    @property
    def running(self) -> bool:
        return bool(self._processes) and all(process.is_alive() for process in self._processes)

    def start(self, *, timeout_seconds: float = 10.0) -> tuple[WorkerIdentity, ...]:
        if self._processes:
            raise WorkerPoolError("Worker pool has already been started")
        if timeout_seconds <= 0:
            raise WorkerPoolError("Startup timeout must be positive")

        # Apply migrations once before children concurrently open the database.
        bootstrap = Store(self._config.database_path)
        bootstrap.engine.dispose()
        self._stop_event.clear()
        for index in range(self._process_count):
            process = self._context.Process(
                target=_worker_main,
                args=(self._config, self._stop_event, self._ready_queue),
                name=f"swarm-worker-{index + 1}",
            )
            process.start()
            self._processes.append(process)

        deadline = time.monotonic() + timeout_seconds
        try:
            while len(self._workers) < self._process_count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkerPoolError("Timed out waiting for worker processes to start")
                try:
                    state, pid, detail = self._ready_queue.get(timeout=min(remaining, 0.1))
                except stdlib_queue.Empty:
                    failed = [p for p in self._processes if p.exitcode not in (None, 0)]
                    if failed:
                        raise WorkerPoolError(
                            f"Worker process exited during startup with code {failed[0].exitcode}"
                        )
                    continue
                if state == "fatal":
                    raise WorkerPoolError(f"Worker process {pid} failed to start: {detail}")
                if state == "ready":
                    self._workers.append(WorkerIdentity(pid=pid, owner_id=detail))
        except BaseException:
            self.stop(timeout_seconds=2.0)
            raise
        return self.workers

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds < 0:
            raise WorkerPoolError("Shutdown timeout cannot be negative")
        self._stop_event.set()
        deadline = time.monotonic() + timeout_seconds
        for process in self._processes:
            process.join(max(0.0, deadline - time.monotonic()))
        for process in self._processes:
            if process.is_alive():
                process.terminate()
        for process in self._processes:
            process.join(2.0)
        self._processes.clear()
        self._workers.clear()

    def __enter__(self) -> ProcessWorkerPool:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()
