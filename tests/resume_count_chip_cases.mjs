import {
  recordedResumeCountFeed, resumeCountView, RESUME_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const resumed = (id, extra = {}) => event(id, "mission.resumed", {reason: "Human resume", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  resumed("r1"),
  event("wait", "mission.waiting", {question_id: "q1"}),
  event("ask", "mission.question", {question_id: "q1", question: "Need a domain?"}),
  resumed("r2"),
  event("resume-req", "mission.resume_requested", {reason: "Human resume"}),
  event("paused", "mission.paused", {reason: "user"}),
  event("agent", "agent.updated", {status: "paused"}),
  event("suspended", "mission.suspended"),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  resumed("r3", {resumes: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = RESUME_COUNT_UNAVAILABLE;
cases.hidden = resumeCountView(log, {visible: false});
cases.hiddenDefault = resumeCountView(log);
cases.preview = resumeCountView(log, {visible: false});
cases.missingNull = resumeCountView(null, {visible: true});
cases.missingUndefined = resumeCountView(undefined, {visible: true});
cases.missingObject = resumeCountView({resumes: 4, events: []}, {visible: true});
cases.empty = resumeCountView([], {visible: true});
cases.counted = resumeCountView(log, {visible: true});
cases.ignoresResumeRequested = resumeCountView([
  event("req", "mission.resume_requested", {resumes: 3}),
], {visible: true});
cases.ignoresPaused = resumeCountView([
  event("paused", "mission.paused", {resumes: 2}),
], {visible: true});
cases.ignoresSuspended = resumeCountView([
  event("suspended", "mission.suspended", {resumes: 1}),
], {visible: true});
cases.ignoresWaiting = resumeCountView([
  event("wait", "mission.waiting", {resumes: 2}),
], {visible: true});
cases.ignoresQuestion = resumeCountView([
  event("ask", "mission.question", {resumes: 4}),
], {visible: true});
cases.ignoresAgentUpdated = resumeCountView([
  event("agent", "agent.updated", {status: "running", resumes: 5}),
], {visible: true});
cases.ignoresStarted = resumeCountView([
  event("start", "mission.started", {resumes: 6}),
], {visible: true});
cases.ignoresRunning = resumeCountView([
  event("run", "mission.running", {resumes: 8}),
], {visible: true});
cases.ignoresBudget = resumeCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, resumes: 1}),
], {visible: true});
cases.oneResumeNotPayload = resumeCountView([
  resumed("big", {resumes: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = resumeCountView([null, {payload: {resumes: 10}}, resumed("one")], {visible: true});
cases.unreadableType = resumeCountView([
  resumed("ok"),
  {id: "bad", event_type: 4, payload: {resumes: 1}},
], {visible: true});
cases.missingType = resumeCountView([
  {id: "blank", payload: {resumes: 7}},
  resumed("one"),
], {visible: true});
cases.prefix = resumeCountView(recordedResumeCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = resumeCountView(recordedResumeCountFeed(log, 0, true), {visible: true});
cases.prefixOne = resumeCountView(recordedResumeCountFeed(log, 4, true), {visible: true});
cases.prefixAll = resumeCountView(recordedResumeCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = resumeCountView(recordedResumeCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedResumeCountFeed(log, log.length - 1, false);
cases.unloadedView = resumeCountView(recordedResumeCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedResumeCountFeed([], -1, true);
cases.notArrayLog = recordedResumeCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
