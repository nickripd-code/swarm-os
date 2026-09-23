import {
  recordedAgentMessageCountFeed, agentMessageCountView, AGENT_MESSAGE_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const message = (id, extra = {}) => event(id, "agent.message", {
  from_id: "a1", to_id: "root", kind: "result", text: "recorded", ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  message("m1"),
  event("done", "task.completed", {id: "t2", status: "completed"}),
  event("llm", "llm.completed", {input_tokens: 3, output_tokens: 4}),
  event("tool", "tool.completed", {name: "echo"}),
  message("m2"),
  event("question", "mission.question", {question: "Which group?"}),
  event("answer", "user.answered", {text: "First group"}),
  event("budget", "budget.updated", {known: true, token_spent: 1}),
  event("updated", "agent.updated", {id: "a1", status: "running"}),
  message("m3", {text: "third", count: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = AGENT_MESSAGE_COUNT_UNAVAILABLE;
cases.hidden = agentMessageCountView(log, {visible: false});
cases.hiddenDefault = agentMessageCountView(log);
cases.preview = agentMessageCountView(log, {visible: false});
cases.missingNull = agentMessageCountView(null, {visible: true});
cases.missingUndefined = agentMessageCountView(undefined, {visible: true});
cases.missingObject = agentMessageCountView({messages: 4, events: []}, {visible: true});
cases.empty = agentMessageCountView([], {visible: true});
cases.counted = agentMessageCountView(log, {visible: true});
cases.ignoresAgentUpdated = agentMessageCountView([
  event("updated", "agent.updated", {text: "hello", kind: "result"}),
], {visible: true});
cases.ignoresSpawned = agentMessageCountView([
  event("spawn", "agent.spawned", {text: "assignment", kind: "assignment"}),
], {visible: true});
cases.ignoresKilled = agentMessageCountView([
  event("killed", "agent.killed", {text: "stopped"}),
], {visible: true});
cases.ignoresQuestion = agentMessageCountView([
  event("question", "mission.question", {question: "Need a decision"}),
], {visible: true});
cases.ignoresAnswer = agentMessageCountView([
  event("answer", "user.answered", {text: "yes"}),
], {visible: true});
cases.ignoresLlm = agentMessageCountView([
  event("llm", "llm.completed", {text: "model said hello"}),
], {visible: true});
cases.ignoresTool = agentMessageCountView([
  event("tool", "tool.completed", {text: "tool output"}),
], {visible: true});
cases.ignoresPaused = agentMessageCountView([
  event("paused", "mission.paused", {text: "paused"}),
], {visible: true});
cases.ignoresBudget = agentMessageCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, text: "spend"}),
], {visible: true});
cases.oneMessageNotPayload = agentMessageCountView([
  message("big", {count: 5000, token_spent: 12, text: "one recorded message"}),
], {visible: true});
cases.skipsHoles = agentMessageCountView([null, {payload: {text: "ghost"}}, message("one")], {visible: true});
cases.unreadableType = agentMessageCountView([
  message("ok"),
  {id: "bad", event_type: 4, payload: {text: "no"}},
], {visible: true});
cases.missingType = agentMessageCountView([
  {id: "blank", payload: {text: "missing type"}},
  message("one"),
], {visible: true});
cases.prefix = agentMessageCountView(recordedAgentMessageCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = agentMessageCountView(recordedAgentMessageCountFeed(log, 0, true), {visible: true});
cases.prefixOne = agentMessageCountView(recordedAgentMessageCountFeed(log, 6, true), {visible: true});
cases.prefixAll = agentMessageCountView(recordedAgentMessageCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = agentMessageCountView(recordedAgentMessageCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAgentMessageCountFeed(log, log.length - 1, false);
cases.unloadedView = agentMessageCountView(recordedAgentMessageCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAgentMessageCountFeed([], -1, true);
cases.notArrayLog = recordedAgentMessageCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
