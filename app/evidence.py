"""Bounded external evidence runners for the finish-gate verifier.

Opt-in (`SWARM_EVIDENCE`) and fail-closed. Never invents a pass. Tests inject
fakes for HTTP and pytest so CI does not hit the network or spawn a live suite.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from .models import FailureClass
from .policy import TRUE_ENV, privacy_from_state

EVIDENCE_KINDS = frozenset({"pytest", "http", "file"})
KIND_ALIASES = {
    "test": "pytest",
    "tests": "pytest",
    "pytest": "pytest",
    "http": "http",
    "get": "http",
    "file": "file",
    "hash": "file",
    "artifact": "file",
}
ALLOWED_TEST_COMMANDS = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
)
ALLOWED_SCHEMES = frozenset({"http", "https"})
PROTECTED_PATHS = frozenset({
    "app/policy.py",
    "app/credentials.py",
    "app/payments.py",
    "app/selfmod.py",
    "app/leases.py",
})
PROTECTED_PREFIXES = (".env", "secrets/", "credentials/")
HTTP_MARKERS = frozenset({"http://", "https://", "deployed to"})
FILE_MARKERS = frozenset({"created file", "wrote file"})
MAX_STEPS = 8
MAX_PATHS = 8
MAX_PATH_BYTES = 256
MAX_URL_BYTES = 2048
MAX_SNIPPET = 500
MAX_BODY_CHARS = 4000
MAX_FILE_BYTES = 1_000_000
MAX_OUTPUT_CHARS = 2000
DEFAULT_TIMEOUT = 15.0

HttpGet = Callable[[str, float], Awaitable[dict[str, Any]]]
RunTests = Callable[[list[str], str, float], Awaitable[dict[str, Any]]]


def env_flag(name: str, raw: str | None = None) -> bool:
    text = (raw if raw is not None else os.getenv(name, "")).strip().lower()
    return text in TRUE_ENV


def evidence_opted_in(raw: str | None = None) -> bool:
    return env_flag("SWARM_EVIDENCE", raw)


def evidence_http_hosts(raw: str | None = None) -> tuple[str, ...]:
    text = raw if raw is not None else os.getenv("SWARM_EVIDENCE_HTTP_HOSTS", "")
    hosts = []
    for item in text.split(","):
        host = item.strip().lower()
        if host:
            hosts.append(host)
    return tuple(hosts)


def evidence_root(raw: str | None = None) -> Path:
    text = (raw if raw is not None else os.getenv("SWARM_EVIDENCE_ROOT", "")).strip()
    return Path(text).resolve() if text else Path.cwd().resolve()


def evidence_timeout(raw: str | None = None) -> float:
    text = (raw if raw is not None else os.getenv("SWARM_EVIDENCE_TIMEOUT", "")).strip()
    if not text:
        return DEFAULT_TIMEOUT
    try:
        value = float(text)
    except ValueError:
        return DEFAULT_TIMEOUT
    return max(0.1, min(value, 60.0))


def parse_test_command(raw: str | None = None) -> list[str] | None:
    text = (raw if raw is not None else os.getenv("SWARM_EVIDENCE_TEST_COMMAND", "pytest")).strip()
    if not text:
        text = "pytest"
    try:
        parts = tuple(shlex.split(text, posix=True))
    except ValueError:
        return None
    if parts in ALLOWED_TEST_COMMANDS:
        return list(parts)
    return None


def public_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, host, parsed.path, parsed.params, parsed.query, ""))


def public_evidence_run(run: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "kind": str(run.get("kind") or "unknown"),
        "ok": bool(run.get("ok")),
        "detail": str(run.get("detail") or "")[:MAX_SNIPPET],
    }
    failure = run.get("failure_class")
    if failure:
        payload["failure_class"] = str(failure)
    return payload


def public_evidence_runs(runs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [public_evidence_run(run) for run in (runs or [])]


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def collect_evidence_steps(state: dict[str, Any] | None, claim: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Explicit steps only. Never inferred from summary text or filesystem walks."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(items: Any) -> None:
        for item in _as_dict_list(items):
            key = repr(sorted(item.items()))
            if key in seen:
                continue
            seen.add(key)
            found.append(item)

    claim = claim or {}
    state = state or {}
    add(claim.get("evidence_steps") or claim.get("checks"))
    add(state.get("evidence_steps") or state.get("checks"))
    verification = state.get("verification")
    if isinstance(verification, dict):
        add(verification.get("steps") or verification.get("evidence_steps"))
    for task in list(state.get("tasks") or []):
        if not isinstance(task, dict) or task.get("status") != "completed":
            continue
        output = task.get("output") if isinstance(task.get("output"), dict) else {}
        add(output.get("evidence_steps") or output.get("checks"))
    return found[: MAX_STEPS + 1]


def normalize_step(raw: dict[str, Any]) -> dict[str, Any]:
    kind = KIND_ALIASES.get(str(raw.get("kind") or "").strip().lower())
    if kind is None:
        return {
            "kind": "unknown",
            "ok": False,
            "detail": "Evidence step is missing a supported kind (pytest, http, file)",
            "failure_class": str(FailureClass.VERIFICATION_FAILURE),
        }
    step: dict[str, Any] = {"kind": kind}
    if kind == "pytest":
        paths = raw.get("paths")
        if isinstance(raw.get("path"), str) and not paths:
            paths = [raw.get("path")]
        if not isinstance(paths, list) or not paths:
            return _invalid(kind, "pytest evidence requires explicit paths")
        step["paths"] = [str(path) for path in paths if path]
        return step
    if kind == "http":
        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            return _invalid(kind, "http evidence requires a url")
        step["url"] = url.strip()
        status = raw.get("status")
        if status is not None and not isinstance(status, int):
            return _invalid(kind, "http evidence status must be an integer")
        step["status"] = status
        contains = raw.get("contains")
        if contains is not None and not isinstance(contains, str):
            return _invalid(kind, "http evidence contains must be a string")
        step["contains"] = contains
        return step
    path = raw.get("path")
    if not isinstance(path, str) or not path.strip():
        return _invalid(kind, "file evidence requires a path")
    step["path"] = path.strip()
    digest = raw.get("sha256") or raw.get("hash")
    if digest is not None and not isinstance(digest, str):
        return _invalid(kind, "file evidence sha256 must be a string")
    step["sha256"] = digest.strip().lower() if isinstance(digest, str) else None
    contains = raw.get("contains")
    if contains is not None and not isinstance(contains, str):
        return _invalid(kind, "file evidence contains must be a string")
    step["contains"] = contains
    return step


def covered_fabricated_markers(steps: list[dict[str, Any]]) -> set[str]:
    kinds = {str(step.get("kind") or "") for step in steps}
    covered: set[str] = set()
    if "http" in kinds:
        covered |= HTTP_MARKERS
    if "file" in kinds:
        covered |= FILE_MARKERS
    return covered


def _invalid(kind: str, detail: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "ok": False,
        "detail": detail,
        "failure_class": str(FailureClass.VERIFICATION_FAILURE),
    }


def _fail(kind: str, detail: str, failure_class: FailureClass = FailureClass.VERIFICATION_FAILURE) -> dict[str, Any]:
    return {
        "kind": kind,
        "ok": False,
        "detail": detail,
        "failure_class": str(failure_class),
    }


def _ok(kind: str, detail: str) -> dict[str, Any]:
    return {"kind": kind, "ok": True, "detail": detail}


def normalize_relpath(value: str) -> str | None:
    raw = value.strip().replace("\\", "/")
    if not raw or len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        return None
    if raw.startswith("/") or raw.startswith("~") or ":" in raw:
        return None
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def path_is_protected(relpath: str) -> bool:
    lowered = relpath.lower()
    if lowered in PROTECTED_PATHS:
        return True
    return any(lowered == prefix.rstrip("/") or lowered.startswith(prefix) for prefix in PROTECTED_PREFIXES)


class EvidenceRunner:
    """Concrete checks the verifier can call. Missing config never counts as a pass."""

    def __init__(
        self,
        *,
        opted_in: bool | None = None,
        http_hosts: tuple[str, ...] | None = None,
        root: Path | str | None = None,
        test_command: list[str] | None = None,
        timeout: float | None = None,
        http_get: HttpGet | None = None,
        run_tests: RunTests | None = None,
    ):
        self._opted_in = evidence_opted_in() if opted_in is None else opted_in
        self._http_hosts = evidence_http_hosts() if http_hosts is None else tuple(
            host.strip().lower() for host in http_hosts if host and host.strip()
        )
        self._root = Path(root).resolve() if root is not None else evidence_root()
        parsed_command = parse_test_command() if test_command is None else (
            list(test_command) if tuple(test_command) in ALLOWED_TEST_COMMANDS else None
        )
        self._test_command = parsed_command
        self._timeout = evidence_timeout() if timeout is None else max(0.1, min(float(timeout), 60.0))
        self.http_get = http_get
        self.run_tests = run_tests

    def configured(self) -> bool:
        return self._opted_in

    async def run(self, steps: list[dict[str, Any]], state: dict[str, Any] | None = None) -> dict[str, Any]:
        if not steps:
            return {"ok": True, "runs": [], "rationale": "No external evidence steps were requested"}
        if len(steps) > MAX_STEPS:
            run = _fail("unknown", "Too many evidence steps")
            return {"ok": False, "runs": [run], "rationale": run["detail"]}
        if not self._opted_in:
            runs = [
                _fail(str(step.get("kind") or "unknown"), "Evidence runners are not configured")
                for step in steps
            ]
            return {
                "ok": False,
                "runs": runs,
                "rationale": "Evidence steps were requested but SWARM_EVIDENCE is not enabled",
            }
        privacy = privacy_from_state(state)
        runs: list[dict[str, Any]] = []
        for raw in steps:
            step = normalize_step(raw)
            if step.get("ok") is False:
                runs.append(step)
                continue
            kind = step["kind"]
            if kind == "pytest":
                runs.append(await self._run_pytest(step))
            elif kind == "http":
                runs.append(await self._run_http(step, privacy))
            else:
                runs.append(await self._run_file(step))
        failed = next((run for run in runs if not run.get("ok")), None)
        if failed:
            return {
                "ok": False,
                "runs": [public_evidence_run(run) for run in runs],
                "rationale": str(failed.get("detail") or "External evidence failed"),
            }
        return {
            "ok": True,
            "runs": [public_evidence_run(run) for run in runs],
            "rationale": "External evidence checks passed; model verification is still required",
        }

    async def _run_pytest(self, step: dict[str, Any]) -> dict[str, Any]:
        if self._test_command is None:
            return _fail("pytest", "pytest evidence command is not allowlisted")
        raw_paths = list(step.get("paths") or [])
        if not raw_paths or len(raw_paths) > MAX_PATHS:
            return _fail("pytest", "pytest evidence requires 1–8 explicit paths")
        rels: list[str] = []
        for raw in raw_paths:
            rel = normalize_relpath(str(raw))
            if rel is None or self._contained_rel(rel) is None:
                return _fail("pytest", "pytest path is outside the evidence root")
            rels.append(rel)
        command = [*self._test_command, "-q", *rels]
        runner = self.run_tests or _default_run_tests
        try:
            result = await runner(command, str(self._root), self._timeout)
        except Exception:
            return _fail("pytest", "pytest evidence runner failed")
        if not isinstance(result, dict):
            return _fail("pytest", "pytest evidence runner returned an invalid result")
        if result.get("timed_out"):
            return _fail("pytest", "pytest evidence timed out", FailureClass.TIMEOUT)
        code = result.get("returncode")
        if code != 0:
            return _fail("pytest", f"pytest evidence failed (exit {code})")
        return _ok("pytest", "pytest evidence passed on " + ", ".join(rels))

    async def _run_http(self, step: dict[str, Any], privacy: str) -> dict[str, Any]:
        if privacy == "local_only":
            return _fail("http", "local_only policy forbids HTTP evidence", FailureClass.POLICY_REFUSAL)
        if not self._http_hosts:
            return _fail("http", "HTTP evidence host allowlist is not configured")
        url = step.get("url")
        if not isinstance(url, str) or len(url.encode("utf-8")) > MAX_URL_BYTES:
            return _fail("http", "HTTP evidence url is invalid")
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.hostname:
            return _fail("http", "HTTP evidence allows only http(s) URLs with a host")
        if parsed.username or parsed.password:
            return _fail("http", "HTTP evidence URLs must not include credentials")
        host = parsed.hostname.lower()
        allowed = host in self._http_hosts
        if parsed.port:
            allowed = allowed or f"{host}:{parsed.port}" in self._http_hosts
        if not allowed:
            return _fail("http", "HTTP evidence host is not allowlisted")
        getter = self.http_get or _default_http_get
        try:
            result = await getter(url.strip(), self._timeout)
        except TimeoutError:
            return _fail("http", "HTTP evidence timed out", FailureClass.TIMEOUT)
        except Exception:
            return _fail("http", "HTTP evidence request failed")
        if not isinstance(result, dict):
            return _fail("http", "HTTP evidence runner returned an invalid result")
        if result.get("timed_out") or result.get("error") == "timeout":
            return _fail("http", "HTTP evidence timed out", FailureClass.TIMEOUT)
        status = result.get("status")
        if not isinstance(status, int):
            return _fail("http", "HTTP evidence omitted a status code")
        expected = step.get("status")
        if expected is not None:
            if status != expected:
                return _fail("http", f"HTTP evidence expected status {expected}, got {status}")
        elif status < 200 or status >= 300:
            return _fail("http", f"HTTP evidence expected 2xx, got {status}")
        body = result.get("body") if isinstance(result.get("body"), str) else ""
        contains = step.get("contains")
        if contains and contains not in body:
            return _fail("http", "HTTP evidence body did not contain the expected snippet")
        return _ok("http", f"GET {public_url(url.strip())} → {status}")

    def _contained_rel(self, rel: str) -> str | None:
        """Reject traversal, symlinks, and aliases onto protected paths."""
        if path_is_protected(rel):
            return None
        current = self._root
        for part in rel.split("/"):
            current = current / part
            try:
                if current.is_symlink():
                    return None
                current.resolve().relative_to(self._root)
            except (OSError, ValueError):
                return None
        try:
            resolved_rel = current.resolve().relative_to(self._root).as_posix()
        except (OSError, ValueError):
            return None
        if path_is_protected(resolved_rel):
            return None
        return rel

    async def _run_file(self, step: dict[str, Any]) -> dict[str, Any]:
        rel = normalize_relpath(str(step.get("path") or ""))
        if rel is None or self._contained_rel(rel) is None:
            return _fail("file", "file evidence path is not allowed")
        resolved = (self._root / rel).resolve()
        if not resolved.is_file():
            return _fail("file", "file evidence artifact is missing")
        try:
            size = resolved.stat().st_size
        except OSError:
            return _fail("file", "file evidence artifact could not be read")
        if size > MAX_FILE_BYTES:
            return _fail("file", "file evidence artifact exceeds the size limit")
        try:
            data = resolved.read_bytes()
        except OSError:
            return _fail("file", "file evidence artifact could not be read")
        digest = hashlib.sha256(data).hexdigest()
        expected = step.get("sha256")
        if expected and digest != expected:
            return _fail("file", "file evidence hash did not match")
        contains = step.get("contains")
        if contains:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return _fail("file", "file evidence artifact is not utf-8 text")
            if contains not in text:
                return _fail("file", "file evidence did not contain the expected snippet")
        detail = f"file {rel} sha256={digest}"
        return _ok("file", detail)


async def _default_http_get(url: str, timeout: float) -> dict[str, Any]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return {"status": None, "body": "", "timed_out": True, "error": "timeout"}
    except httpx.RequestError:
        return {"status": None, "body": "", "error": "request_failed"}
    return {
        "status": response.status_code,
        "body": (response.text or "")[:MAX_BODY_CHARS],
        "timed_out": False,
    }


async def _default_run_tests(command: list[str], cwd: str, timeout: float) -> dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return {"returncode": 127, "timed_out": False, "output": "pytest executable was not found"}
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"returncode": None, "timed_out": True, "output": ""}
    output = (stdout or b"").decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
    return {"returncode": proc.returncode, "timed_out": False, "output": output}
