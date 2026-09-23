import {
  recordedTaskPendingCountFeed, taskPendingCountView, TASK_PENDING_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const pending = (id, extra = {}) => event(id, "task.pending", {id, status: "pending", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  pending("t1"),
  event("failed", "task.failed", {id: "t2", status: "failed"}),
  event("completed", "task.completed", {id: "t1", status: "completed"}),
  pending("t2"),
  event("tool", "tool.started", {name: "read"}),
  event("started", "task.started", {status: "running"}),
  event("updated", "agent.updated", {id: "a1", status: "pending"}),
  pending("t3", {pending: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = TASK_PENDING_COUNT_UNAVAILABLE;
cases.hidden = taskPendingCountView(log, {visible: false});
cases.hiddenDefault = taskPendingCountView(log);
cases.preview = taskPendingCountView(log, {visible: false});
cases.missingNull = taskPendingCountView(null, {visible: true});
cases.missingUndefined = taskPendingCountView(undefined, {visible: true});
cases.missingObject = taskPendingCountView({pending: 4, events: []}, {visible: true});
cases.empty = taskPendingCountView([], {visible: true});
cases.counted = taskPendingCountView(log, {visible: true});
cases.ignoresTaskCompleted = taskPendingCountView([
  event("done", "task.completed", {status: "pending", pending: 3}),
], {visible: true});
cases.ignoresTaskFailed = taskPendingCountView([
  event("failed", "task.failed", {status: "pending", pending: 2}),
], {visible: true});
cases.ignoresTaskStarted = taskPendingCountView([
  event("started", "task.started", {status: "pending", pending: 1}),
], {visible: true});
cases.ignoresToolStarted = taskPendingCountView([
  event("tool", "tool.started", {status: "pending", pending: 1}),
], {visible: true});
cases.ignoresAgentUpdated = taskPendingCountView([
  event("updated", "agent.updated", {status: "pending", pending: 6}),
], {visible: true});
cases.ignoresMissionWaiting = taskPendingCountView([
  event("waiting", "mission.waiting", {status: "pending", pending: 1}),
], {visible: true});
cases.ignoresBudget = taskPendingCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, pending: 1}),
], {visible: true});
cases.onePendingNotPayload = taskPendingCountView([
  pending("big", {pending: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = taskPendingCountView([null, {payload: {pending: 10}}, pending("one")], {visible: true});
cases.unreadableType = taskPendingCountView([
  pending("ok"),
  {id: "bad", event_type: 4, payload: {pending: 1}},
], {visible: true});
cases.missingType = taskPendingCountView([
  {id: "blank", payload: {pending: 7, status: "pending"}},
  pending("one"),
], {visible: true});
cases.prefix = taskPendingCountView(recordedTaskPendingCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = taskPendingCountView(recordedTaskPendingCountFeed(log, 0, true), {visible: true});
cases.prefixOne = taskPendingCountView(recordedTaskPendingCountFeed(log, 5, true), {visible: true});
cases.prefixAll = taskPendingCountView(recordedTaskPendingCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = taskPendingCountView(recordedTaskPendingCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedTaskPendingCountFeed(log, log.length - 1, false);
cases.unloadedView = taskPendingCountView(recordedTaskPendingCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedTaskPendingCountFeed([], -1, true);
cases.notArrayLog = recordedTaskPendingCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
