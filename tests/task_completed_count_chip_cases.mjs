import {
  recordedTaskCompletedCountFeed, taskCompletedCountView, TASK_COMPLETED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const completed = (id, extra = {}) => event(id, "task.completed", {id, status: "completed", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  completed("t1"),
  event("failed", "task.failed", {id: "t2", status: "failed"}),
  event("mission", "mission.completed", {result: "done"}),
  completed("t3"),
  event("tool", "tool.completed", {name: "read"}),
  event("verify", "verification.passed", {}),
  event("budget", "budget.updated", {known: true, token_spent: 1}),
  event("updated", "agent.updated", {id: "a1", status: "running"}),
  event("reparent", "agent.reparented", {id: "a3"}),
  completed("t4", {completed: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = TASK_COMPLETED_COUNT_UNAVAILABLE;
cases.hidden = taskCompletedCountView(log, {visible: false});
cases.hiddenDefault = taskCompletedCountView(log);
cases.preview = taskCompletedCountView(log, {visible: false});
cases.missingNull = taskCompletedCountView(null, {visible: true});
cases.missingUndefined = taskCompletedCountView(undefined, {visible: true});
cases.missingObject = taskCompletedCountView({completed: 4, events: []}, {visible: true});
cases.empty = taskCompletedCountView([], {visible: true});
cases.counted = taskCompletedCountView(log, {visible: true});
cases.ignoresMissionCompleted = taskCompletedCountView([
  event("mission", "mission.completed", {completed: 3}),
], {visible: true});
cases.ignoresTaskFailed = taskCompletedCountView([
  event("failed", "task.failed", {status: "completed", completed: 2}),
], {visible: true});
cases.ignoresTaskStarted = taskCompletedCountView([
  event("started", "task.started", {status: "running", completed: 1}),
], {visible: true});
cases.ignoresToolCompleted = taskCompletedCountView([
  event("tool", "tool.completed", {completed: 1}),
], {visible: true});
cases.ignoresVerificationPassed = taskCompletedCountView([
  event("verify", "verification.passed", {completed: 2}),
], {visible: true});
cases.ignoresLlmCompleted = taskCompletedCountView([
  event("llm", "llm.completed", {completed: 4}),
], {visible: true});
cases.ignoresAgentUpdated = taskCompletedCountView([
  event("updated", "agent.updated", {status: "completed", completed: 6}),
], {visible: true});
cases.ignoresReparented = taskCompletedCountView([
  event("reparent", "agent.reparented", {completed: 1}),
], {visible: true});
cases.ignoresBudget = taskCompletedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, completed: 1}),
], {visible: true});
cases.oneCompletionNotPayload = taskCompletedCountView([
  completed("big", {completed: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = taskCompletedCountView([null, {payload: {completed: 10}}, completed("one")], {visible: true});
cases.unreadableType = taskCompletedCountView([
  completed("ok"),
  {id: "bad", event_type: 4, payload: {completed: 1}},
], {visible: true});
cases.missingType = taskCompletedCountView([
  {id: "blank", payload: {completed: 7}},
  completed("one"),
], {visible: true});
cases.prefix = taskCompletedCountView(recordedTaskCompletedCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = taskCompletedCountView(recordedTaskCompletedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = taskCompletedCountView(recordedTaskCompletedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = taskCompletedCountView(recordedTaskCompletedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = taskCompletedCountView(recordedTaskCompletedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedTaskCompletedCountFeed(log, log.length - 1, false);
cases.unloadedView = taskCompletedCountView(recordedTaskCompletedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedTaskCompletedCountFeed([], -1, true);
cases.notArrayLog = recordedTaskCompletedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
