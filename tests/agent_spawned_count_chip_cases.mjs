import {
  recordedAgentSpawnedCountFeed, agentSpawnedCountView, AGENT_SPAWNED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const spawned = (id, extra = {}) => event(id, "agent.spawned", {id, role: "researcher", status: "created", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  spawned("s1"),
  event("upd", "agent.updated", {id: "s1", status: "running"}),
  event("kill", "agent.killed", {id: "s1", status: "stopped"}),
  event("task", "task.stopped", {reason: "Agent killed", status: "stopped"}),
  spawned("s2"),
  event("retire", "agent.retired", {id: "s3"}),
  event("reparent", "agent.reparented", {id: "s4"}),
  event("stop", "mission.stopped", {reason: "user"}),
  spawned("s5", {spawned: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = AGENT_SPAWNED_COUNT_UNAVAILABLE;
cases.hidden = agentSpawnedCountView(log, {visible: false});
cases.hiddenDefault = agentSpawnedCountView(log);
cases.preview = agentSpawnedCountView(log, {visible: false});
cases.missingNull = agentSpawnedCountView(null, {visible: true});
cases.missingUndefined = agentSpawnedCountView(undefined, {visible: true});
cases.missingObject = agentSpawnedCountView({spawned: 4, events: []}, {visible: true});
cases.empty = agentSpawnedCountView([], {visible: true});
cases.counted = agentSpawnedCountView(log, {visible: true});
cases.ignoresUpdated = agentSpawnedCountView([
  event("upd", "agent.updated", {spawned: 3, status: "running"}),
], {visible: true});
cases.ignoresKilled = agentSpawnedCountView([
  event("kill", "agent.killed", {spawned: 2, status: "stopped"}),
], {visible: true});
cases.ignoresRetired = agentSpawnedCountView([
  event("retire", "agent.retired", {spawned: 1}),
], {visible: true});
cases.ignoresReparented = agentSpawnedCountView([
  event("reparent", "agent.reparented", {spawned: 1}),
], {visible: true});
cases.ignoresMessage = agentSpawnedCountView([
  event("msg", "agent.message", {spawned: 4, text: "joined"}),
], {visible: true});
cases.ignoresTaskStarted = agentSpawnedCountView([
  event("task", "task.started", {spawned: 5}),
], {visible: true});
cases.ignoresMissionStarted = agentSpawnedCountView([
  event("start", "mission.started", {spawned: 6}),
], {visible: true});
cases.ignoresBudget = agentSpawnedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, spawned: 1}),
], {visible: true});
cases.oneSpawnNotPayload = agentSpawnedCountView([
  spawned("big", {spawned: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = agentSpawnedCountView([null, {payload: {spawned: 10}}, spawned("one")], {visible: true});
cases.unreadableType = agentSpawnedCountView([
  spawned("ok"),
  {id: "bad", event_type: 4, payload: {spawned: 1}},
], {visible: true});
cases.missingType = agentSpawnedCountView([
  {id: "blank", payload: {spawned: 7}},
  spawned("one"),
], {visible: true});
cases.prefix = agentSpawnedCountView(recordedAgentSpawnedCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = agentSpawnedCountView(recordedAgentSpawnedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = agentSpawnedCountView(recordedAgentSpawnedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = agentSpawnedCountView(recordedAgentSpawnedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = agentSpawnedCountView(recordedAgentSpawnedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAgentSpawnedCountFeed(log, log.length - 1, false);
cases.unloadedView = agentSpawnedCountView(recordedAgentSpawnedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAgentSpawnedCountFeed([], -1, true);
cases.notArrayLog = recordedAgentSpawnedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
