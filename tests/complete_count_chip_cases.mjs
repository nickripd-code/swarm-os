import {
  recordedCompleteCountFeed, completeCountView, COMPLETE_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const completed = (id, extra = {}) => event(id, "mission.completed", {summary: "Result ready", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  completed("c1"),
  event("wait", "mission.waiting", {question_id: "q1"}),
  event("ask", "mission.question", {question_id: "q1", question: "Need a domain?"}),
  completed("c2"),
  event("task", "task.completed", {status: "completed"}),
  event("llm", "llm.completed", {output_tokens: 12}),
  event("job", "job.completed", {job_id: "j1"}),
  event("tool", "tool.completed", {name: "read"}),
  event("passed", "verification.passed", {verdict: "pass"}),
  event("stopped", "mission.stopped", {reason: "user"}),
  event("failed", "mission.failed", {failure_class: "POLICY_REFUSAL"}),
  event("agent", "agent.updated", {status: "completed"}),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  completed("c3", {completes: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = COMPLETE_COUNT_UNAVAILABLE;
cases.hidden = completeCountView(log, {visible: false});
cases.hiddenDefault = completeCountView(log);
cases.preview = completeCountView(log, {visible: false});
cases.missingNull = completeCountView(null, {visible: true});
cases.missingUndefined = completeCountView(undefined, {visible: true});
cases.missingObject = completeCountView({completes: 4, events: []}, {visible: true});
cases.empty = completeCountView([], {visible: true});
cases.counted = completeCountView(log, {visible: true});
cases.ignoresTaskCompleted = completeCountView([
  event("task", "task.completed", {completes: 3}),
], {visible: true});
cases.ignoresLlmCompleted = completeCountView([
  event("llm", "llm.completed", {completes: 2, token_spent: 1}),
], {visible: true});
cases.ignoresJobCompleted = completeCountView([
  event("job", "job.completed", {completes: 2}),
], {visible: true});
cases.ignoresToolCompleted = completeCountView([
  event("tool", "tool.completed", {completes: 1}),
], {visible: true});
cases.ignoresVerificationPassed = completeCountView([
  event("passed", "verification.passed", {completes: 2}),
], {visible: true});
cases.ignoresStopped = completeCountView([
  event("stopped", "mission.stopped", {completes: 1}),
], {visible: true});
cases.ignoresFailed = completeCountView([
  event("failed", "mission.failed", {completes: 2}),
], {visible: true});
cases.ignoresPaused = completeCountView([
  event("paused", "mission.paused", {completes: 2}),
], {visible: true});
cases.ignoresSuspended = completeCountView([
  event("suspended", "mission.suspended", {completes: 1}),
], {visible: true});
cases.ignoresWaiting = completeCountView([
  event("wait", "mission.waiting", {completes: 2}),
], {visible: true});
cases.ignoresQuestion = completeCountView([
  event("ask", "mission.question", {completes: 4}),
], {visible: true});
cases.ignoresSucceeded = completeCountView([
  event("ok", "mission.succeeded", {completes: 6}),
], {visible: true});
cases.ignoresFinished = completeCountView([
  event("fin", "mission.finished", {completes: 3}),
], {visible: true});
cases.ignoresAgentUpdated = completeCountView([
  event("agent", "agent.updated", {status: "completed", completes: 5}),
], {visible: true});
cases.ignoresStarted = completeCountView([
  event("start", "mission.started", {completes: 6}),
], {visible: true});
cases.ignoresRunning = completeCountView([
  event("run", "mission.running", {completes: 8}),
], {visible: true});
cases.ignoresBudget = completeCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, completes: 1}),
], {visible: true});
cases.oneCompleteNotPayload = completeCountView([
  completed("big", {completes: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = completeCountView([null, {payload: {completes: 10}}, completed("one")], {visible: true});
cases.unreadableType = completeCountView([
  completed("ok"),
  {id: "bad", event_type: 4, payload: {completes: 1}},
], {visible: true});
cases.missingType = completeCountView([
  {id: "blank", payload: {completes: 7}},
  completed("one"),
], {visible: true});
cases.prefix = completeCountView(recordedCompleteCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = completeCountView(recordedCompleteCountFeed(log, 0, true), {visible: true});
cases.prefixOne = completeCountView(recordedCompleteCountFeed(log, 4, true), {visible: true});
cases.prefixAll = completeCountView(recordedCompleteCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = completeCountView(recordedCompleteCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedCompleteCountFeed(log, log.length - 1, false);
cases.unloadedView = completeCountView(recordedCompleteCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedCompleteCountFeed([], -1, true);
cases.notArrayLog = recordedCompleteCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
