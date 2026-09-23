import {
  recordedStopCountFeed, stopCountView, STOP_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const stopped = (id, extra = {}) => event(id, "mission.stopped", {reason: "Execution stopped", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  stopped("s1"),
  event("wait", "mission.waiting", {question_id: "q1"}),
  event("ask", "mission.question", {question_id: "q1", question: "Need a domain?"}),
  stopped("s2"),
  event("task", "task.stopped", {status: "stopped"}),
  event("paused", "mission.paused", {reason: "user"}),
  event("agent", "agent.updated", {status: "stopped"}),
  event("suspended", "mission.suspended"),
  event("failed", "mission.failed", {failure_class: "POLICY_REFUSAL"}),
  event("done", "mission.completed", {summary: "done"}),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  stopped("s3", {stops: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = STOP_COUNT_UNAVAILABLE;
cases.hidden = stopCountView(log, {visible: false});
cases.hiddenDefault = stopCountView(log);
cases.preview = stopCountView(log, {visible: false});
cases.missingNull = stopCountView(null, {visible: true});
cases.missingUndefined = stopCountView(undefined, {visible: true});
cases.missingObject = stopCountView({stops: 4, events: []}, {visible: true});
cases.empty = stopCountView([], {visible: true});
cases.counted = stopCountView(log, {visible: true});
cases.ignoresTaskStopped = stopCountView([
  event("task", "task.stopped", {stops: 3}),
], {visible: true});
cases.ignoresPaused = stopCountView([
  event("paused", "mission.paused", {stops: 2}),
], {visible: true});
cases.ignoresFailed = stopCountView([
  event("failed", "mission.failed", {stops: 2}),
], {visible: true});
cases.ignoresCompleted = stopCountView([
  event("done", "mission.completed", {stops: 2}),
], {visible: true});
cases.ignoresSuspended = stopCountView([
  event("suspended", "mission.suspended", {stops: 1}),
], {visible: true});
cases.ignoresWaiting = stopCountView([
  event("wait", "mission.waiting", {stops: 2}),
], {visible: true});
cases.ignoresQuestion = stopCountView([
  event("ask", "mission.question", {stops: 4}),
], {visible: true});
cases.ignoresResumed = stopCountView([
  event("resumed", "mission.resumed", {stops: 5}),
], {visible: true});
cases.ignoresResumeRequested = stopCountView([
  event("req", "mission.resume_requested", {stops: 3}),
], {visible: true});
cases.ignoresAgentUpdated = stopCountView([
  event("agent", "agent.updated", {status: "stopped", stops: 5}),
], {visible: true});
cases.ignoresAgentKilled = stopCountView([
  event("killed", "agent.killed", {status: "stopped", stops: 2}),
], {visible: true});
cases.ignoresStarted = stopCountView([
  event("start", "mission.started", {stops: 6}),
], {visible: true});
cases.ignoresRunning = stopCountView([
  event("run", "mission.running", {stops: 8}),
], {visible: true});
cases.ignoresBudget = stopCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, stops: 1}),
], {visible: true});
cases.oneStopNotPayload = stopCountView([
  stopped("big", {stops: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = stopCountView([null, {payload: {stops: 10}}, stopped("one")], {visible: true});
cases.unreadableType = stopCountView([
  stopped("ok"),
  {id: "bad", event_type: 4, payload: {stops: 1}},
], {visible: true});
cases.missingType = stopCountView([
  {id: "blank", payload: {stops: 7}},
  stopped("one"),
], {visible: true});
cases.prefix = stopCountView(recordedStopCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = stopCountView(recordedStopCountFeed(log, 0, true), {visible: true});
cases.prefixOne = stopCountView(recordedStopCountFeed(log, 4, true), {visible: true});
cases.prefixAll = stopCountView(recordedStopCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = stopCountView(recordedStopCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedStopCountFeed(log, log.length - 1, false);
cases.unloadedView = stopCountView(recordedStopCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedStopCountFeed([], -1, true);
cases.notArrayLog = recordedStopCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
