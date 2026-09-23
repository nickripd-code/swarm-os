import {
  recordedFailCountFeed, failCountView, FAIL_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "mission.failed", {failure_class: "VERIFICATION_FAILURE", error: "verifier failed", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  failed("f1"),
  event("llm", "llm.failed", {failure_class: "PROVIDER_OUTAGE"}),
  event("ver", "verification.failed", {failure_class: "VERIFICATION_FAILURE"}),
  failed("f2"),
  event("task", "task.failed", {error: "tool"}),
  event("tool", "tool.failed", {error: "timeout"}),
  event("job", "job.failed", {error: "handler"}),
  event("stop", "mission.stopped", {reason: "user"}),
  event("done", "mission.completed", {summary: "ok"}),
  event("block", "mission.blocked", {reason: "capability"}),
  event("ask", "mission.question", {question_id: "q1", question: "Need a domain?"}),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  failed("f3", {fails: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = FAIL_COUNT_UNAVAILABLE;
cases.hidden = failCountView(log, {visible: false});
cases.hiddenDefault = failCountView(log);
cases.preview = failCountView(log, {visible: false});
cases.missingNull = failCountView(null, {visible: true});
cases.missingUndefined = failCountView(undefined, {visible: true});
cases.missingObject = failCountView({fails: 4, events: []}, {visible: true});
cases.empty = failCountView([], {visible: true});
cases.counted = failCountView(log, {visible: true});
cases.ignoresLlmFailed = failCountView([
  event("llm", "llm.failed", {fails: 3}),
], {visible: true});
cases.ignoresVerificationFailed = failCountView([
  event("ver", "verification.failed", {fails: 2}),
], {visible: true});
cases.ignoresEvidenceFailed = failCountView([
  event("ev", "verification.evidence.failed", {fails: 1}),
], {visible: true});
cases.ignoresTaskFailed = failCountView([
  event("task", "task.failed", {fails: 2}),
], {visible: true});
cases.ignoresToolFailed = failCountView([
  event("tool", "tool.failed", {fails: 4}),
], {visible: true});
cases.ignoresJobFailed = failCountView([
  event("job", "job.failed", {fails: 5}),
], {visible: true});
cases.ignoresStopped = failCountView([
  event("stop", "mission.stopped", {fails: 6}),
], {visible: true});
cases.ignoresCompleted = failCountView([
  event("done", "mission.completed", {fails: 8}),
], {visible: true});
cases.ignoresBlocked = failCountView([
  event("block", "mission.blocked", {fails: 1}),
], {visible: true});
cases.ignoresQuestion = failCountView([
  event("ask", "mission.question", {fails: 4}),
], {visible: true});
cases.ignoresBudget = failCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, fails: 1}),
], {visible: true});
cases.oneFailNotPayload = failCountView([
  failed("big", {fails: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = failCountView([null, {payload: {fails: 10}}, failed("one")], {visible: true});
cases.unreadableType = failCountView([
  failed("ok"),
  {id: "bad", event_type: 4, payload: {fails: 1}},
], {visible: true});
cases.missingType = failCountView([
  {id: "blank", payload: {fails: 7}},
  failed("one"),
], {visible: true});
cases.prefix = failCountView(recordedFailCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = failCountView(recordedFailCountFeed(log, 0, true), {visible: true});
cases.prefixOne = failCountView(recordedFailCountFeed(log, 4, true), {visible: true});
cases.prefixAll = failCountView(recordedFailCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = failCountView(recordedFailCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedFailCountFeed(log, log.length - 1, false);
cases.unloadedView = failCountView(recordedFailCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedFailCountFeed([], -1, true);
cases.notArrayLog = recordedFailCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
