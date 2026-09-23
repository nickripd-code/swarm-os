import {
  recordedToolSuccessFeed, toolSuccessCountView, TOOL_SUCCESS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const completed = (id, extra = {}) => event(id, "tool.completed", {tool: "echo", ok: true, used: 1, ...extra});
const log = [
  event("s1", "tool.started", {tool: "echo", used: 1}),
  completed("c1"),
  event("f1", "tool.failed", {tool: "echo", ok: false, used: 1}),
  completed("c2"),
  event("a1", "agent.spawned", {id: "root"}),
  event("m1", "mission.completed", {result: "done"}),
  completed("c3", {ok: false, used: 99}),
];

const cases = {};
cases.unavailable = TOOL_SUCCESS_UNAVAILABLE;
cases.hidden = toolSuccessCountView(log, {visible: false});
cases.hiddenDefault = toolSuccessCountView(log);
cases.preview = toolSuccessCountView(log, {visible: false});
cases.missingNull = toolSuccessCountView(null, {visible: true});
cases.missingUndefined = toolSuccessCountView(undefined, {visible: true});
cases.missingObject = toolSuccessCountView({tool_calls: {completed: 4}, events: []}, {visible: true});
cases.empty = toolSuccessCountView([], {visible: true});
cases.counted = toolSuccessCountView(log, {visible: true});
cases.ignoresStarted = toolSuccessCountView([event("only", "tool.started", {ok: true, completed: 3})], {visible: true});
cases.ignoresFailed = toolSuccessCountView([event("bad", "tool.failed", {ok: false})], {visible: true});
cases.countsCompletedEvenIfOkFalse = toolSuccessCountView([completed("odd", {ok: false})], {visible: true});
cases.skipsHoles = toolSuccessCountView([null, {payload: {ok: 3}}, completed("one")], {visible: true});
cases.prefix = toolSuccessCountView(recordedToolSuccessFeed(log, 1, true), {visible: true});
cases.prefixFirst = toolSuccessCountView(recordedToolSuccessFeed(log, 0, true), {visible: true});
cases.prefixAll = toolSuccessCountView(recordedToolSuccessFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = toolSuccessCountView(recordedToolSuccessFeed(log, -1, true), {visible: true});
cases.unloaded = recordedToolSuccessFeed(log, log.length - 1, false);
cases.unloadedView = toolSuccessCountView(recordedToolSuccessFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedToolSuccessFeed([], -1, true);
cases.notArrayLog = recordedToolSuccessFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
