import {
  recordedActiveToolFeed, activeToolCountView, ACTIVE_TOOLS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}
function started(id, tool, used) {
  return event(id, "tool.started", {tool, used, max: 8});
}
function completed(id, tool, used) {
  return event(id, "tool.completed", {tool, used, max: 8, ok: true});
}
function failed(id, tool, used) {
  return event(id, "tool.failed", {tool, used, max: 8, error: "no"});
}

const log = [
  started("s1", "echo", 1),
  completed("c1", "echo", 1),
  started("s2", "hash.sha256", 2),
  failed("f-pre", "shell", 0),
  started("s3", "clock.utc", 3),
];

const cases = {};
cases.hidden = activeToolCountView(log, {visible: false});
cases.hiddenDefault = activeToolCountView(log);
cases.missingNull = activeToolCountView(null, {visible: true});
cases.missingUndefined = activeToolCountView(undefined, {visible: true});
cases.missingObject = activeToolCountView({used: 4, tool_calls: {used: 4}}, {visible: true});
cases.empty = activeToolCountView([], {visible: true});
cases.oneOpen = activeToolCountView([started("only", "echo", 9)], {visible: true});
cases.twoOpen = activeToolCountView([
  started("a", "echo", 1),
  started("b", "hash.sha256", 2),
], {visible: true});
cases.matchedComplete = activeToolCountView([
  started("a", "echo", 1),
  completed("b", "echo", 1),
], {visible: true});
cases.matchedFailed = activeToolCountView([
  started("a", "echo", 1),
  failed("b", "echo", 1),
], {visible: true});
cases.prestartIgnored = activeToolCountView([
  failed("deny", "shell", 0),
  started("a", "echo", 1),
], {visible: true});
cases.otherToolDoesNotClose = activeToolCountView([
  started("a", "echo", 1),
  failed("deny", "shell", 1),
], {visible: true});
cases.closedThenPrestart = activeToolCountView([
  started("a", "echo", 1),
  completed("b", "echo", 1),
  failed("deny", "echo", 1),
], {visible: true});
cases.prefixOpen = activeToolCountView(recordedActiveToolFeed(log, 0, true), {visible: true});
cases.prefixClosed = activeToolCountView(recordedActiveToolFeed(log, 1, true), {visible: true});
cases.prefixMid = activeToolCountView(recordedActiveToolFeed(log, 2, true), {visible: true});
cases.prefixAll = activeToolCountView(recordedActiveToolFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = activeToolCountView(recordedActiveToolFeed(log, -1, true), {visible: true});
cases.unloaded = activeToolCountView(recordedActiveToolFeed(log, log.length - 1, false), {visible: true});
cases.unloadedMissingFlag = activeToolCountView(recordedActiveToolFeed([], 0, undefined), {visible: true});
cases.holes = activeToolCountView([null, {payload: {used: 5}}, started("one", "echo", 1)], {visible: true});
cases.orphanCompleted = activeToolCountView([
  completed("c", "echo", 1),
], {visible: true});
cases.duplicateStart = activeToolCountView([
  started("a", "echo", 1),
  completed("b", "echo", 1),
  started("c", "echo", 1),
], {visible: true});
cases.missingTool = activeToolCountView([
  event("a", "tool.started", {used: 1, max: 8}),
], {visible: true});
cases.stringUsed = activeToolCountView([
  event("a", "tool.started", {tool: "echo", used: "1", max: 8}),
], {visible: true});
cases.ignoresNonTool = activeToolCountView([
  event("m", "mission.started", {used: 4, tool: "echo"}),
  event("l", "llm.completed", {used: 3}),
], {visible: true});

console.log(JSON.stringify({unavailable: ACTIVE_TOOLS_UNAVAILABLE, cases}));
