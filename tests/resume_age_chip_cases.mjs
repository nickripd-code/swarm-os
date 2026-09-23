import {newState, applyEvent, projectEvents, resumeAgeChip, RESUME_AGE_UNAVAILABLE} from "../app/static/state.mjs";

const STAMP = "2026-09-23T08:00:00Z";
const AT = Date.parse(STAMP);
const OLDER = "2026-09-23T07:00:00Z";
const NEWER = "2026-09-23T08:30:00Z";

function mission(extra = {}) {
  return {id: "m1", goal: "Ship the note", status: "running", created_at: OLDER, ...extra};
}

function withEvents(events, extra = {}) {
  const state = newState(mission());
  for (const event of events) applyEvent(state, event);
  Object.assign(state, extra);
  return state;
}

function ev(id, type, created_at, payload = {reason: "User requested resume", from_status: "paused"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: RESUME_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = resumeAgeChip(newState());
cases.noMission = resumeAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.resumed", STAMP)],
});
cases.preview = resumeAgeChip(withEvents(
  [ev("e1", "mission.resumed", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: knownNow, preview: true});
cases.notRunning = resumeAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP, {reason: "user pause"}),
]), {now: knownNow});
cases.startedOnly = resumeAgeChip(withEvents([
  ev("e1", "mission.started", STAMP, {mode: "live"}),
]), {now: knownNow});

const controls = [
  "mission.blocked",
  "mission.paused",
  "mission.stopped",
  "mission.waiting",
  "mission.resume_requested",
  "mission.failed",
  "mission.completed",
  "mission.suspended",
  "mission.running",
  "mission.question",
  "user.answered",
  "user.answer_consumed",
  "task.blocked",
];
cases.controlsIgnored = {};
for (const type of controls) {
  const state = newState(mission({status: "running"}));
  applyEvent(state, ev("e1", type, STAMP, {reason: "not a resume", question_id: "q1", question: "Which name?"}));
  cases.controlsIgnored[type] = resumeAgeChip(state, {now: knownNow});
}
cases.agentMessageIgnored = resumeAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.message", STAMP, {kind: "resumed", text: "back"})],
}, {now: knownNow});

cases.known = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: knownNow});
cases.offset = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.startedThenResumed = resumeAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
  ev("e2", "mission.resumed", STAMP),
]), {now: knownNow});
cases.newestOpen = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", OLDER),
  ev("e2", "mission.resumed", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", OLDER),
  ev("e2", "mission.paused", "2026-09-23T07:30:00Z", {reason: "user pause"}),
  ev("e3", "mission.resumed", STAMP),
]), {now: knownNow});
cases.seconds = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: AT + 59000});
cases.justNow = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: AT + 400});
cases.hours = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: AT - 30000});
cases.noClock = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]));
cases.badNow = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: Number.NaN});
cases.zeroNow = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: 0});
cases.suspendKeepsResume = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.suspended", NEWER, {reason: "shutdown"}),
]), {now: knownNow});
cases.requestKeepsResume = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.resume_requested", NEWER, {reason: "again"}),
]), {now: knownNow});
cases.answerKeepsResume = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "user.answered", NEWER, {question_id: "q1", answer: "yes"}),
]), {now: knownNow});

const bad = {};
bad.blank = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", ""),
]), {now: knownNow});
bad.whitespace = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "   "),
]), {now: knownNow});
bad.untrimmed = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", " " + STAMP),
]), {now: knownNow});
bad.missing = resumeAgeChip(withEvents([
  {id: "e1", event_type: "mission.resumed", actor_id: "root", payload: {reason: "User requested resume"}},
]), {now: knownNow});
bad.garbage = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "yesterday"),
]), {now: knownNow});
bad.epoch = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", 0),
]), {now: knownNow});
bad.future = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.resumed", ""),
]), {now: knownNow});
bad.impossibleDay = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = resumeAgeChip({
  mission: mission({status: "running"}),
  preview: false,
}, {now: knownNow});
bad.naive = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.emptyFeed = resumeAgeChip(newState(mission({status: "running"})), {now: knownNow});
cases.runningAfterResume = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.running", NEWER, {reason: "Human answer received; controller will continue"}),
]), {now: knownNow});
cases.pausedAfterResume = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "user pause"}),
]), {now: knownNow});
cases.questionAfterResume = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.question", NEWER, {question_id: "q1", question: "Which name?"}),
]), {now: knownNow});
cases.waitingAfterResume = resumeAgeChip(withEvents([
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.waiting", NEWER, {reason: "Waiting for in-flight work"}),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.resumed", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "user pause"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = resumeAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = resumeAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = resumeAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = resumeAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
