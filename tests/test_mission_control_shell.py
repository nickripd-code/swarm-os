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
        "missionMode", "missionStatus", "hudElapsed", "hudAgents", "hudTasks",
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


def test_phone_layout_stacks_priority_surfaces_without_invented_controls():
    """Contract for the 320–430px Mission Control seed. No phone lab is required.

    Spot-check in a desktop browser: set the viewport width to 320px, then
    390px, then 430px. The page should not scroll sideways. The agent map may
    scroll inside #mapViewport. Launch, STOP ALL, Preview, answer send, kill,
    command Run, and zoom/fit should be at least 44px tall. Preview must still
    read PREVIEW and must not claim a model is running.
    """
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/control.css").read_text(encoding="utf-8")
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    marker = "/* phone-mission-control:"
    assert marker in css
    phone = css.split(marker, 1)[1]
    assert "max-width:430px" in phone
    for token in (
        "env(safe-area-inset-top)",
        "env(safe-area-inset-right)",
        "env(safe-area-inset-bottom)",
        "env(safe-area-inset-left)",
        "overflow-x:hidden",
        "overflow-y:auto",
        "min-height:44px",
        "touch-action:manipulation",
        "touch-action:pan-x pan-y",
        ".stop-button",
        ".mission-form button",
        ".answer-form button",
        ".kill-agent",
        ".command-bar-form button",
        ".command-drawer>summary",
        "#activity",
        ".hud-stats",
        ".hud-chips",
        "grid-template-columns:1fr",
        "position:static",
    ):
        assert token in phone, token
    assert "grid-template-columns:minmax(0,1fr) 340px" not in phone
    assert css.index("grid-template-columns:minmax(0,1fr) 340px") < css.index(marker)
    assert 'viewport-fit=cover' in html
    assert "width=device-width" in html
    assert 'class="pan-hint-touch">Scroll' in html
    assert 'class="pan-hint-mouse">Drag · scroll' in html
    assert "estimate unavailable" in html
    assert 'id="pause"' not in html
    assert 'id="resume"' not in html
    assert "Interactive preview · no models or tools are running" in control
    assert 'state.preview?"PREVIEW"' in control
    assert 'matchMedia("(max-width: 430px)")' in control
    assert "Math.max(narrow?280:650," in control
    assert "layoutTree(state.agents,treeLayoutWidth())" in control
    assert 'class="kill-agent"' in control


def test_control_module_starts_with_a_real_line_break():
    control = (ROOT / "app/static/control.js").read_text(encoding="utf-8")
    first_line, second_line, *_ = control.splitlines()
    assert first_line.endswith('from "./state.mjs";')
    assert second_line.startswith("const $ =")
    assert "`;`n" not in first_line
