import {
  recordedLeaseClaimedCountFeed, leaseClaimedCountView, LEASE_CLAIMED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const claim = (id, extra = {}) => event(id, "lease.claimed", {
  scope: "mission", scope_id: "m1", lease_id: id, owner_id: "worker", reclaimed: false, ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  claim("c1"),
  event("expired", "lease.expired", {lease_id: "old", scope: "mission"}),
  event("released", "lease.released", {lease_id: "c0", scope: "task"}),
  event("job", "job.enqueued", {id: "j1", kind: "mission.agent_task"}),
  claim("c2"),
  event("done-job", "job.completed", {id: "j1"}),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  claim("c3", {claims: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = LEASE_CLAIMED_COUNT_UNAVAILABLE;
cases.hidden = leaseClaimedCountView(log, {visible: false});
cases.hiddenDefault = leaseClaimedCountView(log);
cases.preview = leaseClaimedCountView(log, {visible: false});
cases.missingNull = leaseClaimedCountView(null, {visible: true});
cases.missingUndefined = leaseClaimedCountView(undefined, {visible: true});
cases.missingObject = leaseClaimedCountView({claims: 4, events: []}, {visible: true});
cases.empty = leaseClaimedCountView([], {visible: true});
cases.counted = leaseClaimedCountView(log, {visible: true});
cases.ignoresExpired = leaseClaimedCountView([
  event("expired", "lease.expired", {claims: 3}),
], {visible: true});
cases.ignoresReleased = leaseClaimedCountView([
  event("released", "lease.released", {claims: 2}),
], {visible: true});
cases.ignoresJob = leaseClaimedCountView([
  event("job", "job.enqueued", {claims: 1}),
  event("retry", "job.retry_scheduled", {claims: 1}),
  event("failed", "job.failed", {claims: 1}),
], {visible: true});
cases.ignoresTool = leaseClaimedCountView([
  event("tool", "tool.started", {claims: 6}),
], {visible: true});
cases.ignoresBudget = leaseClaimedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, claims: 1}),
], {visible: true});
cases.oneClaimNotPayload = leaseClaimedCountView([
  claim("big", {claims: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = leaseClaimedCountView([null, {payload: {claims: 10}}, claim("one")], {visible: true});
cases.unreadableType = leaseClaimedCountView([
  claim("ok"),
  {id: "bad", event_type: 4, payload: {claims: 1}},
], {visible: true});
cases.missingType = leaseClaimedCountView([
  {id: "blank", payload: {claims: 7}},
  claim("one"),
], {visible: true});
cases.prefix = leaseClaimedCountView(recordedLeaseClaimedCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = leaseClaimedCountView(recordedLeaseClaimedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = leaseClaimedCountView(recordedLeaseClaimedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = leaseClaimedCountView(recordedLeaseClaimedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = leaseClaimedCountView(recordedLeaseClaimedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLeaseClaimedCountFeed(log, log.length - 1, false);
cases.unloadedView = leaseClaimedCountView(recordedLeaseClaimedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLeaseClaimedCountFeed([], -1, true);
cases.notArrayLog = recordedLeaseClaimedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
