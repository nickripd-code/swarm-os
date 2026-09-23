import {newState, applyEvent, projectEvents, pauseAgeChip, PAUSE_AGE_UNAVAILABLE} from "../app/static/state.mjs";

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

function ev(id, type, created_at, payload = {reason: "Execution paused by user"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: PAUSE_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = pauseAgeChip(newState());
cases.noMission = pauseAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.paused", STAMP)],
});
cases.preview = pauseAgeChip(withEvents(
  [ev("e1", "mission.paused", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: knownNow, preview: true});
cases.notPaused = pauseAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
]), {now: knownNow});

const controls = [
  "mission.blocked",
  "mission.waiting",
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
  cases.controlsIgnored[type] = pauseAgeChip(state, {now: knownNow});
}
cases.waitingIsNotPause = pauseAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: knownNow});
cases.blockedIsNotPause = pauseAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP, {reason: "capability"}),
]), {now: knownNow});
cases.suspendIsNotPause = pauseAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP, {reason: "shutdown"}),
]), {now: knownNow});
const forced = withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.blocked", NEWER, {reason: "capability"}),
  ev("e3", "mission.suspended", NEWER, {reason: "shutdown"}),
]);
forced.mission.status = "paused";
cases.forcedStatusWithoutPause = pauseAgeChip(forced, {now: knownNow});
cases.pausedAtFieldIgnored = pauseAgeChip(newState(mission({
  status: "paused",
  paused_at: STAMP,
})), {now: knownNow});
cases.agentPausedIgnored = pauseAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.updated", STAMP, {status: "paused"})],
}, {now: knownNow});

cases.known = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: knownNow});
cases.offset = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.waitingThenPause = pauseAgeChip(withEvents([
  ev("e1", "mission.waiting", OLDER),
  ev("e2", "mission.paused", STAMP),
]), {now: knownNow});
cases.newestOpen = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", OLDER),
  ev("e2", "mission.paused", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", OLDER),
  ev("e2", "mission.resumed", "2026-09-23T07:30:00Z", {reason: "Human resume"}),
  ev("e3", "mission.paused", STAMP),
]), {now: knownNow});
cases.seconds = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: AT + 59000});
cases.justNow = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: AT + 400});
cases.hours = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: AT - 30000});
cases.noClock = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]));
cases.badNow = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: Number.NaN});
cases.zeroNow = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: 0});
cases.suspendKeepsPause = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
  ev("e2", "mission.suspended", NEWER, {reason: "shutdown"}),
]), {now: knownNow});
cases.answerKeepsPause = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
  ev("e2", "user.answered", NEWER, {question_id: "q1", answer: "yes"}),
]), {now: knownNow});
cases.resumeRequestKeepsPause = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
  ev("e2", "mission.resume_requested", NEWER, {reason: "Human resume"}),
]), {now: knownNow});

const bad = {};
bad.blank = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", ""),
]), {now: knownNow});
bad.whitespace = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "   "),
]), {now: knownNow});
bad.untrimmed = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", " " + STAMP),
]), {now: knownNow});
bad.missing = pauseAgeChip(withEvents([
  {id: "e1", event_type: "mission.paused", actor_id: "root", payload: {reason: "Execution paused by user"}},
]), {now: knownNow});
bad.garbage = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "yesterday"),
]), {now: knownNow});
bad.epoch = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", 0),
]), {now: knownNow});
bad.future = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
  ev("e2", "mission.paused", ""),
]), {now: knownNow});
bad.impossibleDay = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = pauseAgeChip({
  mission: mission({status: "paused"}),
  preview: false,
}, {now: knownNow});
bad.emptyFeed = pauseAgeChip(newState(mission({status: "paused"})), {now: knownNow});
bad.naive = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.resumedAfterPause = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
  ev("e2", "mission.resumed", NEWER, {reason: "Human resume"}),
]), {now: knownNow});
cases.blockedAfterPause = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
  ev("e2", "mission.blocked", NEWER, {reason: "capability"}),
]), {now: knownNow});
cases.waitingAfterPause = pauseAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP),
  ev("e2", "mission.waiting", NEWER),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.paused", STAMP),
  ev("e2", "mission.resumed", NEWER, {reason: "Human resume"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = pauseAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = pauseAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = pauseAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = pauseAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
