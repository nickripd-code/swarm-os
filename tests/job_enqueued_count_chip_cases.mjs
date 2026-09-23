import {
  recordedJobEnqueuedCountFeed, jobEnqueuedCountView, JOB_ENQUEUED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const enqueued = (id, extra = {}) => event(id, "job.enqueued", {
  id, kind: "mission.agent_task", status: "pending", attempt: 0, ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  enqueued("j1"),
  event("claimed", "lease.claimed", {lease_id: "c1", scope: "job"}),
  event("expired", "lease.expired", {lease_id: "e1", scope: "job"}),
  event("released", "lease.released", {lease_id: "r1", scope: "job"}),
  enqueued("j2"),
  event("done-job", "job.completed", {id: "j1"}),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  enqueued("j3", {attempt: 2, token_spent: 4}),
];

const cases = {};
cases.unavailable = JOB_ENQUEUED_COUNT_UNAVAILABLE;
cases.hidden = jobEnqueuedCountView(log, {visible: false});
cases.hiddenDefault = jobEnqueuedCountView(log);
cases.preview = jobEnqueuedCountView(log, {visible: false});
cases.missingNull = jobEnqueuedCountView(null, {visible: true});
cases.missingUndefined = jobEnqueuedCountView(undefined, {visible: true});
cases.missingObject = jobEnqueuedCountView({enqueued: 4, events: []}, {visible: true});
cases.empty = jobEnqueuedCountView([], {visible: true});
cases.counted = jobEnqueuedCountView(log, {visible: true});
cases.ignoresCompleted = jobEnqueuedCountView([
  event("done", "job.completed", {enqueued: 3}),
], {visible: true});
cases.ignoresFailed = jobEnqueuedCountView([
  event("failed", "job.failed", {enqueued: 2}),
], {visible: true});
cases.ignoresRetry = jobEnqueuedCountView([
  event("retry", "job.retry_scheduled", {enqueued: 1}),
], {visible: true});
cases.ignoresLease = jobEnqueuedCountView([
  event("claimed", "lease.claimed", {enqueued: 1}),
  event("expired", "lease.expired", {enqueued: 1}),
  event("released", "lease.released", {enqueued: 1}),
], {visible: true});
cases.ignoresTool = jobEnqueuedCountView([
  event("tool", "tool.started", {enqueued: 6}),
], {visible: true});
cases.ignoresBudget = jobEnqueuedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, enqueued: 1}),
], {visible: true});
cases.oneEnqueuedNotPayload = jobEnqueuedCountView([
  enqueued("big", {enqueued: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = jobEnqueuedCountView([null, {payload: {enqueued: 10}}, enqueued("one")], {visible: true});
cases.unreadableType = jobEnqueuedCountView([
  enqueued("ok"),
  {id: "bad", event_type: 4, payload: {enqueued: 1}},
], {visible: true});
cases.missingType = jobEnqueuedCountView([
  {id: "blank", payload: {enqueued: 7}},
  enqueued("one"),
], {visible: true});
cases.prefix = jobEnqueuedCountView(recordedJobEnqueuedCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = jobEnqueuedCountView(recordedJobEnqueuedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = jobEnqueuedCountView(recordedJobEnqueuedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = jobEnqueuedCountView(recordedJobEnqueuedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = jobEnqueuedCountView(recordedJobEnqueuedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedJobEnqueuedCountFeed(log, log.length - 1, false);
cases.unloadedView = jobEnqueuedCountView(recordedJobEnqueuedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedJobEnqueuedCountFeed([], -1, true);
cases.notArrayLog = recordedJobEnqueuedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
