import {
  recordedResumeRequestedCountFeed, resumeRequestedCountView, RESUME_REQUESTED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const requested = (id, extra = {}) => event(id, "mission.resume_requested", {
  status: "paused", ...extra,
});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("resumed", "mission.resumed", {status: "running"}),
  event("running", "mission.running", {status: "running"}),
  event("waiting", "mission.waiting", {status: "waiting"}),
  event("paused", "mission.paused", {status: "paused"}),
  requested("r1"),
  event("answer", "user.answered", {question_id: "q1"}),
  event("task", "task.started", {id: "t1"}),
  event("done", "mission.completed", {status: "completed"}),
  event("fail", "mission.failed", {failure_class: "TOOL_MISSING"}),
  event("llm", "llm.started", {model: "fake"}),
  event("queued", "job.enqueued", {id: "j1", status: "pending"}),
  requested("r2", {token_spent: 4}),
  requested("r3"),
];

const cases = {};
cases.unavailable = RESUME_REQUESTED_COUNT_UNAVAILABLE;
cases.hidden = resumeRequestedCountView(log, {visible: false});
cases.hiddenDefault = resumeRequestedCountView(log);
cases.preview = resumeRequestedCountView(log, {visible: false});
cases.missingNull = resumeRequestedCountView(null, {visible: true});
cases.missingUndefined = resumeRequestedCountView(undefined, {visible: true});
cases.missingObject = resumeRequestedCountView({requested: 4, events: []}, {visible: true});
cases.empty = resumeRequestedCountView([], {visible: true});
cases.counted = resumeRequestedCountView(log, {visible: true});
cases.ignoresResumed = resumeRequestedCountView([
  event("resumed", "mission.resumed", {requested: 3}),
], {visible: true});
cases.ignoresStarted = resumeRequestedCountView([
  event("start", "mission.started", {requested: 2}),
], {visible: true});
cases.ignoresRunning = resumeRequestedCountView([
  event("running", "mission.running", {requested: 1}),
], {visible: true});
cases.ignoresWaiting = resumeRequestedCountView([
  event("waiting", "mission.waiting", {requested: 1}),
], {visible: true});
cases.ignoresPaused = resumeRequestedCountView([
  event("paused", "mission.paused", {requested: 1}),
], {visible: true});
cases.ignoresCompleted = resumeRequestedCountView([
  event("done", "mission.completed", {requested: 1}),
], {visible: true});
cases.ignoresFailed = resumeRequestedCountView([
  event("fail", "mission.failed", {requested: 1, failure_class: "TOOL_MISSING"}),
], {visible: true});
cases.ignoresAnswer = resumeRequestedCountView([
  event("answer", "user.answered", {requested: 1}),
], {visible: true});
cases.ignoresTask = resumeRequestedCountView([
  event("task", "task.started", {requested: 1}),
], {visible: true});
cases.ignoresLlm = resumeRequestedCountView([
  event("llm", "llm.started", {requested: 6}),
], {visible: true});
cases.ignoresJob = resumeRequestedCountView([
  event("queued", "job.enqueued", {requested: 1}),
], {visible: true});
cases.ignoresBudget = resumeRequestedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, requested: 1}),
], {visible: true});
cases.oneRequestedNotPayload = resumeRequestedCountView([
  requested("big", {requested: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = resumeRequestedCountView([null, {payload: {requested: 10}}, requested("one")], {visible: true});
cases.unreadableType = resumeRequestedCountView([
  requested("ok"),
  {id: "bad", event_type: 4, payload: {requested: 1}},
], {visible: true});
cases.missingType = resumeRequestedCountView([
  {id: "blank", payload: {requested: 7}},
  requested("one"),
], {visible: true});
cases.prefix = resumeRequestedCountView(recordedResumeRequestedCountFeed(log, 5, true), {visible: true});
cases.prefixFirst = resumeRequestedCountView(recordedResumeRequestedCountFeed(log, 0, true), {visible: true});
cases.prefixTwo = resumeRequestedCountView(recordedResumeRequestedCountFeed(log, 12, true), {visible: true});
cases.prefixAll = resumeRequestedCountView(recordedResumeRequestedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = resumeRequestedCountView(recordedResumeRequestedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedResumeRequestedCountFeed(log, log.length - 1, false);
cases.unloadedView = resumeRequestedCountView(recordedResumeRequestedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedResumeRequestedCountFeed([], -1, true);
cases.notArrayLog = recordedResumeRequestedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
