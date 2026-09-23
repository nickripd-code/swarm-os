import {
  recordedAgentUpdatedCountFeed, agentUpdatedCountView, AGENT_UPDATED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const updated = (id, extra = {}) => event(id, "agent.updated", {id, status: "running", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  updated("u1"),
  event("task", "task.stopped", {reason: "Agent updated", status: "stopped"}),
  event("retired", "agent.retired", {id: "a1", status: "stopped"}),
  updated("u2"),
  event("killed", "agent.killed", {id: "a2", reason: "Human killed this agent"}),
  event("reparent", "agent.reparented", {id: "a3"}),
  event("org", "org.changed", {op: "reparent"}),
  event("budget", "budget.updated", {known: true, token_spent: 1}),
  event("stop", "mission.stopped", {reason: "user"}),
  updated("u3", {updated: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = AGENT_UPDATED_COUNT_UNAVAILABLE;
cases.hidden = agentUpdatedCountView(log, {visible: false});
cases.hiddenDefault = agentUpdatedCountView(log);
cases.preview = agentUpdatedCountView(log, {visible: false});
cases.missingNull = agentUpdatedCountView(null, {visible: true});
cases.missingUndefined = agentUpdatedCountView(undefined, {visible: true});
cases.missingObject = agentUpdatedCountView({updated: 4, events: []}, {visible: true});
cases.empty = agentUpdatedCountView([], {visible: true});
cases.counted = agentUpdatedCountView(log, {visible: true});
cases.ignoresSpawned = agentUpdatedCountView([
  event("spawn", "agent.spawned", {updated: 3}),
], {visible: true});
cases.ignoresRetired = agentUpdatedCountView([
  event("retired", "agent.retired", {status: "stopped", updated: 2}),
], {visible: true});
cases.ignoresKilled = agentUpdatedCountView([
  event("killed", "agent.killed", {updated: 1}),
], {visible: true});
cases.ignoresReparented = agentUpdatedCountView([
  event("reparent", "agent.reparented", {updated: 1}),
], {visible: true});
cases.ignoresOrgChanged = agentUpdatedCountView([
  event("org", "org.changed", {op: "update", updated: 2}),
], {visible: true});
cases.ignoresTaskStopped = agentUpdatedCountView([
  event("task", "task.stopped", {reason: "updated", updated: 4}),
], {visible: true});
cases.ignoresMissionStopped = agentUpdatedCountView([
  event("stop", "mission.stopped", {updated: 6}),
], {visible: true});
cases.ignoresMissionFailed = agentUpdatedCountView([
  event("fail", "mission.failed", {updated: 2}),
], {visible: true});
cases.ignoresBudget = agentUpdatedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, updated: 1}),
], {visible: true});
cases.oneUpdateNotPayload = agentUpdatedCountView([
  updated("big", {updated: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = agentUpdatedCountView([null, {payload: {updated: 10}}, updated("one")], {visible: true});
cases.unreadableType = agentUpdatedCountView([
  updated("ok"),
  {id: "bad", event_type: 4, payload: {updated: 1}},
], {visible: true});
cases.missingType = agentUpdatedCountView([
  {id: "blank", payload: {updated: 7}},
  updated("one"),
], {visible: true});
cases.prefix = agentUpdatedCountView(recordedAgentUpdatedCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = agentUpdatedCountView(recordedAgentUpdatedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = agentUpdatedCountView(recordedAgentUpdatedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = agentUpdatedCountView(recordedAgentUpdatedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = agentUpdatedCountView(recordedAgentUpdatedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAgentUpdatedCountFeed(log, log.length - 1, false);
cases.unloadedView = agentUpdatedCountView(recordedAgentUpdatedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAgentUpdatedCountFeed([], -1, true);
cases.notArrayLog = recordedAgentUpdatedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
