import {
  recordedLeaseReleasedCountFeed, leaseReleasedCountView, LEASE_RELEASED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const release = (id, extra = {}) => event(id, "lease.released", {
  scope: "mission", scope_id: "m1", lease_id: id, owner_id: "worker", ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  release("r1"),
  event("claimed", "lease.claimed", {lease_id: "c1", scope: "mission"}),
  event("expired", "lease.expired", {lease_id: "old", scope: "mission"}),
  event("job", "job.enqueued", {id: "j1", kind: "mission.agent_task"}),
  release("r2"),
  event("done-job", "job.completed", {id: "j1"}),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  release("r3", {releases: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = LEASE_RELEASED_COUNT_UNAVAILABLE;
cases.hidden = leaseReleasedCountView(log, {visible: false});
cases.hiddenDefault = leaseReleasedCountView(log);
cases.preview = leaseReleasedCountView(log, {visible: false});
cases.missingNull = leaseReleasedCountView(null, {visible: true});
cases.missingUndefined = leaseReleasedCountView(undefined, {visible: true});
cases.missingObject = leaseReleasedCountView({releases: 4, events: []}, {visible: true});
cases.empty = leaseReleasedCountView([], {visible: true});
cases.counted = leaseReleasedCountView(log, {visible: true});
cases.ignoresClaimed = leaseReleasedCountView([
  event("claimed", "lease.claimed", {releases: 3}),
], {visible: true});
cases.ignoresExpired = leaseReleasedCountView([
  event("expired", "lease.expired", {releases: 2}),
], {visible: true});
cases.ignoresJob = leaseReleasedCountView([
  event("job", "job.enqueued", {releases: 1}),
  event("retry", "job.retry_scheduled", {releases: 1}),
  event("failed", "job.failed", {releases: 1}),
], {visible: true});
cases.ignoresTool = leaseReleasedCountView([
  event("tool", "tool.started", {releases: 6}),
], {visible: true});
cases.ignoresBudget = leaseReleasedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, releases: 1}),
], {visible: true});
cases.oneReleaseNotPayload = leaseReleasedCountView([
  release("big", {releases: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = leaseReleasedCountView([null, {payload: {releases: 10}}, release("one")], {visible: true});
cases.unreadableType = leaseReleasedCountView([
  release("ok"),
  {id: "bad", event_type: 4, payload: {releases: 1}},
], {visible: true});
cases.missingType = leaseReleasedCountView([
  {id: "blank", payload: {releases: 7}},
  release("one"),
], {visible: true});
cases.prefix = leaseReleasedCountView(recordedLeaseReleasedCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = leaseReleasedCountView(recordedLeaseReleasedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = leaseReleasedCountView(recordedLeaseReleasedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = leaseReleasedCountView(recordedLeaseReleasedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = leaseReleasedCountView(recordedLeaseReleasedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLeaseReleasedCountFeed(log, log.length - 1, false);
cases.unloadedView = leaseReleasedCountView(recordedLeaseReleasedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLeaseReleasedCountFeed([], -1, true);
cases.notArrayLog = recordedLeaseReleasedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
