import {
  recordedToolFailFeed, toolFailCountView, TOOL_FAILS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "tool.failed", {tool: "echo", used: 99, ...extra});
const log = [
  event("s1", "tool.started", {tool: "echo", used: 1}),
  failed("f1"),
  event("c1", "tool.completed", {tool: "echo", ok: false, used: 1}),
  failed("f2"),
  event("a1", "agent.spawned", {id: "root"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "TOOL_MISSING"}),
  failed("f3"),
];

const cases = {};
cases.unavailable = TOOL_FAILS_UNAVAILABLE;
cases.hidden = toolFailCountView(log, {visible: false});
cases.hiddenDefault = toolFailCountView(log);
cases.preview = toolFailCountView(log, {visible: false});
cases.missingNull = toolFailCountView(null, {visible: true});
cases.missingUndefined = toolFailCountView(undefined, {visible: true});
cases.missingObject = toolFailCountView({tool_calls: {failed: 4}, events: []}, {visible: true});
cases.empty = toolFailCountView([], {visible: true});
cases.counted = toolFailCountView(log, {visible: true});
cases.ignoresStarted = toolFailCountView([event("only", "tool.started", {failed: 3})], {visible: true});
cases.ignoresCompletedFalse = toolFailCountView([event("bad", "tool.completed", {ok: false})], {visible: true});
cases.skipsHoles = toolFailCountView([null, {payload: {failed: 3}}, failed("one")], {visible: true});
cases.prefix = toolFailCountView(recordedToolFailFeed(log, 1, true), {visible: true});
cases.prefixFirst = toolFailCountView(recordedToolFailFeed(log, 0, true), {visible: true});
cases.prefixAll = toolFailCountView(recordedToolFailFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = toolFailCountView(recordedToolFailFeed(log, -1, true), {visible: true});
cases.unloaded = recordedToolFailFeed(log, log.length - 1, false);
cases.unloadedView = toolFailCountView(recordedToolFailFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedToolFailFeed([], -1, true);
cases.notArrayLog = recordedToolFailFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
