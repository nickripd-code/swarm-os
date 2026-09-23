import {
  recordedAgentKilledCountFeed, agentKilledCountView, AGENT_KILLED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const killed = (id, extra = {}) => event(id, "agent.killed", {id, status: "stopped", reason: "Human killed this agent", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  killed("k1"),
  event("task", "task.stopped", {reason: "Agent killed", status: "stopped"}),
  event("upd", "agent.updated", {id: "a1", status: "stopped"}),
  killed("k2"),
  event("retire", "agent.retired", {id: "a2"}),
  event("reparent", "agent.reparented", {id: "a3"}),
  event("stop", "mission.stopped", {reason: "user"}),
  killed("k3", {kills: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = AGENT_KILLED_COUNT_UNAVAILABLE;
cases.hidden = agentKilledCountView(log, {visible: false});
cases.hiddenDefault = agentKilledCountView(log);
cases.preview = agentKilledCountView(log, {visible: false});
cases.missingNull = agentKilledCountView(null, {visible: true});
cases.missingUndefined = agentKilledCountView(undefined, {visible: true});
cases.missingObject = agentKilledCountView({kills: 4, events: []}, {visible: true});
cases.empty = agentKilledCountView([], {visible: true});
cases.counted = agentKilledCountView(log, {visible: true});
cases.ignoresSpawned = agentKilledCountView([
  event("spawn", "agent.spawned", {kills: 3}),
], {visible: true});
cases.ignoresUpdated = agentKilledCountView([
  event("upd", "agent.updated", {status: "stopped", kills: 2}),
], {visible: true});
cases.ignoresRetired = agentKilledCountView([
  event("retire", "agent.retired", {kills: 1}),
], {visible: true});
cases.ignoresReparented = agentKilledCountView([
  event("reparent", "agent.reparented", {kills: 1}),
], {visible: true});
cases.ignoresTaskStopped = agentKilledCountView([
  event("task", "task.stopped", {reason: "Agent killed", kills: 4}),
], {visible: true});
cases.ignoresMissionStopped = agentKilledCountView([
  event("stop", "mission.stopped", {kills: 6}),
], {visible: true});
cases.ignoresMissionFailed = agentKilledCountView([
  event("fail", "mission.failed", {kills: 2}),
], {visible: true});
cases.ignoresBudget = agentKilledCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, kills: 1}),
], {visible: true});
cases.oneKillNotPayload = agentKilledCountView([
  killed("big", {kills: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = agentKilledCountView([null, {payload: {kills: 10}}, killed("one")], {visible: true});
cases.unreadableType = agentKilledCountView([
  killed("ok"),
  {id: "bad", event_type: 4, payload: {kills: 1}},
], {visible: true});
cases.missingType = agentKilledCountView([
  {id: "blank", payload: {kills: 7}},
  killed("one"),
], {visible: true});
cases.prefix = agentKilledCountView(recordedAgentKilledCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = agentKilledCountView(recordedAgentKilledCountFeed(log, 0, true), {visible: true});
cases.prefixOne = agentKilledCountView(recordedAgentKilledCountFeed(log, 5, true), {visible: true});
cases.prefixAll = agentKilledCountView(recordedAgentKilledCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = agentKilledCountView(recordedAgentKilledCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAgentKilledCountFeed(log, log.length - 1, false);
cases.unloadedView = agentKilledCountView(recordedAgentKilledCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAgentKilledCountFeed([], -1, true);
cases.notArrayLog = recordedAgentKilledCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
