import {
  recordedLeaseExpiredCountFeed, leaseExpiredCountView, LEASE_EXPIRED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const expired = (id, extra = {}) => event(id, "lease.expired", {
  scope: "mission", scope_id: "m1", lease_id: id, owner_id: "worker", ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  expired("e1"),
  event("claimed", "lease.claimed", {lease_id: "c1", scope: "mission"}),
  event("released", "lease.released", {lease_id: "r1", scope: "mission"}),
  event("job", "job.enqueued", {id: "j1", kind: "mission.agent_task"}),
  expired("e2"),
  event("done-job", "job.completed", {id: "j1"}),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  expired("e3", {expired: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = LEASE_EXPIRED_COUNT_UNAVAILABLE;
cases.hidden = leaseExpiredCountView(log, {visible: false});
cases.hiddenDefault = leaseExpiredCountView(log);
cases.preview = leaseExpiredCountView(log, {visible: false});
cases.missingNull = leaseExpiredCountView(null, {visible: true});
cases.missingUndefined = leaseExpiredCountView(undefined, {visible: true});
cases.missingObject = leaseExpiredCountView({expired: 4, events: []}, {visible: true});
cases.empty = leaseExpiredCountView([], {visible: true});
cases.counted = leaseExpiredCountView(log, {visible: true});
cases.ignoresClaimed = leaseExpiredCountView([
  event("claimed", "lease.claimed", {expired: 3}),
], {visible: true});
cases.ignoresReleased = leaseExpiredCountView([
  event("released", "lease.released", {expired: 2}),
], {visible: true});
cases.ignoresJob = leaseExpiredCountView([
  event("job", "job.enqueued", {expired: 1}),
  event("retry", "job.retry_scheduled", {expired: 1}),
  event("failed", "job.failed", {expired: 1}),
], {visible: true});
cases.ignoresTool = leaseExpiredCountView([
  event("tool", "tool.started", {expired: 6}),
], {visible: true});
cases.ignoresBudget = leaseExpiredCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, expired: 1}),
], {visible: true});
cases.oneExpiredNotPayload = leaseExpiredCountView([
  expired("big", {expired: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = leaseExpiredCountView([null, {payload: {expired: 10}}, expired("one")], {visible: true});
cases.unreadableType = leaseExpiredCountView([
  expired("ok"),
  {id: "bad", event_type: 4, payload: {expired: 1}},
], {visible: true});
cases.missingType = leaseExpiredCountView([
  {id: "blank", payload: {expired: 7}},
  expired("one"),
], {visible: true});
cases.prefix = leaseExpiredCountView(recordedLeaseExpiredCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = leaseExpiredCountView(recordedLeaseExpiredCountFeed(log, 0, true), {visible: true});
cases.prefixOne = leaseExpiredCountView(recordedLeaseExpiredCountFeed(log, 5, true), {visible: true});
cases.prefixAll = leaseExpiredCountView(recordedLeaseExpiredCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = leaseExpiredCountView(recordedLeaseExpiredCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLeaseExpiredCountFeed(log, log.length - 1, false);
cases.unloadedView = leaseExpiredCountView(recordedLeaseExpiredCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLeaseExpiredCountFeed([], -1, true);
cases.notArrayLog = recordedLeaseExpiredCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
