import {
  recordedOrgChangedCountFeed, orgChangedCountView, ORG_CHANGED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-09-23T12:35:04Z"};
}

const changed = (id, extra = {}) => event(id, "org.changed", {
  op: "spawn", agent_id: id, ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  changed("c1"),
  event("spawned", "agent.spawned", {id: "a1", role: "researcher"}),
  event("updated", "agent.updated", {id: "a1", status: "running"}),
  event("reparented", "agent.reparented", {id: "a1", parent_id: "root"}),
  changed("c2"),
  event("retired", "agent.retired", {id: "a2"}),
  event("killed", "agent.killed", {id: "a3"}),
  event("tool", "tool.failed", {name: "echo"}),
  changed("c3", {count: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = ORG_CHANGED_COUNT_UNAVAILABLE;
cases.hidden = orgChangedCountView(log, {visible: false});
cases.hiddenDefault = orgChangedCountView(log);
cases.preview = orgChangedCountView(log, {visible: false});
cases.missingNull = orgChangedCountView(null, {visible: true});
cases.missingUndefined = orgChangedCountView(undefined, {visible: true});
cases.missingObject = orgChangedCountView({count: 4, events: []}, {visible: true});
cases.empty = orgChangedCountView([], {visible: true});
cases.counted = orgChangedCountView(log, {visible: true});
cases.ignoresSpawned = orgChangedCountView([
  event("spawned", "agent.spawned", {count: 3}),
], {visible: true});
cases.ignoresUpdated = orgChangedCountView([
  event("updated", "agent.updated", {count: 2}),
], {visible: true});
cases.ignoresReparented = orgChangedCountView([
  event("reparented", "agent.reparented", {count: 2}),
], {visible: true});
cases.ignoresRetired = orgChangedCountView([
  event("retired", "agent.retired", {count: 2}),
], {visible: true});
cases.ignoresKilled = orgChangedCountView([
  event("killed", "agent.killed", {count: 2}),
], {visible: true});
cases.ignoresToolFailed = orgChangedCountView([
  event("tool", "tool.failed", {count: 6}),
], {visible: true});
cases.ignoresBudget = orgChangedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, count: 1}),
], {visible: true});
cases.oneChangeNotPayload = orgChangedCountView([
  changed("big", {count: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = orgChangedCountView([null, {payload: {count: 10}}, changed("one")], {visible: true});
cases.unreadableType = orgChangedCountView([
  changed("ok"),
  {id: "bad", event_type: 4, payload: {count: 1}},
], {visible: true});
cases.missingType = orgChangedCountView([
  {id: "blank", payload: {count: 7}},
  changed("one"),
], {visible: true});
cases.prefix = orgChangedCountView(recordedOrgChangedCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = orgChangedCountView(recordedOrgChangedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = orgChangedCountView(recordedOrgChangedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = orgChangedCountView(recordedOrgChangedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = orgChangedCountView(recordedOrgChangedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedOrgChangedCountFeed(log, log.length - 1, false);
cases.unloadedView = orgChangedCountView(recordedOrgChangedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedOrgChangedCountFeed([], -1, true);
cases.notArrayLog = recordedOrgChangedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
