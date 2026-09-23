import {
  recordedSuspendCountFeed, suspendCountView, SUSPEND_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const suspended = (id, extra = {}) => event(id, "mission.suspended", {
  reason: "Runtime is shutting down; unfinished work remains recoverable",
  ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  suspended("s1"),
  event("paused", "mission.paused", {reason: "Execution paused by user"}),
  event("wait", "mission.waiting", {question_id: "q1"}),
  suspended("s2"),
  event("resume-req", "mission.resume_requested", {reason: "Human resume"}),
  event("resumed", "mission.resumed", {reason: "Human resume"}),
  event("stopped", "mission.stopped", {reason: "Execution stopped"}),
  event("failed", "mission.failed", {error: "failed", failure_class: "UNKNOWN_FAILURE"}),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  suspended("s3", {suspends: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = SUSPEND_COUNT_UNAVAILABLE;
cases.hidden = suspendCountView(log, {visible: false});
cases.hiddenDefault = suspendCountView(log);
cases.preview = suspendCountView(log, {visible: false});
cases.missingNull = suspendCountView(null, {visible: true});
cases.missingUndefined = suspendCountView(undefined, {visible: true});
cases.missingObject = suspendCountView({suspends: 4, events: []}, {visible: true});
cases.empty = suspendCountView([], {visible: true});
cases.counted = suspendCountView(log, {visible: true});
cases.ignoresPaused = suspendCountView([
  event("paused", "mission.paused", {suspends: 2}),
], {visible: true});
cases.ignoresResumed = suspendCountView([
  event("resumed", "mission.resumed", {suspends: 2}),
], {visible: true});
cases.ignoresResumeRequested = suspendCountView([
  event("req", "mission.resume_requested", {suspends: 3}),
], {visible: true});
cases.ignoresStopped = suspendCountView([
  event("stopped", "mission.stopped", {suspends: 1}),
], {visible: true});
cases.ignoresFailed = suspendCountView([
  event("failed", "mission.failed", {suspends: 1}),
], {visible: true});
cases.ignoresWaiting = suspendCountView([
  event("wait", "mission.waiting", {suspends: 2}),
], {visible: true});
cases.ignoresAgent = suspendCountView([
  event("agent", "agent.updated", {status: "suspended", suspends: 5}),
], {visible: true});
cases.ignoresStarted = suspendCountView([
  event("start", "mission.started", {suspends: 6}),
], {visible: true});
cases.ignoresBudget = suspendCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, suspends: 1}),
], {visible: true});
cases.oneSuspendNotPayload = suspendCountView([
  suspended("big", {suspends: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = suspendCountView([null, {payload: {suspends: 10}}, suspended("one")], {visible: true});
cases.unreadableType = suspendCountView([
  suspended("ok"),
  {id: "bad", event_type: 4, payload: {suspends: 1}},
], {visible: true});
cases.missingType = suspendCountView([
  {id: "blank", payload: {suspends: 7}},
  suspended("one"),
], {visible: true});
cases.prefix = suspendCountView(recordedSuspendCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = suspendCountView(recordedSuspendCountFeed(log, 0, true), {visible: true});
cases.prefixOne = suspendCountView(recordedSuspendCountFeed(log, 4, true), {visible: true});
cases.prefixAll = suspendCountView(recordedSuspendCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = suspendCountView(recordedSuspendCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedSuspendCountFeed(log, log.length - 1, false);
cases.unloadedView = suspendCountView(recordedSuspendCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedSuspendCountFeed([], -1, true);
cases.notArrayLog = recordedSuspendCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
