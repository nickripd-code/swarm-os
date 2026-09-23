import {
  recordedToolFeed, toolCallCountView, TOOL_CALLS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id, extra = {}) => event(id, "tool.started", {tool: "echo", used: 99, ...extra});
const log = [
  started("t1"),
  event("f1", "tool.failed", {tool: "echo", used: 0}),
  event("c1", "tool.completed", {tool: "echo", used: 1, ok: true}),
  started("t2"),
  event("a1", "agent.spawned", {id: "root"}),
  started("t3"),
];

const cases = {};
cases.unavailable = TOOL_CALLS_UNAVAILABLE;
cases.hidden = toolCallCountView(log, {visible: false});
cases.hiddenDefault = toolCallCountView(log);
cases.missingNull = toolCallCountView(null, {visible: true});
cases.missingUndefined = toolCallCountView(undefined, {visible: true});
cases.missingObject = toolCallCountView({tool_calls: {used: 4}, events: []}, {visible: true});
cases.empty = toolCallCountView([], {visible: true});
cases.counted = toolCallCountView(log, {visible: true});
cases.ignoresUsedField = toolCallCountView([started("only")], {visible: true});
cases.skipsHoles = toolCallCountView([null, {payload: {used: 3}}, started("one")], {visible: true});
cases.prefix = toolCallCountView(recordedToolFeed(log, 1, true), {visible: true});
cases.prefixFirst = toolCallCountView(recordedToolFeed(log, 0, true), {visible: true});
cases.prefixAll = toolCallCountView(recordedToolFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = toolCallCountView(recordedToolFeed(log, -1, true), {visible: true});
cases.unloaded = recordedToolFeed(log, log.length - 1, false);
cases.unloadedView = toolCallCountView(recordedToolFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedToolFeed([], -1, true);
cases.notArrayLog = recordedToolFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
