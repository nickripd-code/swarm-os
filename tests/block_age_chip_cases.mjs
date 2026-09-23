import {newState, applyEvent, projectEvents, blockAgeChip, BLOCK_AGE_UNAVAILABLE} from "../app/static/state.mjs";

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

function ev(id, type, created_at, payload = {reason: "Required capability is unavailable"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: BLOCK_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = blockAgeChip(newState());
cases.noMission = blockAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.blocked", STAMP)],
});
cases.preview = blockAgeChip(withEvents(
  [ev("e1", "mission.blocked", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: knownNow, preview: true});
cases.notBlocked = blockAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
]), {now: knownNow});

const controls = [
  "mission.waiting",
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
  cases.controlsIgnored[type] = blockAgeChip(state, {now: knownNow});
}
cases.questionIsNotBlock = blockAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, {question_id: "q1", question: "Which name?"}),
]), {now: knownNow});
cases.agentMessageIgnored = blockAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.message", STAMP, {kind: "blocked", text: "hold"})],
}, {now: knownNow});

cases.known = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: knownNow});
cases.offset = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.taskThenBlock = blockAgeChip(withEvents([
  ev("e1", "task.blocked", OLDER, {task_id: "t1", reason: "missing tool"}),
  ev("e2", "mission.blocked", STAMP),
]), {now: knownNow});
cases.newestOpen = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", OLDER),
  ev("e2", "mission.blocked", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", OLDER),
  ev("e2", "mission.running", "2026-09-23T07:30:00Z", {reason: "work finished"}),
  ev("e3", "mission.blocked", STAMP),
]), {now: knownNow});
cases.seconds = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: AT + 59000});
cases.justNow = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: AT + 400});
cases.hours = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: AT - 30000});
cases.noClock = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]));
cases.badNow = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: Number.NaN});
cases.zeroNow = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: 0});
cases.suspendKeepsBlock = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
  ev("e2", "mission.suspended", NEWER, {reason: "shutdown"}),
]), {now: knownNow});
cases.taskBlockedKeepsBlock = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
  ev("e2", "task.blocked", NEWER, {task_id: "t1", reason: "missing tool"}),
]), {now: knownNow});

const bad = {};
bad.blank = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", ""),
]), {now: knownNow});
bad.whitespace = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "   "),
]), {now: knownNow});
bad.untrimmed = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", " " + STAMP),
]), {now: knownNow});
bad.missing = blockAgeChip(withEvents([
  {id: "e1", event_type: "mission.blocked", actor_id: "root", payload: {reason: "blocked"}},
]), {now: knownNow});
bad.garbage = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "yesterday"),
]), {now: knownNow});
bad.epoch = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", 0),
]), {now: knownNow});
bad.future = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
  ev("e2", "mission.blocked", ""),
]), {now: knownNow});
bad.impossibleDay = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = blockAgeChip({
  mission: mission({status: "blocked"}),
  preview: false,
}, {now: knownNow});
bad.emptyFeed = blockAgeChip(newState(mission({status: "blocked"})), {now: knownNow});
bad.taskOnly = blockAgeChip({
  mission: mission({status: "blocked"}),
  preview: false,
  events: [ev("e1", "task.blocked", STAMP, {task_id: "t1", reason: "missing tool"})],
}, {now: knownNow});
bad.pauseOnly = blockAgeChip({
  mission: mission({status: "blocked"}),
  preview: false,
  events: [ev("e1", "mission.paused", STAMP, {reason: "user pause"})],
}, {now: knownNow});
bad.waitingOnly = blockAgeChip({
  mission: mission({status: "blocked"}),
  preview: false,
  events: [ev("e1", "mission.waiting", STAMP)],
}, {now: knownNow});
bad.suspendOnly = blockAgeChip({
  mission: mission({status: "blocked"}),
  preview: false,
  events: [ev("e1", "mission.suspended", STAMP, {reason: "shutdown"})],
}, {now: knownNow});
bad.naive = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.pausedAfterBlock = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "user pause"}),
]), {now: knownNow});
cases.waitingAfterBlock = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
  ev("e2", "mission.waiting", NEWER),
]), {now: knownNow});
cases.runningAfterBlock = blockAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP),
  ev("e2", "mission.running", NEWER, {reason: "continuing"}),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.blocked", STAMP),
  ev("e2", "mission.running", NEWER, {reason: "continuing"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = blockAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = blockAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = blockAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = blockAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
