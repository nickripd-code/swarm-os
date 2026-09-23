import {newState, applyEvent, projectEvents, stopAgeChip, STOP_AGE_UNAVAILABLE} from "../app/static/state.mjs";

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

function ev(id, type, created_at, payload = {reason: "All execution stopped"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: STOP_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = stopAgeChip(newState());
cases.noMission = stopAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.stopped", STAMP)],
});
cases.preview = stopAgeChip(withEvents(
  [ev("e1", "mission.stopped", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: knownNow, preview: true});
cases.notStopped = stopAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
]), {now: knownNow});

const controls = [
  "mission.blocked",
  "mission.waiting",
  "mission.paused",
  "mission.resumed",
  "mission.resume_requested",
  "mission.failed",
  "mission.completed",
  "mission.suspended",
  "mission.running",
  "user.answered",
  "user.answer_consumed",
  "task.stopped",
  "task.blocked",
];
cases.controlsIgnored = {};
for (const type of controls) {
  const state = newState(mission({status: "running"}));
  applyEvent(state, ev("e1", type, STAMP, {reason: "parked", question_id: "q1", question: "Which name?", id: "t1"}));
  cases.controlsIgnored[type] = stopAgeChip(state, {now: knownNow});
}
cases.waitingIsNotStop = stopAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: knownNow});
cases.pausedIsNotStop = stopAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP, {reason: "Execution paused by user"}),
]), {now: knownNow});
cases.failedIsNotStop = stopAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP, {error: "boom", failure_class: "PROVIDER_OUTAGE"}),
]), {now: knownNow});
cases.completedIsNotStop = stopAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP, {summary: "done"}),
]), {now: knownNow});
cases.taskStoppedIsNotStop = stopAgeChip(withEvents([
  ev("e1", "task.stopped", STAMP, {id: "t1", reason: "stopped"}),
]), {now: knownNow});
cases.suspendIsNotStop = stopAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP, {reason: "shutdown"}),
]), {now: knownNow});
const forced = withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "Execution paused by user"}),
  ev("e3", "mission.failed", NEWER, {error: "boom"}),
  ev("e4", "task.stopped", NEWER, {id: "t1"}),
]);
forced.mission.status = "stopped";
cases.forcedStatusWithoutStop = stopAgeChip(forced, {now: knownNow});
cases.stoppedAtFieldIgnored = stopAgeChip(newState(mission({
  status: "stopped",
  stopped_at: STAMP,
})), {now: knownNow});
cases.agentStoppedIgnored = stopAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.updated", STAMP, {status: "stopped", id: "a1"})],
}, {now: knownNow});

cases.known = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: knownNow});
cases.offset = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.pauseThenStop = stopAgeChip(withEvents([
  ev("e1", "mission.paused", OLDER, {reason: "Execution paused by user"}),
  ev("e2", "mission.stopped", STAMP),
]), {now: knownNow});
cases.failThenStop = stopAgeChip(withEvents([
  ev("e1", "mission.failed", OLDER, {error: "boom"}),
  ev("e2", "mission.stopped", STAMP),
]), {now: knownNow});
cases.taskThenStop = stopAgeChip(withEvents([
  ev("e1", "task.stopped", OLDER, {id: "t1"}),
  ev("e2", "mission.stopped", STAMP),
]), {now: knownNow});
cases.newestOpen = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", OLDER),
  ev("e2", "mission.stopped", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", OLDER),
  ev("e2", "mission.running", "2026-09-23T07:30:00Z"),
  ev("e3", "mission.stopped", STAMP),
]), {now: knownNow});
cases.seconds = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: AT + 59000});
cases.justNow = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: AT + 400});
cases.hours = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: AT - 30000});
cases.noClock = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]));
cases.badNow = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: Number.NaN});
cases.zeroNow = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: 0});
cases.suspendKeepsStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.suspended", NEWER, {reason: "shutdown"}),
]), {now: knownNow});
cases.answerKeepsStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "user.answered", NEWER, {question_id: "q1", answer: "yes"}),
]), {now: knownNow});
cases.resumeRequestKeepsStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.resume_requested", NEWER, {reason: "Human resume"}),
]), {now: knownNow});
cases.taskStoppedKeepsMissionStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "task.stopped", NEWER, {id: "t1"}),
]), {now: knownNow});

const bad = {};
bad.blank = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", ""),
]), {now: knownNow});
bad.whitespace = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "   "),
]), {now: knownNow});
bad.untrimmed = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", " " + STAMP),
]), {now: knownNow});
bad.missing = stopAgeChip(withEvents([
  {id: "e1", event_type: "mission.stopped", actor_id: "root", payload: {reason: "All execution stopped"}},
]), {now: knownNow});
bad.garbage = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "yesterday"),
]), {now: knownNow});
bad.epoch = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", 0),
]), {now: knownNow});
bad.future = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.stopped", ""),
]), {now: knownNow});
bad.impossibleDay = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = stopAgeChip({
  mission: mission({status: "stopped"}),
  preview: false,
}, {now: knownNow});
bad.emptyFeed = stopAgeChip(newState(mission({status: "stopped"})), {now: knownNow});
bad.naive = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.runningAfterStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.running", NEWER),
]), {now: knownNow});
cases.pausedAfterStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "Execution paused by user"}),
]), {now: knownNow});
cases.failedAfterStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.failed", NEWER, {error: "boom"}),
]), {now: knownNow});
cases.completedAfterStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.completed", NEWER, {summary: "done"}),
]), {now: knownNow});
cases.blockedAfterStop = stopAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.blocked", NEWER, {reason: "capability"}),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.stopped", STAMP),
  ev("e2", "mission.running", NEWER),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = stopAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = stopAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = stopAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = stopAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
