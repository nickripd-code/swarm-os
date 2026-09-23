import {newState, applyEvent, projectEvents, completeAgeChip, COMPLETE_AGE_UNAVAILABLE} from "../app/static/state.mjs";

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

function ev(id, type, created_at, payload = {summary: "Result ready"}) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: COMPLETE_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = completeAgeChip(newState());
cases.noMission = completeAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.completed", STAMP)],
});
cases.preview = completeAgeChip(withEvents(
  [ev("e1", "mission.completed", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: knownNow, preview: true});
cases.notCompleted = completeAgeChip(withEvents([
  ev("e1", "mission.started", OLDER, {mode: "live"}),
]), {now: knownNow});

const controls = [
  "mission.blocked",
  "mission.waiting",
  "mission.stopped",
  "mission.resumed",
  "mission.resume_requested",
  "mission.paused",
  "mission.failed",
  "mission.suspended",
  "mission.running",
  "user.answered",
  "user.answer_consumed",
  "task.blocked",
  "task.completed",
  "llm.completed",
  "verification.passed",
  "job.completed",
  "tool.completed",
];
cases.controlsIgnored = {};
for (const type of controls) {
  const state = newState(mission({status: "running"}));
  applyEvent(state, ev("e1", type, STAMP, {reason: "parked", error: "no", question_id: "q1", question: "Which name?", summary: "done"}));
  cases.controlsIgnored[type] = completeAgeChip(state, {now: knownNow});
}
cases.failedIsNotComplete = completeAgeChip(withEvents([
  ev("e1", "mission.failed", STAMP, {error: "provider down"}),
]), {now: knownNow});
cases.stoppedIsNotComplete = completeAgeChip(withEvents([
  ev("e1", "mission.stopped", STAMP, {reason: "user stop"}),
]), {now: knownNow});
cases.blockedIsNotComplete = completeAgeChip(withEvents([
  ev("e1", "mission.blocked", STAMP, {reason: "capability"}),
]), {now: knownNow});
cases.pausedIsNotComplete = completeAgeChip(withEvents([
  ev("e1", "mission.paused", STAMP, {reason: "Execution paused by user"}),
]), {now: knownNow});
cases.llmCompletedIsNotMissionComplete = completeAgeChip(withEvents([
  ev("e1", "llm.completed", STAMP, {output_tokens: 1}),
]), {now: knownNow});
const forced = withEvents([
  ev("e1", "mission.stopped", STAMP, {reason: "user stop"}),
  ev("e2", "mission.failed", NEWER, {error: "provider down"}),
  ev("e3", "mission.blocked", NEWER, {reason: "capability"}),
]);
forced.mission.status = "completed";
cases.forcedStatusWithoutComplete = completeAgeChip(forced, {now: knownNow});
cases.completedAtFieldIgnored = completeAgeChip(newState(mission({
  status: "completed",
  completed_at: STAMP,
})), {now: knownNow});
cases.agentCompletedIgnored = completeAgeChip({
  mission: mission({status: "running"}),
  preview: false,
  events: [ev("e1", "agent.updated", STAMP, {status: "completed"})],
}, {now: knownNow});

cases.known = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: knownNow});
cases.offset = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.runningThenComplete = completeAgeChip(withEvents([
  ev("e1", "mission.running", OLDER),
  ev("e2", "mission.completed", STAMP),
]), {now: knownNow});
cases.newestOpen = completeAgeChip(withEvents([
  ev("e1", "mission.completed", OLDER),
  ev("e2", "mission.completed", STAMP),
]), {now: knownNow});
cases.priorPeriodIgnored = completeAgeChip(withEvents([
  ev("e1", "mission.completed", OLDER),
  ev("e2", "mission.running", "2026-09-23T07:30:00Z"),
  ev("e3", "mission.completed", STAMP),
]), {now: knownNow});
cases.seconds = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: AT + 59000});
cases.justNow = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: AT + 400});
cases.hours = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: AT - 30000});
cases.noClock = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]));
cases.badNow = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: Number.NaN});
cases.zeroNow = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: 0});
cases.suspendKeepsComplete = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
  ev("e2", "mission.suspended", NEWER, {reason: "shutdown"}),
]), {now: knownNow});
cases.answerKeepsComplete = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
  ev("e2", "user.answered", NEWER, {question_id: "q1", answer: "yes"}),
]), {now: knownNow});
cases.llmCompletedKeepsMissionComplete = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
  ev("e2", "llm.completed", NEWER, {output_tokens: 3}),
]), {now: knownNow});

const bad = {};
bad.blank = completeAgeChip(withEvents([
  ev("e1", "mission.completed", ""),
]), {now: knownNow});
bad.whitespace = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "   "),
]), {now: knownNow});
bad.untrimmed = completeAgeChip(withEvents([
  ev("e1", "mission.completed", " " + STAMP),
]), {now: knownNow});
bad.missing = completeAgeChip(withEvents([
  {id: "e1", event_type: "mission.completed", actor_id: "root", payload: {summary: "Result ready"}},
]), {now: knownNow});
bad.garbage = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "yesterday"),
]), {now: knownNow});
bad.epoch = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = completeAgeChip(withEvents([
  ev("e1", "mission.completed", 0),
]), {now: knownNow});
bad.future = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
]), {now: AT - 121000});
bad.invalidNewest = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
  ev("e2", "mission.completed", ""),
]), {now: knownNow});
bad.impossibleDay = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.missingFeed = completeAgeChip({
  mission: mission({status: "completed"}),
  preview: false,
}, {now: knownNow});
bad.emptyFeed = completeAgeChip(newState(mission({status: "completed"})), {now: knownNow});
bad.naive = completeAgeChip(withEvents([
  ev("e1", "mission.completed", "2026-09-23T08:00:00"),
]), {now: knownNow});
cases.bad = bad;

cases.failedAfterComplete = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
  ev("e2", "mission.failed", NEWER, {error: "provider down"}),
]), {now: knownNow});
cases.stoppedAfterComplete = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
  ev("e2", "mission.stopped", NEWER, {reason: "user stop"}),
]), {now: knownNow});
cases.blockedAfterComplete = completeAgeChip(withEvents([
  ev("e1", "mission.completed", STAMP),
  ev("e2", "mission.blocked", NEWER, {reason: "capability"}),
]), {now: knownNow});

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.completed", STAMP),
  ev("e2", "mission.stopped", NEWER, {reason: "user stop"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = completeAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = completeAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAfter = completeAgeChip(projectEvents(source, log, 2), {now: knownNow});
cases.replayEmpty = completeAgeChip(projectEvents(source, log, -1), {now: knownNow});

console.log(JSON.stringify(cases));
