import {
  recordedToolCompletedCountFeed, toolCompletedCountView, TOOL_COMPLETED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const completed = (id, extra = {}) => event(id, "tool.completed", {name: "read", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  completed("t1"),
  event("started", "tool.started", {name: "read"}),
  event("failed", "tool.failed", {name: "read", failure_class: "TOOL_MISSING"}),
  completed("t2"),
  event("task", "task.completed", {status: "completed"}),
  event("llm", "llm.completed", {output_tokens: 12}),
  event("job", "job.completed", {job_id: "j1"}),
  event("mission", "mission.completed", {summary: "Result ready"}),
  event("passed", "verification.passed", {verdict: "pass"}),
  event("stopped", "mission.stopped", {reason: "user"}),
  event("fail", "mission.failed", {failure_class: "POLICY_REFUSAL"}),
  event("agent", "agent.updated", {status: "completed"}),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  completed("t3", {completes: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = TOOL_COMPLETED_COUNT_UNAVAILABLE;
cases.hidden = toolCompletedCountView(log, {visible: false});
cases.hiddenDefault = toolCompletedCountView(log);
cases.preview = toolCompletedCountView(log, {visible: false});
cases.missingNull = toolCompletedCountView(null, {visible: true});
cases.missingUndefined = toolCompletedCountView(undefined, {visible: true});
cases.missingObject = toolCompletedCountView({completes: 4, events: []}, {visible: true});
cases.empty = toolCompletedCountView([], {visible: true});
cases.counted = toolCompletedCountView(log, {visible: true});
cases.ignoresToolStarted = toolCompletedCountView([
  event("started", "tool.started", {completes: 3}),
], {visible: true});
cases.ignoresToolFailed = toolCompletedCountView([
  event("failed", "tool.failed", {completes: 2}),
], {visible: true});
cases.ignoresTaskCompleted = toolCompletedCountView([
  event("task", "task.completed", {completes: 3}),
], {visible: true});
cases.ignoresLlmCompleted = toolCompletedCountView([
  event("llm", "llm.completed", {completes: 2, token_spent: 1}),
], {visible: true});
cases.ignoresJobCompleted = toolCompletedCountView([
  event("job", "job.completed", {completes: 2}),
], {visible: true});
cases.ignoresMissionCompleted = toolCompletedCountView([
  event("mission", "mission.completed", {completes: 1}),
], {visible: true});
cases.ignoresVerificationPassed = toolCompletedCountView([
  event("passed", "verification.passed", {completes: 2}),
], {visible: true});
cases.ignoresStopped = toolCompletedCountView([
  event("stopped", "mission.stopped", {completes: 1}),
], {visible: true});
cases.ignoresFailed = toolCompletedCountView([
  event("failed", "mission.failed", {completes: 2}),
], {visible: true});
cases.ignoresPaused = toolCompletedCountView([
  event("paused", "mission.paused", {completes: 2}),
], {visible: true});
cases.ignoresFailover = toolCompletedCountView([
  event("failover", "llm.failover", {completes: 1}),
], {visible: true});
cases.ignoresBudget = toolCompletedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, completes: 1}),
], {visible: true});
cases.oneCompleteNotPayload = toolCompletedCountView([
  completed("big", {completes: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = toolCompletedCountView([null, {payload: {completes: 10}}, completed("one")], {visible: true});
cases.unreadableType = toolCompletedCountView([
  completed("ok"),
  {id: "bad", event_type: 4, payload: {completes: 1}},
], {visible: true});
cases.missingType = toolCompletedCountView([
  {id: "blank", payload: {completes: 7}},
  completed("one"),
], {visible: true});
cases.prefix = toolCompletedCountView(recordedToolCompletedCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = toolCompletedCountView(recordedToolCompletedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = toolCompletedCountView(recordedToolCompletedCountFeed(log, 4, true), {visible: true});
cases.prefixAll = toolCompletedCountView(recordedToolCompletedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = toolCompletedCountView(recordedToolCompletedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedToolCompletedCountFeed(log, log.length - 1, false);
cases.unloadedView = toolCompletedCountView(recordedToolCompletedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedToolCompletedCountFeed([], -1, true);
cases.notArrayLog = recordedToolCompletedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
