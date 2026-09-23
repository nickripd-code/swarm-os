import {
  recordedPauseCountFeed, pauseCountView, PAUSE_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const paused = (id, extra = {}) => event(id, "mission.paused", {reason: "user", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  paused("p1"),
  event("wait", "mission.waiting", {question_id: "q1"}),
  event("ask", "mission.question", {question_id: "q1", question: "Need a domain?"}),
  paused("p2"),
  event("resume-req", "mission.resume_requested", {reason: "Human resume"}),
  event("resumed", "mission.resumed", {reason: "Human resume"}),
  event("agent", "agent.updated", {status: "paused"}),
  event("suspended", "mission.suspended"),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  paused("p3", {pauses: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = PAUSE_COUNT_UNAVAILABLE;
cases.hidden = pauseCountView(log, {visible: false});
cases.hiddenDefault = pauseCountView(log);
cases.preview = pauseCountView(log, {visible: false});
cases.missingNull = pauseCountView(null, {visible: true});
cases.missingUndefined = pauseCountView(undefined, {visible: true});
cases.missingObject = pauseCountView({pauses: 4, events: []}, {visible: true});
cases.empty = pauseCountView([], {visible: true});
cases.counted = pauseCountView(log, {visible: true});
cases.ignoresResumed = pauseCountView([
  event("resumed", "mission.resumed", {pauses: 2}),
], {visible: true});
cases.ignoresResumeRequested = pauseCountView([
  event("req", "mission.resume_requested", {pauses: 3}),
], {visible: true});
cases.ignoresSuspended = pauseCountView([
  event("suspended", "mission.suspended", {pauses: 1}),
], {visible: true});
cases.ignoresWaiting = pauseCountView([
  event("wait", "mission.waiting", {pauses: 2}),
], {visible: true});
cases.ignoresQuestion = pauseCountView([
  event("ask", "mission.question", {pauses: 4}),
], {visible: true});
cases.ignoresAgentPaused = pauseCountView([
  event("agent", "agent.updated", {status: "paused", pauses: 5}),
], {visible: true});
cases.ignoresStarted = pauseCountView([
  event("start", "mission.started", {pauses: 6}),
], {visible: true});
cases.ignoresBudget = pauseCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, pauses: 1}),
], {visible: true});
cases.onePauseNotPayload = pauseCountView([
  paused("big", {pauses: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = pauseCountView([null, {payload: {pauses: 10}}, paused("one")], {visible: true});
cases.unreadableType = pauseCountView([
  paused("ok"),
  {id: "bad", event_type: 4, payload: {pauses: 1}},
], {visible: true});
cases.missingType = pauseCountView([
  {id: "blank", payload: {pauses: 7}},
  paused("one"),
], {visible: true});
cases.prefix = pauseCountView(recordedPauseCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = pauseCountView(recordedPauseCountFeed(log, 0, true), {visible: true});
cases.prefixOne = pauseCountView(recordedPauseCountFeed(log, 4, true), {visible: true});
cases.prefixAll = pauseCountView(recordedPauseCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = pauseCountView(recordedPauseCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedPauseCountFeed(log, log.length - 1, false);
cases.unloadedView = pauseCountView(recordedPauseCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedPauseCountFeed([], -1, true);
cases.notArrayLog = recordedPauseCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
