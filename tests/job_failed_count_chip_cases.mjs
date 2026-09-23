import {
  recordedJobFailedCountFeed, jobFailedCountView, JOB_FAILED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "job.failed", {
  id, kind: "mission.agent_task", status: "failed", attempt: 1, ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("queued", "job.enqueued", {id: "j1", kind: "mission.agent_task", status: "pending", attempt: 0}),
  event("claimed", "lease.claimed", {lease_id: "c1", scope: "job"}),
  event("expired", "lease.expired", {lease_id: "e1", scope: "job"}),
  event("released", "lease.released", {lease_id: "r1", scope: "job"}),
  failed("j1"),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  event("tool-done", "tool.completed", {name: "echo"}),
  event("mission-done", "mission.completed", {status: "completed"}),
  event("task-done", "task.completed", {id: "t1"}),
  event("completed", "job.completed", {id: "j8", status: "completed"}),
  event("retry", "job.retry_scheduled", {id: "j9", attempt: 2}),
  failed("j2", {attempt: 2, token_spent: 4}),
  failed("j3"),
];

const cases = {};
cases.unavailable = JOB_FAILED_COUNT_UNAVAILABLE;
cases.hidden = jobFailedCountView(log, {visible: false});
cases.hiddenDefault = jobFailedCountView(log);
cases.preview = jobFailedCountView(log, {visible: false});
cases.missingNull = jobFailedCountView(null, {visible: true});
cases.missingUndefined = jobFailedCountView(undefined, {visible: true});
cases.missingObject = jobFailedCountView({failed: 4, events: []}, {visible: true});
cases.empty = jobFailedCountView([], {visible: true});
cases.counted = jobFailedCountView(log, {visible: true});
cases.ignoresEnqueued = jobFailedCountView([
  event("queued", "job.enqueued", {failed: 3}),
], {visible: true});
cases.ignoresCompleted = jobFailedCountView([
  event("completed", "job.completed", {failed: 2}),
], {visible: true});
cases.ignoresRetry = jobFailedCountView([
  event("retry", "job.retry_scheduled", {failed: 1}),
], {visible: true});
cases.ignoresLease = jobFailedCountView([
  event("claimed", "lease.claimed", {failed: 1}),
  event("expired", "lease.expired", {failed: 1}),
  event("released", "lease.released", {failed: 1}),
], {visible: true});
cases.ignoresTool = jobFailedCountView([
  event("tool", "tool.started", {failed: 6}),
  event("tool-done", "tool.completed", {failed: 6}),
], {visible: true});
cases.ignoresMissionFailed = jobFailedCountView([
  event("mission-fail", "mission.failed", {failed: 1, failure_class: "TOOL_MISSING"}),
], {visible: true});
cases.ignoresMissionCompleted = jobFailedCountView([
  event("mission-done", "mission.completed", {failed: 1}),
], {visible: true});
cases.ignoresTask = jobFailedCountView([
  event("task-fail", "task.failed", {failed: 1}),
  event("task-done", "task.completed", {failed: 1}),
], {visible: true});
cases.ignoresBudget = jobFailedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, failed: 1}),
], {visible: true});
cases.oneFailedNotPayload = jobFailedCountView([
  failed("big", {failed: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = jobFailedCountView([null, {payload: {failed: 10}}, failed("one")], {visible: true});
cases.unreadableType = jobFailedCountView([
  failed("ok"),
  {id: "bad", event_type: 4, payload: {failed: 1}},
], {visible: true});
cases.missingType = jobFailedCountView([
  {id: "blank", payload: {failed: 7}},
  failed("one"),
], {visible: true});
cases.prefix = jobFailedCountView(recordedJobFailedCountFeed(log, 5, true), {visible: true});
cases.prefixFirst = jobFailedCountView(recordedJobFailedCountFeed(log, 0, true), {visible: true});
cases.prefixTwo = jobFailedCountView(recordedJobFailedCountFeed(log, 12, true), {visible: true});
cases.prefixAll = jobFailedCountView(recordedJobFailedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = jobFailedCountView(recordedJobFailedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedJobFailedCountFeed(log, log.length - 1, false);
cases.unloadedView = jobFailedCountView(recordedJobFailedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedJobFailedCountFeed([], -1, true);
cases.notArrayLog = recordedJobFailedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
