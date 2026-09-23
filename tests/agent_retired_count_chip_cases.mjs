import {
  recordedAgentRetiredCountFeed, agentRetiredCountView, AGENT_RETIRED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const retired = (id, extra = {}) => event(id, "agent.retired", {id, status: "stopped", reason: "retired", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  retired("r1"),
  event("task", "task.stopped", {reason: "Agent retired", status: "stopped"}),
  event("upd", "agent.updated", {id: "a1", status: "stopped"}),
  retired("r2"),
  event("killed", "agent.killed", {id: "a2", reason: "Human killed this agent"}),
  event("reparent", "agent.reparented", {id: "a3"}),
  event("org", "org.changed", {op: "retire"}),
  event("stop", "mission.stopped", {reason: "user"}),
  retired("r3", {retired: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = AGENT_RETIRED_COUNT_UNAVAILABLE;
cases.hidden = agentRetiredCountView(log, {visible: false});
cases.hiddenDefault = agentRetiredCountView(log);
cases.preview = agentRetiredCountView(log, {visible: false});
cases.missingNull = agentRetiredCountView(null, {visible: true});
cases.missingUndefined = agentRetiredCountView(undefined, {visible: true});
cases.missingObject = agentRetiredCountView({retired: 4, events: []}, {visible: true});
cases.empty = agentRetiredCountView([], {visible: true});
cases.counted = agentRetiredCountView(log, {visible: true});
cases.ignoresSpawned = agentRetiredCountView([
  event("spawn", "agent.spawned", {retired: 3}),
], {visible: true});
cases.ignoresUpdated = agentRetiredCountView([
  event("upd", "agent.updated", {status: "stopped", retired: 2}),
], {visible: true});
cases.ignoresKilled = agentRetiredCountView([
  event("killed", "agent.killed", {retired: 1}),
], {visible: true});
cases.ignoresReparented = agentRetiredCountView([
  event("reparent", "agent.reparented", {retired: 1}),
], {visible: true});
cases.ignoresOrgChanged = agentRetiredCountView([
  event("org", "org.changed", {op: "retire", retired: 2}),
], {visible: true});
cases.ignoresTaskStopped = agentRetiredCountView([
  event("task", "task.stopped", {reason: "retired", retired: 4}),
], {visible: true});
cases.ignoresMissionStopped = agentRetiredCountView([
  event("stop", "mission.stopped", {retired: 6}),
], {visible: true});
cases.ignoresMissionFailed = agentRetiredCountView([
  event("fail", "mission.failed", {retired: 2}),
], {visible: true});
cases.ignoresBudget = agentRetiredCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, retired: 1}),
], {visible: true});
cases.oneRetireNotPayload = agentRetiredCountView([
  retired("big", {retired: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = agentRetiredCountView([null, {payload: {retired: 10}}, retired("one")], {visible: true});
cases.unreadableType = agentRetiredCountView([
  retired("ok"),
  {id: "bad", event_type: 4, payload: {retired: 1}},
], {visible: true});
cases.missingType = agentRetiredCountView([
  {id: "blank", payload: {retired: 7}},
  retired("one"),
], {visible: true});
cases.prefix = agentRetiredCountView(recordedAgentRetiredCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = agentRetiredCountView(recordedAgentRetiredCountFeed(log, 0, true), {visible: true});
cases.prefixOne = agentRetiredCountView(recordedAgentRetiredCountFeed(log, 5, true), {visible: true});
cases.prefixAll = agentRetiredCountView(recordedAgentRetiredCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = agentRetiredCountView(recordedAgentRetiredCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAgentRetiredCountFeed(log, log.length - 1, false);
cases.unloadedView = agentRetiredCountView(recordedAgentRetiredCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAgentRetiredCountFeed([], -1, true);
cases.notArrayLog = recordedAgentRetiredCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
