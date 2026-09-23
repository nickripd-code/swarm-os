import {newState, applyEvent, projectEvents, failAgeChip, FAIL_AGE_UNAVAILABLE} from "../app/static/state.mjs";

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

function ev(id, type, created_at, payload = {error: "provider down", failure_class: "PROVIDER_OUTAGE"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: FAIL_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = failAgeChip(newState());
cases.noMission = failAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.failed", STAMP)],
});
cases.preview = failAgeChip(withEvents(
  [ev("e1", "mission.failed", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: knownNow, preview: true});
cases.notFailed = failAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
]), {now: knownNow});

const controls = [
  "mission.blocked",
  "mission.waiting",
  "mission.stopped",
  "mission.resumed",
  "mission.resume_requested",
  "mission.paused",
  "mission.completed",
  "mission.suspended",
  "mission.running",
  "user.answered",
  "user.answer_consumed",
  "task.blocked",
  "llm.failed",
  "verification.failed",
  "tool.failed",
];
cases.controlsIgnored = {};
for (const type of controls) {
  const state = newState(mission({status: "running"}));
  applyEvent(state, ev("e1", type, STAMP, {reason: "parked", error: "no", question_id: "q1", question: "Which name?"}));
  cases.controlsIgnored[type] = failAgeChip(state, {now: knownNow});
}
cases.stoppedIsNotFail = failAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP, {reason: "user stop"}),
]), {now: knownNow});
cases.completedIsNotFail = failAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP, {summary: "done"}),
]), {now: knownNow});
cases.blockedIsNotFail = failAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP, {reason: "capability"}),
]), {now: knownNow});
cases.pausedIsNotFail = failAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP, {reason: "Execution paused by user"}),
]), {now: knownNow});
const forced = withEvents([
  ev("e1", "mission.stopped", STAMP, {reason: "user stop"}),
  ev("e2", "mission.completed", NEWER, {summary: "done"}),
  ev("e3", "mission.blocked", NEWER, {reason: "capability"}),
]);
forced.mission.status = "failed";
cases.forcedStatusWithoutFail = failAgeChip(forced, {now: knownNow});
cases.failedAtFieldIgnored = failAgeChip(newState(mission({
  status: "failed",
  failed_at: STAMP,
})), {now: knownNow});
cases.agentFailedIgnored = failAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.updated", STAMP, {status: "failed"})],
}, {now: knownNow});

cases.known = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: knownNow});
cases.offset = failAgeChip(withEvents([
  ev("e1", "mission.failed", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.runningThenFail = failAgeChip(withEvents([
  ev("e1", "mission.running", OLDER),
  ev("e2", "mission.failed", STAMP),
]), {now: knownNow});
cases.newestOpen = failAgeChip(withEvents([
  ev("e1", "mission.failed", OLDER),
  ev("e2", "mission.failed", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = failAgeChip(withEvents([
  ev("e1", "mission.failed", OLDER),
  ev("e2", "mission.running", "2026-09-23T07:30:00Z"),
  ev("e3", "mission.failed", STAMP),
]), {now: knownNow});
cases.seconds = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: AT + 59000});
cases.justNow = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: AT + 400});
cases.hours = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = failAgeChip(withEvents([
  ev("e1", "mission.failed", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: AT - 30000});
cases.noClock = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]));
cases.badNow = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: Number.NaN});
cases.zeroNow = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: 0});
cases.suspendKeepsFail = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
  ev("e2", "mission.suspended", NEWER, {reason: "shutdown"}),
]), {now: knownNow});
cases.answerKeepsFail = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
  ev("e2", "user.answered", NEWER, {question_id: "q1", answer: "yes"}),
]), {now: knownNow});
cases.llmFailKeepsMissionFail = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
  ev("e2", "llm.failed", NEWER, {error: "later llm"}),
]), {now: knownNow});

const bad = {};
bad.blank = failAgeChip(withEvents([
  ev("e1", "mission.failed", ""),
]), {now: knownNow});
bad.whitespace = failAgeChip(withEvents([
  ev("e1", "mission.failed", "   "),
]), {now: knownNow});
bad.untrimmed = failAgeChip(withEvents([
  ev("e1", "mission.failed", " " + STAMP),
]), {now: knownNow});
bad.missing = failAgeChip(withEvents([
  {id: "e1", event_type: "mission.failed", actor_id: "root", payload: {error: "provider down"}},
]), {now: knownNow});
bad.garbage = failAgeChip(withEvents([
  ev("e1", "mission.failed", "yesterday"),
]), {now: knownNow});
bad.epoch = failAgeChip(withEvents([
  ev("e1", "mission.failed", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = failAgeChip(withEvents([
  ev("e1", "mission.failed", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = failAgeChip(withEvents([
  ev("e1", "mission.failed", 0),
]), {now: knownNow});
bad.future = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
  ev("e2", "mission.failed", ""),
]), {now: knownNow});
bad.impossibleDay = failAgeChip(withEvents([
  ev("e1", "mission.failed", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = failAgeChip({
  mission: mission({status: "failed"}),
  preview: false,
}, {now: knownNow});
bad.emptyFeed = failAgeChip(newState(mission({status: "failed"})), {now: knownNow});
bad.naive = failAgeChip(withEvents([
  ev("e1", "mission.failed", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.stoppedAfterFail = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
  ev("e2", "mission.stopped", NEWER, {reason: "user stop"}),
]), {now: knownNow});
cases.completedAfterFail = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
  ev("e2", "mission.completed", NEWER, {summary: "done"}),
]), {now: knownNow});
cases.blockedAfterFail = failAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP),
  ev("e2", "mission.blocked", NEWER, {reason: "capability"}),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.failed", STAMP),
  ev("e2", "mission.stopped", NEWER, {reason: "user stop"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = failAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = failAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = failAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = failAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
