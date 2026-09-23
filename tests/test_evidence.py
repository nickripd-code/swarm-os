import hashlib

import pytest

from app.evidence import EvidenceRunner, collect_evidence_steps, evidence_opted_in
from app.llm import OpenAIProvider
from app.models import FailureClass, Mission
from app.router import ModelRouter
from app.runtime import SwarmRuntime
from app.store import Store
from app.verifier import check_claim_with_evidence, local_evidence_check
from tests.test_router import openai_like


class FakeHttp:
    def __init__(self, status=200, body="ok", timed_out=False, error=None, calls=None):
        self.status = status
        self.body = body
        self.timed_out = timed_out
        self.error = error
        self.calls = calls if calls is not None else []

    async def __call__(self, url: str, timeout: float):
        self.calls.append((url, timeout))
        if self.timed_out:
            return {"status": None, "body": "", "timed_out": True, "error": "timeout"}
        if self.error:
            raise RuntimeError(self.error)
        return {"status": self.status, "body": self.body, "timed_out": False}


class FakeTests:
    def __init__(self, returncode=0, timed_out=False):
        self.returncode = returncode
        self.timed_out = timed_out
        self.calls = []

    async def __call__(self, command: list[str], cwd: str, timeout: float):
        self.calls.append((command, cwd, timeout))
        if self.timed_out:
            return {"returncode": None, "timed_out": True, "output": ""}
        return {"returncode": self.returncode, "timed_out": False, "output": "1 passed"}


def _runner(tmp_path, **kwargs):
    kwargs.setdefault("opted_in", True)
    kwargs.setdefault("root", tmp_path)
    kwargs.setdefault("http_hosts", ("example.com",))
    kwargs.setdefault("test_command", ["pytest"])
    kwargs.setdefault("http_get", FakeHttp())
    kwargs.setdefault("run_tests", FakeTests())
    return EvidenceRunner(**kwargs)


def test_evidence_opt_in_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SWARM_EVIDENCE", raising=False)
    assert evidence_opted_in() is False
    assert EvidenceRunner().configured() is False


@pytest.mark.asyncio
async def test_missing_config_fails_closed(tmp_path):
    runner = _runner(tmp_path, opted_in=False)
    result = await runner.run([{"kind": "pytest", "paths": ["tests/test_x.py"]}])
    assert result["ok"] is False
    assert "SWARM_EVIDENCE is not enabled" in result["rationale"]
    assert result["runs"][0]["failure_class"] == FailureClass.VERIFICATION_FAILURE
    assert runner.run_tests.calls == []


@pytest.mark.asyncio
async def test_pytest_pass_and_fail_use_fakes(tmp_path):
    passing = FakeTests(returncode=0)
    ok = await _runner(tmp_path, run_tests=passing).run(
        [{"kind": "pytest", "paths": ["tests/test_ok.py"]}],
    )
    assert ok["ok"] is True
    assert passing.calls[0][0][:3] == ["pytest", "-q", "tests/test_ok.py"]
    failing = FakeTests(returncode=1)
    bad = await _runner(tmp_path, run_tests=failing).run(
        [{"kind": "tests", "path": "tests/test_bad.py"}],
    )
    assert bad["ok"] is False
    assert "failed" in bad["rationale"]


@pytest.mark.asyncio
async def test_pytest_timeout_fails_closed(tmp_path):
    result = await _runner(tmp_path, run_tests=FakeTests(timed_out=True)).run(
        [{"kind": "pytest", "paths": ["tests/test_slow.py"]}],
    )
    assert result["ok"] is False
    assert result["runs"][0]["failure_class"] == FailureClass.TIMEOUT


@pytest.mark.asyncio
async def test_http_pass_and_non_2xx_fail(tmp_path):
    http = FakeHttp(status=200, body="healthy")
    ok = await _runner(tmp_path, http_get=http).run(
        [{"kind": "http", "url": "https://example.com/health", "contains": "healthy"}],
    )
    assert ok["ok"] is True
    assert http.calls[0][0] == "https://example.com/health"
    bad = await _runner(tmp_path, http_get=FakeHttp(status=503, body="down")).run(
        [{"kind": "get", "url": "https://example.com/health"}],
    )
    assert bad["ok"] is False
    assert "503" in bad["rationale"]


@pytest.mark.asyncio
async def test_http_missing_snippet_and_timeout_fail(tmp_path):
    missing = await _runner(tmp_path, http_get=FakeHttp(body="nope")).run(
        [{"kind": "http", "url": "https://example.com/x", "contains": "expected"}],
    )
    assert missing["ok"] is False
    timed = await _runner(tmp_path, http_get=FakeHttp(timed_out=True)).run(
        [{"kind": "http", "url": "https://example.com/x"}],
    )
    assert timed["ok"] is False
    assert timed["runs"][0]["failure_class"] == FailureClass.TIMEOUT


