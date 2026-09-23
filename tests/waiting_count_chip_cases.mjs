import {
  recordedWaitingCountFeed, waitingCountView, WAITING_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const waiting = (id, extra = {}) => event(id, "mission.waiting", {reason: "Waiting for in-flight work", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  waiting("w1"),
  event("ask", "mission.question", {question_id: "q1", question: "Need a domain?"}),
  event("running", "mission.running", {reason: "In-flight work finished"}),
  waiting("w2"),
  event("paused", "mission.paused", {reason: "user"}),
  event("blocked", "mission.blocked", {reason: "missing capability"}),
  event("task", "task.blocked", {reason: "missing tool"}),
  event("agent", "agent.updated", {status: "waiting"}),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  waiting("w3", {waits: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = WAITING_COUNT_UNAVAILABLE;
cases.hidden = waitingCountView(log, {visible: false});
cases.hiddenDefault = waitingCountView(log);
cases.preview = waitingCountView(log, {visible: false});
cases.missingNull = waitingCountView(null, {visible: true});
cases.missingUndefined = waitingCountView(undefined, {visible: true});
cases.missingObject = waitingCountView({waits: 4, events: []}, {visible: true});
cases.empty = waitingCountView([], {visible: true});
cases.counted = waitingCountView(log, {visible: true});
cases.ignoresRunning = waitingCountView([
  event("running", "mission.running", {waits: 2}),
], {visible: true});
cases.ignoresQuestion = waitingCountView([
  event("ask", "mission.question", {waits: 3}),
], {visible: true});
cases.ignoresPaused = waitingCountView([
  event("paused", "mission.paused", {waits: 1}),
], {visible: true});
cases.ignoresBlocked = waitingCountView([
  event("blocked", "mission.blocked", {waits: 2}),
], {visible: true});
cases.ignoresTaskBlocked = waitingCountView([
  event("task", "task.blocked", {waits: 4}),
], {visible: true});
cases.ignoresAgentWaiting = waitingCountView([
  event("agent", "agent.updated", {status: "waiting", waits: 5}),
], {visible: true});
cases.ignoresStarted = waitingCountView([
  event("start", "mission.started", {waits: 6}),
], {visible: true});
cases.ignoresBudget = waitingCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, waits: 1}),
], {visible: true});
cases.oneWaitNotPayload = waitingCountView([
  waiting("big", {waits: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = waitingCountView([null, {payload: {waits: 10}}, waiting("one")], {visible: true});
cases.unreadableType = waitingCountView([
  waiting("ok"),
  {id: "bad", event_type: 4, payload: {waits: 1}},
], {visible: true});
cases.missingType = waitingCountView([
  {id: "blank", payload: {waits: 7}},
  waiting("one"),
], {visible: true});
cases.prefix = waitingCountView(recordedWaitingCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = waitingCountView(recordedWaitingCountFeed(log, 0, true), {visible: true});
cases.prefixOne = waitingCountView(recordedWaitingCountFeed(log, 4, true), {visible: true});
cases.prefixAll = waitingCountView(recordedWaitingCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = waitingCountView(recordedWaitingCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedWaitingCountFeed(log, log.length - 1, false);
cases.unloadedView = waitingCountView(recordedWaitingCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedWaitingCountFeed([], -1, true);
cases.notArrayLog = recordedWaitingCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
