"""Read-only pending-approval count chip. Never invents a count."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "pending_approval_count_cases.mjs"


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the pending-approval count harness")
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


def test_no_mission_or_preview_hides_the_chip_with_an_empty_label(cases):
    for key in ("noMission", "preview"):
        view = cases[key]
        assert view["hidden"] is True
        assert view["label"] == ""
        assert view["count"] is None
        assert view["known"] is False


def test_explicit_null_and_plain_question_are_honest_zero(cases):
    for key in ("explicitNull", "humanQuestion", "answeredHistoryIsNotPending", "afterAnswer",
                "inFlightWaitIsZero", "projectedAnswered", "projectedQuestion", "emptyProjection"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is True
        assert view["count"] == 0
        assert view["label"] == "0"


def test_parked_human_and_org_approvals_count_as_one(cases):
    for key in ("orgApproval", "finishApproval", "paymentApproval", "afterQuestionEvent",
                "secondApprovalIsStillOne", "projectedApproval"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is True
        assert view["count"] == 1
        assert view["label"] == "1"


def test_unclassified_pending_item_is_unavailable(cases):
    for key in ("missingField", "missingKind", "blankApprovalId", "unknownKind",
                "orgOpWithoutKind", "questionEventWithoutKind"):
        view = cases[key]
        assert view["hidden"] is False
        assert view["known"] is False
        assert view["count"] is None
        assert view["label"] == "unavailable"


def test_chip_is_wired_as_a_readout_only():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    state = (ROOT / "app/static/state.mjs").read_text(encoding="utf-8")
    hud = html.split('id="objectiveHud"', 1)[1].split("</section>", 1)[0]
    assert 'id="pendingApprovalCountChip"' in hud
    assert "pendingApprovalCountView" in control
    assert "export function pendingApprovalCountView" in state
    assert "fetch(" not in state.split("export function pendingApprovalCountView", 1)[1].split("export function applyEvent", 1)[0]