@pytest.mark.asyncio
async def test_http_without_allowlist_or_unlisted_host_fails_closed(tmp_path):
    missing_hosts = await _runner(tmp_path, http_hosts=()).run(
        [{"kind": "http", "url": "https://example.com/x"}],
    )
    assert missing_hosts["ok"] is False
    assert "allowlist" in missing_hosts["rationale"]
    other = await _runner(tmp_path, http_hosts=("allowed.test",)).run(
        [{"kind": "http", "url": "https://example.com/x"}],
    )
    assert other["ok"] is False
    assert "not allowlisted" in other["rationale"]


@pytest.mark.asyncio
async def test_http_local_only_and_credentials_fail_closed(tmp_path):
    local = await _runner(tmp_path).run(
        [{"kind": "http", "url": "https://example.com/x"}],
        {"privacy": "local_only"},
    )
    assert local["ok"] is False
    assert local["runs"][0]["failure_class"] == FailureClass.POLICY_REFUSAL
    creds = await _runner(tmp_path).run(
        [{"kind": "http", "url": "https://user:secret@example.com/x"}],
    )
    assert creds["ok"] is False
    assert "credentials" in creds["rationale"]


@pytest.mark.asyncio
async def test_file_hash_and_read_pass(tmp_path):
    artifact = tmp_path / "out" / "report.txt"
    artifact.parent.mkdir()
    artifact.write_text("shipped v1", encoding="utf-8")
    digest = hashlib.sha256(b"shipped v1").hexdigest()
    result = await _runner(tmp_path).run(
        [{"kind": "file", "path": "out/report.txt", "sha256": digest, "contains": "shipped"}],
    )
    assert result["ok"] is True
    assert digest in result["runs"][0]["detail"]


@pytest.mark.asyncio
async def test_missing_file_and_hash_mismatch_fail(tmp_path):
    missing = await _runner(tmp_path).run([{"kind": "file", "path": "out/missing.txt"}])
    assert missing["ok"] is False
    assert "missing" in missing["rationale"]
    (tmp_path / "out.txt").write_text("a", encoding="utf-8")
    mismatch = await _runner(tmp_path).run(
        [{"kind": "hash", "path": "out.txt", "sha256": "00" * 32}],
    )
    assert mismatch["ok"] is False
    assert "hash" in mismatch["rationale"]


@pytest.mark.asyncio
async def test_file_traversal_and_protected_paths_fail_closed(tmp_path):
    traversal = await _runner(tmp_path).run([{"kind": "file", "path": "../secrets.txt"}])
    assert traversal["ok"] is False
    protected = await _runner(tmp_path).run([{"kind": "file", "path": ".env"}])
    assert protected["ok"] is False


@pytest.mark.asyncio
async def test_github_host_is_not_an_implicit_evidence_allowlist(tmp_path):
    result = await _runner(tmp_path).run(
        [{"kind": "http", "url": "https://api.github.com/repos/nickripd-code/swarm-os"}],
    )
    assert result["ok"] is False
    assert "not allowlisted" in result["rationale"]


