import {
  recordedJobRetryScheduledCountFeed, jobRetryScheduledCountView, JOB_RETRY_SCHEDULED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const scheduled = (id, extra = {}) => event(id, "job.retry_scheduled", {
  id, kind: "mission.agent_task", status: "pending", attempt: 2, ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("queued", "job.enqueued", {id: "j1", kind: "mission.agent_task", status: "pending", attempt: 0}),
  event("claimed", "lease.claimed", {lease_id: "c1", scope: "job"}),
  event("expired", "lease.expired", {lease_id: "e1", scope: "job"}),
  event("released", "lease.released", {lease_id: "r1", scope: "job"}),
  scheduled("j1"),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  event("tool-done", "tool.completed", {name: "echo"}),
  event("mission-done", "mission.completed", {status: "completed"}),
  event("task-done", "task.completed", {id: "t1"}),
  event("completed", "job.completed", {id: "j8", status: "completed"}),
  event("failed", "job.failed", {id: "j9", attempt: 1}),
  scheduled("j2", {attempt: 3, token_spent: 4}),
  scheduled("j3"),
];

const cases = {};
cases.unavailable = JOB_RETRY_SCHEDULED_COUNT_UNAVAILABLE;
cases.hidden = jobRetryScheduledCountView(log, {visible: false});
cases.hiddenDefault = jobRetryScheduledCountView(log);
cases.preview = jobRetryScheduledCountView(log, {visible: false});
cases.missingNull = jobRetryScheduledCountView(null, {visible: true});
cases.missingUndefined = jobRetryScheduledCountView(undefined, {visible: true});
cases.missingObject = jobRetryScheduledCountView({scheduled: 4, events: []}, {visible: true});
cases.empty = jobRetryScheduledCountView([], {visible: true});
cases.counted = jobRetryScheduledCountView(log, {visible: true});
cases.ignoresEnqueued = jobRetryScheduledCountView([
  event("queued", "job.enqueued", {scheduled: 3}),
], {visible: true});
cases.ignoresCompleted = jobRetryScheduledCountView([
  event("completed", "job.completed", {scheduled: 2}),
], {visible: true});
cases.ignoresFailed = jobRetryScheduledCountView([
  event("failed", "job.failed", {scheduled: 1}),
], {visible: true});
cases.ignoresLlmRetry = jobRetryScheduledCountView([
  event("llm", "llm.retry", {scheduled: 4}),
], {visible: true});
cases.ignoresLease = jobRetryScheduledCountView([
  event("claimed", "lease.claimed", {scheduled: 1}),
  event("expired", "lease.expired", {scheduled: 1}),
  event("released", "lease.released", {scheduled: 1}),
], {visible: true});
cases.ignoresTool = jobRetryScheduledCountView([
  event("tool", "tool.started", {scheduled: 6}),
  event("tool-done", "tool.completed", {scheduled: 6}),
], {visible: true});
cases.ignoresMissionFailed = jobRetryScheduledCountView([
  event("mission-fail", "mission.failed", {scheduled: 1, failure_class: "TOOL_MISSING"}),
], {visible: true});
cases.ignoresMissionCompleted = jobRetryScheduledCountView([
  event("mission-done", "mission.completed", {scheduled: 1}),
], {visible: true});
cases.ignoresTask = jobRetryScheduledCountView([
  event("task-fail", "task.failed", {scheduled: 1}),
  event("task-done", "task.completed", {scheduled: 1}),
], {visible: true});
cases.ignoresBudget = jobRetryScheduledCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, scheduled: 1}),
], {visible: true});
cases.oneScheduledNotPayload = jobRetryScheduledCountView([
  scheduled("big", {scheduled: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = jobRetryScheduledCountView([null, {payload: {scheduled: 10}}, scheduled("one")], {visible: true});
cases.unreadableType = jobRetryScheduledCountView([
  scheduled("ok"),
  {id: "bad", event_type: 4, payload: {scheduled: 1}},
], {visible: true});
cases.missingType = jobRetryScheduledCountView([
  {id: "blank", payload: {scheduled: 7}},
  scheduled("one"),
], {visible: true});
cases.prefix = jobRetryScheduledCountView(recordedJobRetryScheduledCountFeed(log, 5, true), {visible: true});
cases.prefixFirst = jobRetryScheduledCountView(recordedJobRetryScheduledCountFeed(log, 0, true), {visible: true});
cases.prefixTwo = jobRetryScheduledCountView(recordedJobRetryScheduledCountFeed(log, 12, true), {visible: true});
cases.prefixAll = jobRetryScheduledCountView(recordedJobRetryScheduledCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = jobRetryScheduledCountView(recordedJobRetryScheduledCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedJobRetryScheduledCountFeed(log, log.length - 1, false);
cases.unloadedView = jobRetryScheduledCountView(recordedJobRetryScheduledCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedJobRetryScheduledCountFeed([], -1, true);
cases.notArrayLog = recordedJobRetryScheduledCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
