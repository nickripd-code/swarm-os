import {
  recordedTaskFailedCountFeed, taskFailedCountView, TASK_FAILED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "task.failed", {id, status: "failed", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  failed("t1"),
  event("done", "task.completed", {id: "t2", status: "completed"}),
  event("mission", "mission.failed", {error: "no"}),
  failed("t3"),
  event("tool", "tool.failed", {name: "read"}),
  event("verify", "verification.failed", {}),
  event("budget", "budget.updated", {known: true, token_spent: 1}),
  event("updated", "agent.updated", {id: "a1", status: "failed"}),
  event("llm", "llm.failed", {failure_class: "PROVIDER_OUTAGE"}),
  failed("t4", {failed: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = TASK_FAILED_COUNT_UNAVAILABLE;
cases.hidden = taskFailedCountView(log, {visible: false});
cases.hiddenDefault = taskFailedCountView(log);
cases.preview = taskFailedCountView(log, {visible: false});
cases.missingNull = taskFailedCountView(null, {visible: true});
cases.missingUndefined = taskFailedCountView(undefined, {visible: true});
cases.missingObject = taskFailedCountView({failed: 4, events: []}, {visible: true});
cases.empty = taskFailedCountView([], {visible: true});
cases.counted = taskFailedCountView(log, {visible: true});
cases.ignoresMissionFailed = taskFailedCountView([
  event("mission", "mission.failed", {failed: 3}),
], {visible: true});
cases.ignoresTaskCompleted = taskFailedCountView([
  event("done", "task.completed", {status: "failed", failed: 2}),
], {visible: true});
cases.ignoresTaskStarted = taskFailedCountView([
  event("started", "task.started", {status: "running", failed: 1}),
], {visible: true});
cases.ignoresToolFailed = taskFailedCountView([
  event("tool", "tool.failed", {failed: 1}),
], {visible: true});
cases.ignoresVerificationFailed = taskFailedCountView([
  event("verify", "verification.failed", {failed: 2}),
], {visible: true});
cases.ignoresLlmFailed = taskFailedCountView([
  event("llm", "llm.failed", {failed: 4}),
], {visible: true});
cases.ignoresAgentUpdated = taskFailedCountView([
  event("updated", "agent.updated", {status: "failed", failed: 6}),
], {visible: true});
cases.ignoresAgentKilled = taskFailedCountView([
  event("killed", "agent.killed", {failed: 1}),
], {visible: true});
cases.ignoresBudget = taskFailedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, failed: 1}),
], {visible: true});
cases.oneFailureNotPayload = taskFailedCountView([
  failed("big", {failed: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = taskFailedCountView([null, {payload: {failed: 10}}, failed("one")], {visible: true});
cases.unreadableType = taskFailedCountView([
  failed("ok"),
  {id: "bad", event_type: 4, payload: {failed: 1}},
], {visible: true});
cases.missingType = taskFailedCountView([
  {id: "blank", payload: {failed: 7}},
  failed("one"),
], {visible: true});
cases.prefix = taskFailedCountView(recordedTaskFailedCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = taskFailedCountView(recordedTaskFailedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = taskFailedCountView(recordedTaskFailedCountFeed(log, 5, true), {visible: true});
cases.prefixAll = taskFailedCountView(recordedTaskFailedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = taskFailedCountView(recordedTaskFailedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedTaskFailedCountFeed(log, log.length - 1, false);
cases.unloadedView = taskFailedCountView(recordedTaskFailedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedTaskFailedCountFeed([], -1, true);
cases.notArrayLog = recordedTaskFailedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
