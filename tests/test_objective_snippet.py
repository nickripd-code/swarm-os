"""Read-only Mission Control objective snippet: loaded goal only, phone-truncated."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "objective_snippet_cases.mjs"
PLACEHOLDERS = (
    "Awaiting a mission.",
    "One mission. As many minds as it needs.",
    "Design a launch plan for a small business",
)


def _load_cases() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the objective snippet harness")
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


def test_empty_mission_stays_hidden_and_blank(cases):
    for name, view in cases["empty"].items():
        assert view["visible"] is False, name
        assert view["text"] == "", name
        assert view["full"] == "", name
        assert view["truncated"] is False, name
        for placeholder in PLACEHOLDERS:
            assert placeholder not in view["text"]


def test_loaded_goal_is_shown_without_invention(cases):
    view = cases["short"]
    assert view["visible"] is True
    assert view["truncated"] is False
    assert view["text"] == "Publish the weekly launch note"
    assert view["full"] == view["text"]
    assert view["graphemes"] <= cases["limit"]


def test_whitespace_is_collapsed_not_rewritten(cases):
    view = cases["collapsed"]
    assert view["text"] == "alpha beta gamma"
    assert "alpha" in view["text"] and "gamma" in view["text"]


def test_phone_budget_truncates_on_a_word_boundary(cases):
    view = cases["spaced"]
    assert view["visible"] is True
    assert view["truncated"] is True
    assert view["text"].endswith("…")
    assert view["graphemes"] <= cases["limit"]
    assert view["text"][:-1].rstrip() in view["full"]
    assert not view["text"].endswith(" …")
    assert "include the open risks" not in view["text"]


def test_unbroken_token_is_hard_cut_inside_the_phone_budget(cases):
    view = cases["token"]
    assert view["truncated"] is True
    assert view["text"].endswith("…")
    assert view["graphemes"] == cases["limit"]
    assert " " not in view["text"]


def test_grapheme_clusters_are_not_split(cases):
    fit = cases["emojiFit"]
    assert fit["truncated"] is False
    assert fit["text"].endswith("👨‍👩‍👧‍👦")
    assert fit["graphemes"] == cases["limit"]
    overflow = cases["emojiOverflow"]
    assert overflow["truncated"] is True
    assert "👨‍👩‍👧‍👦" not in overflow["text"]
    assert overflow["graphemes"] <= cases["limit"]


def test_invalid_limit_uses_the_phone_budget(cases):
    view = cases["badLimit"]
    assert view["graphemes"] == cases["limit"]
    assert view["truncated"] is True


def test_markup_stays_text_and_is_not_executed_as_markup(cases):
    view = cases["markup"]
    assert view["visible"] is True
    assert "<script>" in view["full"]
    assert view["text"].startswith("<script>")


def test_panel_is_hidden_empty_and_phone_truncated_in_the_shell():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    opening = html.index('<section class="objective-snippet"')
    tag = html[opening:html.index(">", opening) + 1]
    section = html[opening:html.index('id="questionPanel"')]
    assert tag.endswith('hidden>')
    assert 'id="objectiveSnippetText"></p>' in section
    assert "<input" not in section and "<button" not in section and "<textarea" not in section
    for placeholder in PLACEHOLDERS:
        assert placeholder not in section
    assert "objectiveSnippet" in control
    block = control[control.index("const snippet=objectiveSnippet"):control.index('if($("missionMode"))')]
    assert "snippetText.textContent=snippet.text" in block
    assert "innerHTML" not in block
    phone = css.split("@media(max-width:620px)")[1].split("@media")[0]
    assert ".objective-snippet p{" in phone
    assert "overflow:hidden" in phone
    assert "line-clamp:2" in phone
    assert "overflow-wrap:anywhere" in phone
    assert ".objective-snippet p{" in css
    assert "animation" not in css.split(".objective-snippet{")[1].split(".telemetry-drawer")[0]


def test_static_objective_snippet_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_DB", str(tmp_path / "swarm.db"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="objectiveSnippet"' in page.text
        assert 'id="objectiveSnippetText"></p>' in page.text
        state = client.get("/static/state.mjs")
        assert state.status_code == 200
        assert "export function objectiveSnippet" in state.text
        css = client.get("/static/control.css")
        assert css.status_code == 200
        assert ".objective-snippet" in css.text
