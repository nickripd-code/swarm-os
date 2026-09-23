import {
  recordedPendingToolFeed, pendingToolCountView, PENDING_TOOLS_UNAVAILABLE,
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
cases.hidden = pendingToolCountView(log, {visible: false});
cases.hiddenDefault = pendingToolCountView(log);
cases.missingNull = pendingToolCountView(null, {visible: true});
cases.missingUndefined = pendingToolCountView(undefined, {visible: true});
cases.missingObject = pendingToolCountView({used: 4, tool_calls: {used: 4}}, {visible: true});
cases.empty = pendingToolCountView([], {visible: true});
cases.oneOpen = pendingToolCountView([started("only", "echo", 9)], {visible: true});
cases.twoOpen = pendingToolCountView([
  started("a", "echo", 1),
  started("b", "hash.sha256", 2),
], {visible: true});
cases.matchedComplete = pendingToolCountView([
  started("a", "echo", 1),
  completed("b", "echo", 1),
], {visible: true});
cases.matchedFailed = pendingToolCountView([
  started("a", "echo", 1),
  failed("b", "echo", 1),
], {visible: true});
cases.prestartIgnored = pendingToolCountView([
  failed("deny", "shell", 0),
  started("a", "echo", 1),
], {visible: true});
cases.otherToolDoesNotClose = pendingToolCountView([
  started("a", "echo", 1),
  failed("deny", "shell", 1),
], {visible: true});
cases.closedThenPrestart = pendingToolCountView([
  started("a", "echo", 1),
  completed("b", "echo", 1),
  failed("deny", "echo", 1),
], {visible: true});
cases.prefixOpen = pendingToolCountView(recordedPendingToolFeed(log, 0, true), {visible: true});
cases.prefixClosed = pendingToolCountView(recordedPendingToolFeed(log, 1, true), {visible: true});
cases.prefixMid = pendingToolCountView(recordedPendingToolFeed(log, 2, true), {visible: true});
cases.prefixAll = pendingToolCountView(recordedPendingToolFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = pendingToolCountView(recordedPendingToolFeed(log, -1, true), {visible: true});
cases.unloaded = pendingToolCountView(recordedPendingToolFeed(log, log.length - 1, false), {visible: true});
cases.unloadedMissingFlag = pendingToolCountView(recordedPendingToolFeed([], 0, undefined), {visible: true});
cases.holes = pendingToolCountView([null, {payload: {used: 5}}, started("one", "echo", 1)], {visible: true});
cases.orphanCompleted = pendingToolCountView([
  completed("c", "echo", 1),
], {visible: true});
cases.duplicateStart = pendingToolCountView([
  started("a", "echo", 1),
  completed("b", "echo", 1),
  started("c", "echo", 1),
], {visible: true});
cases.missingTool = pendingToolCountView([
  event("a", "tool.started", {used: 1, max: 8}),
], {visible: true});
cases.stringUsed = pendingToolCountView([
  event("a", "tool.started", {tool: "echo", used: "1", max: 8}),
], {visible: true});
cases.ignoresNonTool = pendingToolCountView([
  event("m", "mission.started", {used: 4, tool: "echo"}),
  event("l", "llm.completed", {used: 3}),
  event("d", "controller.decision", {action: "use_tool", tool: "echo"}),
], {visible: true});

console.log(JSON.stringify({unavailable: PENDING_TOOLS_UNAVAILABLE, cases}));