@pytest.mark.asyncio
async def test_symlink_file_evidence_fails_closed_without_reading_the_target(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("OPENAI_API_KEY=hidden", encoding="utf-8")
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("outside", encoding="utf-8")
    alias = tmp_path / "notes"
    alias.mkdir()
    (alias / "leak").symlink_to(secret)
    (tmp_path / "escape").symlink_to(outside)
    tests = FakeTests()
    runner = _runner(tmp_path, run_tests=tests)
    leaked = await runner.run([{"kind": "file", "path": "notes/leak", "contains": "OPENAI_API_KEY"}])
    escaped = await runner.run([{"kind": "file", "path": "escape"}])
    pytest_link = tmp_path / "tests"
    pytest_link.mkdir()
    (pytest_link / "test_link.py").symlink_to(secret)
    linked_test = await runner.run([{"kind": "pytest", "paths": ["tests/test_link.py"]}])
    assert leaked["ok"] is False
    assert escaped["ok"] is False
    assert linked_test["ok"] is False
    assert "OPENAI_API_KEY" not in leaked["rationale"]
    assert "hidden" not in leaked["rationale"]
    assert outside.read_text(encoding="utf-8") == "outside"
    assert tests.calls == []


@pytest.mark.asyncio
async def test_unknown_kind_fails_closed(tmp_path):
    result = await _runner(tmp_path).run([{"kind": "shell", "command": "rm -rf /"}])
    assert result["ok"] is False
    assert result["runs"][0]["kind"] == "unknown"


def test_collect_steps_from_claim_and_task_artifacts_only():
    state = {
        "tasks": [
            {
                "status": "completed",
                "output": {"finding": "built", "evidence_steps": [
                    {"kind": "file", "path": "out/a.txt"},
                ]},
            },
            {"status": "running", "output": {"evidence_steps": [{"kind": "http", "url": "https://evil.test"}]}},
        ],
    }
    claim = {"summary": "done", "checks": [{"kind": "pytest", "paths": ["tests/test_a.py"]}]}
    steps = collect_evidence_steps(state, claim)
    kinds = {step["kind"] for step in steps}
    assert kinds == {"file", "pytest"}


@pytest.mark.asyncio
async def test_openai_only_without_steps_still_calls_the_model(tmp_path):
    openai = openai_like()
    controller = OpenAIProvider(
        model_provider=openai,
        router=ModelRouter([openai]),
        evidence=_runner(tmp_path, opted_in=False),
    )
    result = await controller.verify(
        {"goal": "Write a short answer", "agents": [], "tasks": []},
        {"summary": "A concise text answer"},
    )
    assert result["verdict"] == "pass"
    assert openai.calls == 1
    assert "evidence_runs" not in result


@pytest.mark.asyncio
async def test_missing_config_does_not_call_the_model(tmp_path):
    openai = openai_like()
    controller = OpenAIProvider(
        model_provider=openai,
        router=ModelRouter([openai]),
        evidence=_runner(tmp_path, opted_in=False),
    )
    result = await controller.verify(
        {"goal": "Prove the tests ran", "agents": [], "tasks": []},
        {"summary": "Tests passed", "evidence_steps": [{"kind": "pytest", "paths": ["tests/test_a.py"]}]},
    )
    assert result["verdict"] == "fail"
    assert openai.calls == 0
    assert result["evidence_runs"][0]["ok"] is False


@pytest.mark.asyncio
async def test_evidence_pass_still_requires_model_verdict(tmp_path):
    openai = openai_like(verify_output={
        "verdict": "inconclusive",
        "rationale": "Text claim is still unproven",
        "evidence": [],
    })
    controller = OpenAIProvider(
        model_provider=openai,
        router=ModelRouter([openai]),
        evidence=_runner(tmp_path),
    )
    result = await controller.verify(
        {"goal": "Prove the tests ran", "agents": [], "tasks": []},
        {"summary": "Tests passed", "evidence_steps": [{"kind": "pytest", "paths": ["tests/test_a.py"]}]},
    )
    assert result["verdict"] == "inconclusive"
    assert openai.calls == 1
    assert result["evidence_runs"][0]["ok"] is True


@pytest.mark.asyncio
async def test_http_evidence_allows_matching_url_claim_then_model_runs(tmp_path):
    openai = openai_like()
    controller = OpenAIProvider(
        model_provider=openai,
        router=ModelRouter([openai]),
        evidence=_runner(tmp_path, http_get=FakeHttp(status=200, body="ok")),
    )
    result = await controller.verify(
        {"goal": "Check the endpoint", "agents": [], "tasks": []},
        {
            "summary": "Deployed to https://example.com/health",
            "evidence_steps": [{"kind": "http", "url": "https://example.com/health", "contains": "ok"}],
        },
    )
    assert result["verdict"] == "pass"
    assert openai.calls == 1


@pytest.mark.asyncio
async def test_finish_with_failed_evidence_emits_additive_events(tmp_path):
    openai = openai_like(output={
        "action": "finish",
        "summary": "Tests passed",
        "evidence_steps": [{"kind": "pytest", "paths": ["tests/test_a.py"]}],
    })
    controller = OpenAIProvider(
        model_provider=openai,
        router=ModelRouter([openai]),
        evidence=_runner(tmp_path, run_tests=FakeTests(returncode=1)),
    )
    store = Store(str(tmp_path / "swarm.db"))
    runtime = SwarmRuntime(store, controller=controller)
    mission = Mission(goal="Do not complete when pytest fails")
    store.save_mission(mission)
    await runtime.run(mission)
    saved = store.get_mission(mission.id)
    assert saved.status == "failed"
    assert saved.result["failure_class"] == "VERIFICATION_FAILURE"
    events = store.events(mission.id)
    types = [e.event_type for e in events]
    assert "verification.evidence.started" in types
    assert "verification.evidence.failed" in types
    assert "verification.failed" in types
    assert "verification.passed" not in types
    assert "mission.completed" not in types
    assert openai.calls == 1  # decide only; verify does not call the model


def test_url_claim_without_http_step_still_fails_local_precheck():
    result = local_evidence_check(
        {"goal": "Ship", "agents": [], "tasks": []},
        {"summary": "Deployed to https://example.com"},
    )
    assert result["verdict"] == "fail"


@pytest.mark.asyncio
async def test_check_claim_collects_task_artifact_steps(tmp_path):
    artifact = tmp_path / "out.txt"
    artifact.write_text("hello", encoding="utf-8")
    state = {
        "goal": "Write a file",
        "agents": [],
        "tasks": [{
            "status": "completed",
            "output": {
                "finding": "wrote out.txt",
                "evidence_steps": [{"kind": "file", "path": "out.txt", "contains": "hello"}],
            },
        }],
    }
    result = await check_claim_with_evidence(
        state,
        {"summary": "Created file out.txt with hello"},
        runner=_runner(tmp_path),
    )
    assert result["verdict"] == "pass"
    assert result["evidence_runs"][0]["ok"] is True
