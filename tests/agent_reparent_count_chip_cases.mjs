import {
  recordedAgentReparentCountFeed, agentReparentCountView, AGENT_REPARENT_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const reparent = (id, extra = {}) => event(id, "agent.reparented", {
  id, parent_id: "root", previous_parent_id: "lead", depth: 2, role: "researcher", ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  reparent("r1"),
  event("org", "org.changed", {op: "reparent", agent_id: "a1"}),
  event("upd", "agent.updated", {id: "a1", parent_id: "root"}),
  reparent("r2"),
  event("retire", "agent.retired", {id: "a2"}),
  event("kill", "agent.killed", {id: "a3"}),
  event("done", "mission.completed", {result: "ok"}),
  reparent("r3", {reparents: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = AGENT_REPARENT_COUNT_UNAVAILABLE;
cases.hidden = agentReparentCountView(log, {visible: false});
cases.hiddenDefault = agentReparentCountView(log);
cases.preview = agentReparentCountView(log, {visible: false});
cases.missingNull = agentReparentCountView(null, {visible: true});
cases.missingUndefined = agentReparentCountView(undefined, {visible: true});
cases.missingObject = agentReparentCountView({reparents: 4, events: []}, {visible: true});
cases.empty = agentReparentCountView([], {visible: true});
cases.counted = agentReparentCountView(log, {visible: true});
cases.ignoresSpawned = agentReparentCountView([
  event("spawn", "agent.spawned", {reparents: 3}),
], {visible: true});
cases.ignoresUpdated = agentReparentCountView([
  event("upd", "agent.updated", {parent_id: "root", reparents: 2}),
], {visible: true});
cases.ignoresRetired = agentReparentCountView([
  event("retire", "agent.retired", {reparents: 1}),
], {visible: true});
cases.ignoresKilled = agentReparentCountView([
  event("kill", "agent.killed", {reparents: 1}),
], {visible: true});
cases.ignoresOrgChanged = agentReparentCountView([
  event("org", "org.changed", {op: "reparent", reparents: 4}),
], {visible: true});
cases.ignoresCompleted = agentReparentCountView([
  event("done", "mission.completed", {reparents: 6}),
], {visible: true});
cases.ignoresBudget = agentReparentCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, reparents: 1}),
], {visible: true});
cases.oneReparentNotPayload = agentReparentCountView([
  reparent("big", {reparents: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = agentReparentCountView([null, {payload: {reparents: 10}}, reparent("one")], {visible: true});
cases.unreadableType = agentReparentCountView([
  reparent("ok"),
  {id: "bad", event_type: 4, payload: {reparents: 1}},
], {visible: true});
cases.missingType = agentReparentCountView([
  {id: "blank", payload: {reparents: 7}},
  reparent("one"),
], {visible: true});
cases.prefix = agentReparentCountView(recordedAgentReparentCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = agentReparentCountView(recordedAgentReparentCountFeed(log, 0, true), {visible: true});
cases.prefixOne = agentReparentCountView(recordedAgentReparentCountFeed(log, 5, true), {visible: true});
cases.prefixAll = agentReparentCountView(recordedAgentReparentCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = agentReparentCountView(recordedAgentReparentCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAgentReparentCountFeed(log, log.length - 1, false);
cases.unloadedView = agentReparentCountView(recordedAgentReparentCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAgentReparentCountFeed([], -1, true);
cases.notArrayLog = recordedAgentReparentCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
