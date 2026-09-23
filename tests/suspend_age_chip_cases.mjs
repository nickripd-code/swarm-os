import {newState, applyEvent, projectEvents, suspendAgeChip, SUSPEND_AGE_UNAVAILABLE} from "../app/static/state.mjs";

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

function ev(id, type, created_at, payload = {reason: "Runtime is shutting down; unfinished work remains recoverable"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: SUSPEND_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = suspendAgeChip(newState());
cases.noMission = suspendAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.suspended", STAMP)],
});
cases.preview = suspendAgeChip(withEvents(
  [ev("e1", "mission.suspended", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: knownNow, preview: true});
cases.notSuspended = suspendAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
]), {now: knownNow});
cases.emptyFeed = suspendAgeChip(newState(mission()), {now: knownNow});

const controls = [
  "mission.blocked",
  "mission.waiting",
  "mission.paused",
  "mission.stopped",
  "mission.resumed",
  "mission.resume_requested",
  "mission.failed",
  "mission.completed",
  "mission.running",
  "mission.question",
  "user.answered",
  "user.answer_consumed",
  "task.blocked",
  "budget.warning",
];
cases.controlsIgnored = {};
for (const type of controls) {
  const state = newState(mission({status: "running"}));
  applyEvent(state, ev("e1", type, STAMP, {
    reason: "parked",
    question_id: "q1",
    question: "Which name?",
    token_spent: 1,
    token_budget: 3,
  }));
  cases.controlsIgnored[type] = suspendAgeChip(state, {now: knownNow});
}
cases.waitingIsNotSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP),
]), {now: knownNow});
cases.pausedIsNotSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP, {reason: "Execution paused by user"}),
]), {now: knownNow});
cases.blockedIsNotSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP, {reason: "capability"}),
]), {now: knownNow});
const forced = withEvents([
  ev("e1", "mission.waiting", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "Execution paused by user"}),
  ev("e3", "mission.blocked", NEWER, {reason: "capability"}),
]);
forced.mission.status = "suspended";
cases.forcedStatusWithoutSuspend = suspendAgeChip(forced, {now: knownNow});
cases.pausedAtFieldIgnored = suspendAgeChip(newState(mission({
  status: "paused",
  paused_at: STAMP,
})), {now: knownNow});
cases.agentSuspendedIgnored = suspendAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.updated", STAMP, {status: "suspended"})],
}, {now: knownNow});

cases.known = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: knownNow});
cases.offset = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.waitingThenSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.waiting", OLDER),
  ev("e2", "mission.suspended", STAMP),
]), {now: knownNow});
cases.pausedThenSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.paused", OLDER, {reason: "Execution paused by user"}),
  ev("e2", "mission.suspended", STAMP),
]), {now: knownNow});
cases.newestOpen = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", OLDER),
  ev("e2", "mission.suspended", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", OLDER),
  ev("e2", "mission.resumed", "2026-09-23T07:30:00Z", {reason: "Recovering durable unfinished mission"}),
  ev("e3", "mission.suspended", STAMP),
]), {now: knownNow});
cases.seconds = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: AT + 59000});
cases.justNow = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: AT + 400});
cases.hours = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: AT - 30000});
cases.noClock = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]));
cases.badNow = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: Number.NaN});
cases.zeroNow = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: 0});
cases.resumeRequestKeepsSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "mission.resume_requested", NEWER, {reason: "Human resume"}),
]), {now: knownNow});
cases.answerKeepsSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "user.answered", NEWER, {question_id: "q1", answer: "yes"}),
]), {now: knownNow});
cases.budgetWarningKeepsSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "budget.warning", NEWER, {token_spent: 2.5, token_budget: 3}),
]), {now: knownNow});
cases.runningStatusStillSuspended = suspendAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
  ev("e2", "mission.suspended", STAMP),
]), {now: knownNow});

const bad = {};
bad.blank = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", ""),
]), {now: knownNow});
bad.whitespace = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "   "),
]), {now: knownNow});
bad.untrimmed = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", " " + STAMP),
]), {now: knownNow});
bad.missing = suspendAgeChip(withEvents([
  {id: "e1", event_type: "mission.suspended", actor_id: "root", payload: {reason: "shutdown"}},
]), {now: knownNow});
bad.garbage = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "yesterday"),
]), {now: knownNow});
bad.epoch = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", 0),
]), {now: knownNow});
bad.future = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "mission.suspended", ""),
]), {now: knownNow});
bad.impossibleDay = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = suspendAgeChip({
  mission: mission({status: "running"}),
  preview: false,
}, {now: knownNow});
bad.naive = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.resumedAfterSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "mission.resumed", NEWER, {reason: "Recovering durable unfinished mission"}),
]), {now: knownNow});
cases.pausedAfterSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "mission.paused", NEWER, {reason: "Execution paused by user"}),
]), {now: knownNow});
cases.waitingAfterSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "mission.waiting", NEWER),
]), {now: knownNow});
cases.blockedAfterSuspend = suspendAgeChip(withEvents([
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "mission.blocked", NEWER, {reason: "capability"}),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.suspended", STAMP),
  ev("e2", "mission.resumed", NEWER, {reason: "Recovering durable unfinished mission"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = suspendAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = suspendAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = suspendAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = suspendAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
