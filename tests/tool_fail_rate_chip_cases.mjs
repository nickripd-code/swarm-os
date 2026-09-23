import {
  recordedToolFailRateFeed, toolFailRateView, TOOL_FAIL_RATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "tool.failed", {tool: "echo", used: 99, ...extra});
const completed = (id, extra = {}) => event(id, "tool.completed", {tool: "echo", ok: true, used: 1, ...extra});
const log = [
  event("s1", "tool.started", {tool: "echo", failed: 4, completed: 9}),
  failed("f1"),
  completed("c1"),
  event("cFalse", "tool.completed", {tool: "echo", ok: false, used: 1}),
  failed("f2"),
  event("a1", "agent.spawned", {id: "root", status: "running"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "TOOL_MISSING"}),
  completed("c3"),
];

const cases = {};
cases.unavailable = TOOL_FAIL_RATE_UNAVAILABLE;
cases.hidden = toolFailRateView(log, {visible: false});
cases.hiddenDefault = toolFailRateView(log);
cases.preview = toolFailRateView(log, {visible: false});
cases.missingNull = toolFailRateView(null, {visible: true});
cases.missingUndefined = toolFailRateView(undefined, {visible: true});
cases.missingObject = toolFailRateView({tool_calls: {failed: 4, completed: 1}, events: []}, {visible: true});
cases.empty = toolFailRateView([], {visible: true});
cases.counted = toolFailRateView(log, {visible: true});
cases.noToolsYet = toolFailRateView([
  event("only", "tool.started", {failed: 3, completed: 0}),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.completesOnly = toolFailRateView([
  completed("ok1"),
  event("bad", "tool.completed", {ok: false}),
], {visible: true});
cases.half = toolFailRateView([failed("f"), completed("a"), completed("b")], {visible: true});
cases.double = toolFailRateView([failed("f1"), failed("f2"), completed("a")], {visible: true});
cases.third = toolFailRateView([failed("f"), completed("a"), completed("b"), completed("c")], {visible: true});
cases.failsWithoutCompletes = toolFailRateView([failed("only")], {visible: true});
cases.tiny = toolFailRateView([failed("f"), ...Array.from({length: 50001}, (_, i) => completed("c" + i))], {visible: true});
cases.skipsHoles = toolFailRateView([null, {payload: {failed: 3, rate: 1}}, failed("one"), completed("two")], {visible: true});
cases.prefix = toolFailRateView(recordedToolFailRateFeed(log, 2, true), {visible: true});
cases.prefixFirst = toolFailRateView(recordedToolFailRateFeed(log, 0, true), {visible: true});
cases.prefixAll = toolFailRateView(recordedToolFailRateFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = toolFailRateView(recordedToolFailRateFeed(log, -1, true), {visible: true});
cases.unloaded = recordedToolFailRateFeed(log, log.length - 1, false);
cases.unloadedView = toolFailRateView(recordedToolFailRateFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedToolFailRateFeed([], -1, true);
cases.notArrayLog = recordedToolFailRateFeed({length: 0, failed: 1, completed: 1}, 0, true);

console.log(JSON.stringify(cases));
