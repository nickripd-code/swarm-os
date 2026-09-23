"""Static contract for the compact, truthful Mission Control shell."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")


def test_compact_shell_preserves_every_javascript_mount_point():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    parser = _IdCollector()
    parser.feed(html)

    required = {
        "missionForm", "goal", "launch", "brain", "history", "objectiveHud",
        "missionMode", "missionStatus", "lastApprovalAtChip", "hudElapsed", "hudAgents", "hudTasks",
        "hudTokens", "hudSpend", "costHud", "replayHud", "questionPanel",
        "answerForm", "mapViewport", "world", "connections", "nodes", "emptyMap",
        "agentCount", "taskCount", "tokenCount", "inspectorContent", "activity",
        "commandBar", "commandForm", "resultPanel", "stopAll", "alerts",
    }
    assert required <= set(parser.ids)
    assert len(parser.ids) == len(set(parser.ids))


def test_shell_is_tree_first_and_secondary_controls_are_collapsible():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")

    assert 'class="mission-dock"' in html
    assert '<section class="workspace">' in html
    assert '<details class="telemetry-drawer">' in html
    assert '<details class="command-drawer">' in html
    assert html.index('id="stopAll"') < html.index('id="mapViewport"')
    assert "grid-template-columns:minmax(0,1fr) 340px" in css
    assert "height:calc(100vh - 258px)" in css


def test_ui_does_not_claim_unconfigured_capabilities():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8").lower()
    assert "connected to thousands" not in html
    assert "can do anything" not in html
    assert "payment connected" not in html
    assert "durable mission events appear here" in html


def test_control_module_starts_with_a_real_line_break():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    first_line, second_line, *_ = control.splitlines()
    assert first_line.endswith('from "./state.mjs";')
    assert second_line.startswith("const $ =")
    assert "`;`n" not in first_line
