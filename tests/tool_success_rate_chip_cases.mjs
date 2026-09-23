import {
  recordedToolSuccessRateFeed, toolSuccessRateView, TOOL_SUCCESS_RATE_UNAVAILABLE,
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
  event("l1", "llm.failed", {kind: "decision"}),
  event("l2", "llm.completed", {kind: "decision"}),
  completed("c3"),
];

const cases = {};
cases.unavailable = TOOL_SUCCESS_RATE_UNAVAILABLE;
cases.hidden = toolSuccessRateView(log, {visible: false});
cases.hiddenDefault = toolSuccessRateView(log);
cases.preview = toolSuccessRateView(log, {visible: false});
cases.missingNull = toolSuccessRateView(null, {visible: true});
cases.missingUndefined = toolSuccessRateView(undefined, {visible: true});
cases.missingObject = toolSuccessRateView({tool_calls: {failed: 4, completed: 1}, events: []}, {visible: true});
cases.empty = toolSuccessRateView([], {visible: true});
cases.counted = toolSuccessRateView(log, {visible: true});
cases.startedOnly = toolSuccessRateView([
  event("only", "tool.started", {failed: 3, completed: 0}),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.completesOnly = toolSuccessRateView([
  completed("ok1"),
  event("bad", "tool.completed", {ok: false}),
], {visible: true});
cases.half = toolSuccessRateView([failed("f"), completed("a")], {visible: true});
cases.allFailed = toolSuccessRateView([failed("f1"), failed("f2")], {visible: true});
cases.third = toolSuccessRateView([failed("f"), completed("a"), completed("b")], {visible: true});
cases.startedIgnored = toolSuccessRateView([
  event("s", "tool.started"),
  event("llm", "llm.completed"),
  completed("ok"),
], {visible: true});
cases.tiny = toolSuccessRateView([completed("ok"), ...Array.from({length: 1000000}, (_, i) => failed("f" + i))], {visible: true});
cases.nearPerfect = toolSuccessRateView([failed("f"), ...Array.from({length: 1000000}, (_, i) => completed("c" + i))], {visible: true});
cases.skipsHoles = toolSuccessRateView([null, {payload: {failed: 3, rate: 1}}, failed("one"), completed("two")], {visible: true});
cases.prefix = toolSuccessRateView(recordedToolSuccessRateFeed(log, 2, true), {visible: true});
cases.prefixFirst = toolSuccessRateView(recordedToolSuccessRateFeed(log, 0, true), {visible: true});
cases.prefixAll = toolSuccessRateView(recordedToolSuccessRateFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = toolSuccessRateView(recordedToolSuccessRateFeed(log, -1, true), {visible: true});
cases.unloaded = recordedToolSuccessRateFeed(log, log.length - 1, false);
cases.unloadedView = toolSuccessRateView(recordedToolSuccessRateFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedToolSuccessRateFeed([], -1, true);
cases.notArrayLog = recordedToolSuccessRateFeed({length: 0, failed: 1, completed: 1}, 0, true);

console.log(JSON.stringify(cases));
