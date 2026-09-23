"""Read-only verification chip: only a recorded verdict, never an invented pass."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "verification_chip_cases.mjs"
UNAVAILABLE = "UNAVAILABLE"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the verification chip harness")
    result = subprocess.run(
        ["node", str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def cases() -> dict:
    return _load_cases()


def test_chip_stays_hidden_without_a_recorded_verification(cases):
    for name in ("noMission", "missingState", "preview", "noVerification", "completedWithoutVerification",
                 "evidenceOnly", "llmKindIsNotAVerdict", "replayBefore"):
        view = cases[name]
        assert view["visible"] is False
        assert view["status"] is None
        assert view["label"] == ""
        assert view["known"] is False


def test_started_is_pending_and_evidence_does_not_count_as_pass(cases):
    assert cases["started"] == {"visible": True, "known": True, "status": "pending", "label": "PENDING"}
    assert cases["evidenceDoesNotUpgradePending"]["status"] == "pending"
    assert cases["replayPending"]["status"] == "pending"
    assert cases["replayEvidenceStaysPending"]["status"] == "pending"
    assert cases["lastStartedClearsPass"]["status"] == "pending"


def test_pass_and_fail_come_only_from_matching_verdicts(cases):
    assert cases["pass"]["status"] == "pass"
    assert cases["pass"]["label"] == "PASS"
    assert cases["replayPass"]["label"] == "PASS"
    assert cases["lastPassReplacesFail"]["status"] == "pass"
    assert cases["fail"] == {"visible": True, "known": True, "status": "fail", "label": "FAIL"}
    assert cases["inconclusive"]["status"] == "inconclusive"
    assert cases["inconclusive"]["label"] == "INCONCLUSIVE"
    assert cases["evidenceDoesNotDowngradePass"]["status"] == "pass"
    assert cases["duplicateDoesNotReplace"]["status"] == "pass"


def test_unreadable_verdict_is_unavailable_not_a_pass(cases):
    for name in (
        "missingVerdict", "nullPayload", "listPayload", "wrongCase", "spaced",
        "numericVerdict", "passOnFailed", "failOnPassed", "pendingVerdictOnFailed",
    ):
        view = cases[name]
        assert view["visible"] is True
        assert view["known"] is False
        assert view["status"] == "unavailable"
        assert view["label"] == UNAVAILABLE
        assert view["label"] != "PASS"
    assert cases["unavailable"] == UNAVAILABLE


def test_shell_mounts_a_hidden_chip_and_does_not_invent_a_verdict():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    assert 'id="verificationChip" class="hud-chip status" hidden' in html
    assert "PASS" not in html.split('id="verificationChip"', 1)[1].split("</span>", 1)[0]
    assert "export function verificationStatusChip" in state
    assert "verification.evidence" not in state.split("function recordedVerification", 1)[1].split("export function verificationStatusChip", 1)[0]
    assert "verificationStatusChip" in control
    assert ".hud-chip.status.pass{" in css
    assert ".hud-chip.status.fail,.hud-chip.status.inconclusive{" in css
    assert ".hud-chip.status.pending{" in css
