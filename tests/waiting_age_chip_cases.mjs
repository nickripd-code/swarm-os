import {newState, applyEvent, projectEvents, waitingAgeChip, WAITING_AGE_UNAVAILABLE} from "../app/static/state.mjs";

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

function ev(id, type, created_at, payload = {reason: "Waiting for in-flight work"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: WAITING_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = waitingAgeChip(newState());
cases.noMission = waitingAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.waiting", STAMP)],
});
cases.preview = waitingAgeChip(withEvents(
  [ev("e1", "mission.waiting", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: knownNow, preview: true});
cases.notWaiting = waitingAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
]), {now: knownNow});

const controls = [
  "mission.blocked",
  "mission.paused",
  "mission.stopped",
  "mission.resumed",
  "mission.resume_requested",
  "mission.failed",
  "mission.completed",
  "mission.suspended",
  "mission.running",
  "user.answered",
  "user.answer_consumed",
  "task.blocked",
];
cases.controlsIgnored = {};
for (const type of controls) {
  const state = newState(mission({status: "running"}));
  applyEvent(state, ev("e1", type, STAMP, {reason: "parked", question_id: "q1", question: "Which name?"}));
  cases.controlsIgnored[type] = waitingAgeChip(state, {now: knownNow});
}
cases.questionIsNotWaiting = waitingAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, {question_id: "q1", question: "Which name?"}),
]), {now: knownNow});
cases.agentMessageIgnored = waitingAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.message", STAMP, {kind: "waiting", text: "hold"})],
}, {now: knownNow});

cases.known = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: knownNow});
cases.offset = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.questionThenWaiting = waitingAgeChip(withEvents([
  ev("e1", "mission.question", OLDER, {question_id: "q1", question: "Which name?"}),
  ev("e2", "mission.waiting", STAMP, {question_id: "q1", question: "Which name?"}),
]), {now: knownNow});
cases.newestOpen = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", OLDER),
  ev("e2", "mission.waiting", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", OLDER),
  ev("e2", "mission.running", "2026-09-23T07:30:00Z", {reason: "work finished"}),
  ev("e3", "mission.waiting", STAMP),
]), {now: knownNow});
cases.seconds = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: AT + 59000});
cases.justNow = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: AT + 400});
cases.hours = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: AT - 30000});
cases.noClock = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]));
cases.badNow = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: Number.NaN});
cases.zeroNow = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: 0});
cases.suspendKeepsWait = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.suspended", NEWER, {reason: "shutdown"}),
]), {now: knownNow});
cases.answerKeepsWait = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP, {question_id: "q1"}),
  ev("e2", "user.answered", NEWER, {question_id: "q1", answer: "yes"}),
]), {now: knownNow});

const bad = {};
bad.blank = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", ""),
]), {now: knownNow});
bad.whitespace = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "   "),
]), {now: knownNow});
bad.untrimmed = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", " " + STAMP),
]), {now: knownNow});
bad.missing = waitingAgeChip(withEvents([
  {id: "e1", event_type: "mission.waiting", actor_id: "root", payload: {reason: "Waiting"}},
]), {now: knownNow});
bad.garbage = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "yesterday"),
]), {now: knownNow});
bad.epoch = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", 0),
]), {now: knownNow});
bad.future = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.waiting", ""),
]), {now: knownNow});
bad.impossibleDay = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = waitingAgeChip({
  mission: mission({status: "waiting"}),
  preview: false,
}, {now: knownNow});
bad.emptyFeed = waitingAgeChip(newState(mission({status: "waiting"})), {now: knownNow});
bad.questionAfterClear = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", OLDER),
  ev("e2", "mission.running", "2026-09-23T07:30:00Z", {reason: "work finished"}),
  ev("e3", "mission.question", STAMP, {question_id: "q1", question: "Which name?"}),
]), {now: knownNow});
bad.naive = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.pausedAfterWait = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "user pause"}),
]), {now: knownNow});
cases.blockedAfterWait = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.blocked", NEWER, {reason: "capability"}),
]), {now: knownNow});
cases.runningAfterWait = waitingAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.running", NEWER, {reason: "continuing"}),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.running", NEWER, {reason: "continuing"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = waitingAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = waitingAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = waitingAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = waitingAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
