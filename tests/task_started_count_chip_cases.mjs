import {
  recordedTaskStartedCountFeed, taskStartedCountView, TASK_STARTED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id, extra = {}) => event(id, "task.started", {id, status: "running", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  started("t1"),
  event("pending", "task.pending", {id: "t2", status: "pending"}),
  event("failed", "task.failed", {id: "t3", status: "failed"}),
  event("done", "task.completed", {id: "t4", status: "completed"}),
  started("t5"),
  event("llm", "llm.started", {}),
  event("tool", "tool.started", {name: "read"}),
  event("verify", "verification.started", {}),
  event("budget", "budget.updated", {known: true, token_spent: 1}),
  started("t6", {started: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = TASK_STARTED_COUNT_UNAVAILABLE;
cases.hidden = taskStartedCountView(log, {visible: false});
cases.hiddenDefault = taskStartedCountView(log);
cases.preview = taskStartedCountView(log, {visible: false});
cases.missingNull = taskStartedCountView(null, {visible: true});
cases.missingUndefined = taskStartedCountView(undefined, {visible: true});
cases.missingObject = taskStartedCountView({started: 4, events: []}, {visible: true});
cases.empty = taskStartedCountView([], {visible: true});
cases.counted = taskStartedCountView(log, {visible: true});
cases.ignoresMissionStarted = taskStartedCountView([
  event("mission", "mission.started", {started: 3}),
], {visible: true});
cases.ignoresTaskPending = taskStartedCountView([
  event("pending", "task.pending", {status: "running", started: 2}),
], {visible: true});
cases.ignoresTaskCompleted = taskStartedCountView([
  event("done", "task.completed", {status: "running", started: 1}),
], {visible: true});
cases.ignoresTaskFailed = taskStartedCountView([
  event("failed", "task.failed", {status: "running", started: 1}),
], {visible: true});
cases.ignoresLlmStarted = taskStartedCountView([
  event("llm", "llm.started", {started: 4}),
], {visible: true});
cases.ignoresToolStarted = taskStartedCountView([
  event("tool", "tool.started", {started: 1}),
], {visible: true});
cases.ignoresVerificationStarted = taskStartedCountView([
  event("verify", "verification.started", {started: 2}),
], {visible: true});
cases.ignoresAgentSpawned = taskStartedCountView([
  event("spawn", "agent.spawned", {status: "running", started: 6}),
], {visible: true});
cases.ignoresBudget = taskStartedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, started: 1}),
], {visible: true});
cases.ignoresPayment = taskStartedCountView([
  event("pay", "payment.created", {started: 1, amount: 2}),
], {visible: true});
cases.oneStartNotPayload = taskStartedCountView([
  started("big", {started: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = taskStartedCountView([null, {payload: {started: 10}}, started("one")], {visible: true});
cases.unreadableType = taskStartedCountView([
  started("ok"),
  {id: "bad", event_type: 4, payload: {started: 1}},
], {visible: true});
cases.missingType = taskStartedCountView([
  {id: "blank", payload: {started: 7}},
  started("one"),
], {visible: true});
cases.prefix = taskStartedCountView(recordedTaskStartedCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = taskStartedCountView(recordedTaskStartedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = taskStartedCountView(recordedTaskStartedCountFeed(log, 6, true), {visible: true});
cases.prefixAll = taskStartedCountView(recordedTaskStartedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = taskStartedCountView(recordedTaskStartedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedTaskStartedCountFeed(log, log.length - 1, false);
cases.unloadedView = taskStartedCountView(recordedTaskStartedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedTaskStartedCountFeed([], -1, true);
cases.notArrayLog = recordedTaskStartedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
