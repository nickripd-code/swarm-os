import {newState, applyEvent, projectEvents, lastToolNameChip, LAST_TOOL_UNAVAILABLE} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

function mission() {
  return {id: "m1", goal: "Ship the seed", status: "running", created_at: "2026-01-01T00:00:00Z"};
}

function loaded(...events) {
  const state = newState(mission());
  for (const item of events) applyEvent(state, item);
  return state;
}

const cases = {unavailable: LAST_TOOL_UNAVAILABLE};

cases.noMission = lastToolNameChip(newState());
cases.preview = lastToolNameChip({
  ...loaded(event("t1", "tool.started", {tool: "workspace.read"})),
  preview: true,
});
cases.noEvents = lastToolNameChip(newState(mission()));
cases.blank = lastToolNameChip(loaded(event("t2", "tool.started", {tool: "   "})));
cases.missingTool = lastToolNameChip(loaded(event("t3", "tool.completed", {})));
cases.nameOnly = lastToolNameChip(loaded(event("t4", "tool.started", {name: "invented.tool"})));
cases.invalid = lastToolNameChip(loaded(event("t5", "tool.failed", {tool: "<script>"})));
cases.tooLong = lastToolNameChip(loaded(event("t6", "tool.started", {tool: "a".repeat(81)})));
cases.decision = lastToolNameChip(loaded(event("d1", "controller.decision", {action: "tool", tool: "workspace.read"})));
cases.queueField = lastToolNameChip({
  ...newState(mission()),
  workQueue: {lastTool: "queue.fake"},
  events: [],
});

cases.started = lastToolNameChip(loaded(event("s1", "tool.started", {tool: "workspace.read", used: 1, max: 200})));
cases.completed = lastToolNameChip(loaded(event("c1", "tool.completed", {tool: "composio.github_get", ok: true})));
cases.failed = lastToolNameChip(loaded(event("f1", "tool.failed", {tool: "browser.navigate", failure_class: "TOOL_FAILURE"})));
cases.trimmed = lastToolNameChip(loaded(event("p1", "tool.started", {tool: "  workspace.read  "})));

const newest = loaded(
  event("n1", "tool.started", {tool: "workspace.read"}),
  event("n2", "tool.completed", {tool: "workspace.read"}),
  event("n3", "tool.started", {tool: "composio.github_get"}),
);
cases.newest = lastToolNameChip(newest);

const skipped = loaded(
  event("k2", "tool.started", {tool: "workspace.read"}),
  event("k1", "tool.started", {tool: "not a tool"}),
);
cases.skipInvalidNewer = lastToolNameChip(skipped);

const log = [
  event("e0", "mission.started", {mode: "live"}),
  event("e1", "tool.started", {tool: "workspace.read"}),
  event("e2", "tool.failed", {tool: "browser.navigate"}),
];
const recorded = mission();
cases.replayBefore = lastToolNameChip(projectEvents(recorded, log, 0));
cases.replayFirst = lastToolNameChip(projectEvents(recorded, log, 1));
cases.replaySecond = lastToolNameChip(projectEvents(recorded, log, 2));

console.log(JSON.stringify(cases));
