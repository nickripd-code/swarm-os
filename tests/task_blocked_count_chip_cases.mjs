import {
  recordedTaskBlockedCountFeed, taskBlockedCountView, TASK_BLOCKED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const blocked = (id, extra = {}) => event(id, "task.blocked", {id, status: "blocked", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  blocked("t1"),
  event("done", "task.completed", {id: "t2", status: "completed"}),
  event("mission", "mission.blocked", {reason: "Required capability or information is unavailable"}),
  event("started", "task.started", {id: "t5", status: "running"}),
  blocked("t3"),
  event("stopped", "task.stopped", {id: "t7", status: "stopped"}),
  event("budget", "budget.updated", {known: true, token_spent: 1}),
  event("updated", "agent.updated", {id: "a1", status: "blocked"}),
  event("failed", "task.failed", {id: "t6", status: "failed"}),
  blocked("t4", {blocked: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = TASK_BLOCKED_COUNT_UNAVAILABLE;
cases.hidden = taskBlockedCountView(log, {visible: false});
cases.hiddenDefault = taskBlockedCountView(log);
cases.preview = taskBlockedCountView(log, {visible: false});
cases.missingNull = taskBlockedCountView(null, {visible: true});
cases.missingUndefined = taskBlockedCountView(undefined, {visible: true});
cases.missingObject = taskBlockedCountView({blocked: 4, events: []}, {visible: true});
cases.empty = taskBlockedCountView([], {visible: true});
cases.counted = taskBlockedCountView(log, {visible: true});
cases.ignoresMissionBlocked = taskBlockedCountView([
  event("mission", "mission.blocked", {blocked: 3}),
], {visible: true});
cases.ignoresTaskStarted = taskBlockedCountView([
  event("started", "task.started", {status: "blocked", blocked: 1}),
], {visible: true});
cases.ignoresTaskCompleted = taskBlockedCountView([
  event("done", "task.completed", {status: "blocked", blocked: 2}),
], {visible: true});
cases.ignoresTaskFailed = taskBlockedCountView([
  event("failed", "task.failed", {status: "blocked", blocked: 2}),
], {visible: true});
cases.ignoresTaskPending = taskBlockedCountView([
  event("pending", "task.pending", {status: "blocked", blocked: 1}),
], {visible: true});
cases.ignoresTaskStopped = taskBlockedCountView([
  event("stopped", "task.stopped", {status: "blocked", blocked: 1}),
], {visible: true});
cases.ignoresAgentUpdated = taskBlockedCountView([
  event("updated", "agent.updated", {status: "blocked", blocked: 6}),
], {visible: true});
cases.ignoresPaused = taskBlockedCountView([
  event("paused", "mission.paused", {blocked: 1}),
], {visible: true});
cases.ignoresMissionFailed = taskBlockedCountView([
  event("failed-mission", "mission.failed", {blocked: 1}),
], {visible: true});
cases.ignoresBudget = taskBlockedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, blocked: 1}),
], {visible: true});
cases.oneBlockNotPayload = taskBlockedCountView([
  blocked("big", {blocked: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = taskBlockedCountView([null, {payload: {blocked: 10}}, blocked("one")], {visible: true});
cases.unreadableType = taskBlockedCountView([
  blocked("ok"),
  {id: "bad", event_type: 4, payload: {blocked: 1}},
], {visible: true});
cases.missingType = taskBlockedCountView([
  {id: "blank", payload: {blocked: 7}},
  blocked("one"),
], {visible: true});
cases.prefix = taskBlockedCountView(recordedTaskBlockedCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = taskBlockedCountView(recordedTaskBlockedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = taskBlockedCountView(recordedTaskBlockedCountFeed(log, 6, true), {visible: true});
cases.prefixAll = taskBlockedCountView(recordedTaskBlockedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = taskBlockedCountView(recordedTaskBlockedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedTaskBlockedCountFeed(log, log.length - 1, false);
cases.unloadedView = taskBlockedCountView(recordedTaskBlockedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedTaskBlockedCountFeed([], -1, true);
cases.notArrayLog = recordedTaskBlockedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
