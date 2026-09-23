import {
  newState, applyEvent, projectEvents, toolCallStrip,
  TOOL_STRIP_EMPTY, TOOL_STRIP_PREVIEW, TOOL_STRIP_NOTE,
} from "../app/static/state.mjs";

const mission = {
  id: "m1",
  goal: "Check the clock",
  created_at: "2026-01-01T00:00:00Z",
  mode: "openai",
  budget: 0,
};

function spawn(id, role) {
  return {
    id: "spawn-" + id,
    event_type: "agent.spawned",
    actor_id: id,
    payload: {id, role, purpose: "work", capabilities: [], status: "running", depth: 0},
    created_at: "2026-01-01T00:00:00Z",
  };
}

const log = [
  {id: "started", event_type: "mission.started", actor_id: "root", payload: {mode: "openai"}, created_at: "2026-01-01T00:00:00Z"},
  spawn("root", "mission_controller"),
  {
    id: "tool-start",
    event_type: "tool.started",
    actor_id: "root",
    payload: {tool: "clock.utc", used: 1, max: 4, arguments: {query: "do not show"}, output: {secret: "nope"}},
    created_at: "2026-01-01T00:00:01Z",
  },
  {
    id: "tool-done",
    event_type: "tool.completed",
    actor_id: "root",
    payload: {tool: "clock.utc", ok: true, output: {iso: "secret"}, error: "hidden", provider: "local"},
    created_at: "2026-01-01T00:00:02Z",
  },
  {
    id: "tool-fail",
    event_type: "tool.failed",
    actor_id: "missing",
    payload: {tool: "echo", failure_class: "TOOL_FAILURE", error: "boom details that must stay hidden"},
    created_at: "2026-01-01T00:00:03Z",
  },
  {
    id: "nameless",
    event_type: "tool.completed",
    actor_id: "root",
    payload: {output: {invented: true}, error: "missing name"},
    created_at: "2026-01-01T00:00:04Z",
  },
  {
    id: "blob",
    event_type: "tool.started",
    actor_id: "root",
    payload: {tool: "{\"output\":\"dump\"}"},
    created_at: "2026-01-01T00:00:05Z",
  },
];

const cases = {};
cases.empty = toolCallStrip(newState(mission));
cases.standby = toolCallStrip(newState(null));
cases.constants = {empty: TOOL_STRIP_EMPTY, preview: TOOL_STRIP_PREVIEW, note: TOOL_STRIP_NOTE};

const preview = newState(mission);
preview.preview = true;
applyEvent(preview, log[2]);
cases.preview = toolCallStrip(preview);

const full = projectEvents(mission, log);
cases.full = toolCallStrip(full);
cases.atStart = toolCallStrip(projectEvents(mission, log, 2));
cases.limit = toolCallStrip(projectEvents(mission, [
  spawn("root", "researcher"),
  ...Array.from({length: 10}, (_, i) => ({
    id: "n" + i,
    event_type: i % 2 ? "tool.completed" : "tool.started",
    actor_id: "root",
    payload: {tool: "echo", output: {i}},
    created_at: "2026-01-01T00:00:0" + i + "Z",
  })),
]), 3);

process.stdout.write(JSON.stringify(cases));
