import {
  recordedJobCompletedCountFeed, jobCompletedCountView, JOB_COMPLETED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const completed = (id, extra = {}) => event(id, "job.completed", {
  id, kind: "mission.agent_task", status: "completed", attempt: 1, result: {}, ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("queued", "job.enqueued", {id: "j1", kind: "mission.agent_task", status: "pending", attempt: 0}),
  event("claimed", "lease.claimed", {lease_id: "c1", scope: "job"}),
  event("expired", "lease.expired", {lease_id: "e1", scope: "job"}),
  event("released", "lease.released", {lease_id: "r1", scope: "job"}),
  completed("j1"),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  event("tool-done", "tool.completed", {name: "echo"}),
  event("mission-done", "mission.completed", {status: "completed"}),
  event("task-done", "task.completed", {id: "t1"}),
  event("failed", "job.failed", {id: "j9", status: "failed"}),
  event("retry", "job.retry_scheduled", {id: "j9", attempt: 2}),
  completed("j2", {attempt: 2, token_spent: 4}),
  completed("j3"),
];

const cases = {};
cases.unavailable = JOB_COMPLETED_COUNT_UNAVAILABLE;
cases.hidden = jobCompletedCountView(log, {visible: false});
cases.hiddenDefault = jobCompletedCountView(log);
cases.preview = jobCompletedCountView(log, {visible: false});
cases.missingNull = jobCompletedCountView(null, {visible: true});
cases.missingUndefined = jobCompletedCountView(undefined, {visible: true});
cases.missingObject = jobCompletedCountView({completed: 4, events: []}, {visible: true});
cases.empty = jobCompletedCountView([], {visible: true});
cases.counted = jobCompletedCountView(log, {visible: true});
cases.ignoresEnqueued = jobCompletedCountView([
  event("queued", "job.enqueued", {completed: 3}),
], {visible: true});
cases.ignoresFailed = jobCompletedCountView([
  event("failed", "job.failed", {completed: 2}),
], {visible: true});
cases.ignoresRetry = jobCompletedCountView([
  event("retry", "job.retry_scheduled", {completed: 1}),
], {visible: true});
cases.ignoresLease = jobCompletedCountView([
  event("claimed", "lease.claimed", {completed: 1}),
  event("expired", "lease.expired", {completed: 1}),
  event("released", "lease.released", {completed: 1}),
], {visible: true});
cases.ignoresTool = jobCompletedCountView([
  event("tool", "tool.started", {completed: 6}),
  event("tool-done", "tool.completed", {completed: 6}),
], {visible: true});
cases.ignoresMission = jobCompletedCountView([
  event("mission-done", "mission.completed", {completed: 1}),
], {visible: true});
cases.ignoresTask = jobCompletedCountView([
  event("task-done", "task.completed", {completed: 1}),
], {visible: true});
cases.ignoresBudget = jobCompletedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, completed: 1}),
], {visible: true});
cases.oneCompletedNotPayload = jobCompletedCountView([
  completed("big", {completed: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = jobCompletedCountView([null, {payload: {completed: 10}}, completed("one")], {visible: true});
cases.unreadableType = jobCompletedCountView([
  completed("ok"),
  {id: "bad", event_type: 4, payload: {completed: 1}},
], {visible: true});
cases.missingType = jobCompletedCountView([
  {id: "blank", payload: {completed: 7}},
  completed("one"),
], {visible: true});
cases.prefix = jobCompletedCountView(recordedJobCompletedCountFeed(log, 5, true), {visible: true});
cases.prefixFirst = jobCompletedCountView(recordedJobCompletedCountFeed(log, 0, true), {visible: true});
cases.prefixTwo = jobCompletedCountView(recordedJobCompletedCountFeed(log, 12, true), {visible: true});
cases.prefixAll = jobCompletedCountView(recordedJobCompletedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = jobCompletedCountView(recordedJobCompletedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedJobCompletedCountFeed(log, log.length - 1, false);
cases.unloadedView = jobCompletedCountView(recordedJobCompletedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedJobCompletedCountFeed([], -1, true);
cases.notArrayLog = recordedJobCompletedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
