import {newState, applyEvent, projectEvents, questionAgeChip, QUESTION_AGE_UNAVAILABLE} from "../app/static/state.mjs";

const STAMP = "2026-09-23T08:00:00Z";
const AT = Date.parse(STAMP);
const OLDER = "2026-09-23T07:00:00Z";
const readable = {question_id: "q1", question: "Which name?"};

function mission(extra = {}) {
  return {id: "m1", goal: "Ship the note", status: "waiting", created_at: "2026-09-23T07:00:00Z", pending_question: readable, ...extra};
}

function withEvents(events, extra = {}) {
  const state = newState(mission());
  for (const event of events) applyEvent(state, event);
  Object.assign(state, extra);
  return state;
}

function ev(id, type, created_at, payload = readable) {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const cases = {unavailable: QUESTION_AGE_UNAVAILABLE, stamp: STAMP};
const knownNow = AT + 4 * 60 * 1000;

cases.idle = questionAgeChip(newState());
cases.noMission = questionAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.question", STAMP)],
});
cases.preview = questionAgeChip(withEvents(
  [ev("e1", "mission.question", STAMP)],
  {preview: true},
), {now: knownNow});
cases.previewOption = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: knownNow, preview: true});
cases.missingKey = questionAgeChip({
  mission: {id: "m1", goal: "Ship the note", status: "running"},
  preview: false,
  events: [ev("e1", "mission.question", STAMP)],
}, {now: knownNow});

const noneState = newState(mission({pending_question: null}));
applyEvent(noneState, ev("e1", "mission.started", OLDER, {mode: "live"}));
cases.explicitNone = questionAgeChip(noneState, {now: knownNow});

cases.known = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: knownNow});
cases.offset = questionAgeChip(withEvents([
  ev("e1", "mission.question", "2026-09-23T09:00:00+01:00"),
]), {now: knownNow});
cases.approval = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, {
    question_id: "q1",
    question: "Approve finish?",
    kind: "approval",
    approval_action: "finish",
  }),
]), {now: knownNow});
cases.oldestWins = questionAgeChip(withEvents([
  ev("e1", "mission.question", OLDER),
  ev("e2", "mission.question", STAMP),
]), {now: knownNow});
cases.otherIdIgnored = questionAgeChip(withEvents([
  ev("e1", "mission.question", OLDER, {question_id: "other", question: "Older?"}),
  ev("e2", "mission.question", STAMP),
]), {now: knownNow});
cases.seconds = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: AT + 59000});
cases.justNow = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: AT + 400});
cases.hours = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = questionAgeChip(withEvents([
  ev("e1", "mission.question", "2026-09-23T08:00:00.500000Z"),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: AT - 30000});
cases.noClock = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]));
cases.badNow = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: Number.NaN});
cases.zeroNow = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: 0});

const controls = [
  "mission.blocked",
  "mission.paused",
  "mission.stopped",
  "mission.resumed",
  "mission.resume_requested",
  "mission.failed",
  "mission.completed",
  "mission.waiting",
  "mission.running",
  "user.answered",
  "user.answer_consumed",
  "task.blocked",
];
cases.controlsIgnored = {};
for (const type of controls) {
  const state = newState(mission({pending_question: null, status: "running"}));
  applyEvent(state, ev("e1", type, STAMP, {question_id: "q1", question: "Which name?", reason: "blocked"}));
  cases.controlsIgnored[type] = questionAgeChip(state, {now: knownNow});
}
cases.waitingIsNotAsk = questionAgeChip(withEvents([
  ev("e1", "mission.waiting", STAMP, {question_id: "q1", question: "Which name?", reason: "Waiting"}),
]), {now: knownNow});
cases.agentMessageIgnored = questionAgeChip({
  mission: mission({pending_question: null}),
  preview: false,
  events: [ev("e1", "agent.message", STAMP, {kind: "question", text: "Which name?"})],
}, {now: knownNow});

const bad = {};
bad.blank = questionAgeChip(withEvents([
  ev("e1", "mission.question", ""),
]), {now: knownNow});
bad.whitespace = questionAgeChip(withEvents([
  ev("e1", "mission.question", "   "),
]), {now: knownNow});
bad.missing = questionAgeChip(withEvents([
  {id: "e1", event_type: "mission.question", actor_id: "root", payload: readable},
]), {now: knownNow});
bad.garbage = questionAgeChip(withEvents([
  ev("e1", "mission.question", "yesterday"),
]), {now: knownNow});
bad.epoch = questionAgeChip(withEvents([
  ev("e1", "mission.question", "1970-01-01T00:00:00Z"),
]), {now: knownNow});
bad.epochMillis = questionAgeChip(withEvents([
  ev("e1", "mission.question", "1970-01-01T00:00:00.000Z"),
]), {now: knownNow});
bad.numericZero = questionAgeChip(withEvents([
  ev("e1", "mission.question", 0),
]), {now: knownNow});
bad.future = questionAgeChip(withEvents([
  ev("e1", "mission.question", STAMP),
]), {now: AT - 121000});
bad.invalidOldest = questionAgeChip(withEvents([
  ev("e1", "mission.question", ""),
  ev("e2", "mission.question", STAMP),
]), {now: knownNow});
bad.impossibleDay = questionAgeChip(withEvents([
  ev("e1", "mission.question", "2026-02-31T08:00:00Z"),
]), {now: knownNow});
bad.blankPrompt = questionAgeChip({
  mission: mission({pending_question: {question_id: "q1", question: "   "}}),
  preview: false,
  events: [ev("e1", "mission.question", STAMP)],
}, {now: knownNow});
bad.blankId = questionAgeChip({
  mission: mission({pending_question: {question_id: "  ", question: "Which name?"}}),
  preview: false,
  events: [ev("e1", "mission.question", STAMP)],
}, {now: knownNow});
bad.number = questionAgeChip({
  mission: mission({pending_question: 1}),
  preview: false,
  events: [ev("e1", "mission.question", STAMP)],
}, {now: knownNow});
bad.array = questionAgeChip({
  mission: mission({pending_question: [readable]}),
  preview: false,
  events: [ev("e1", "mission.question", STAMP)],
}, {now: knownNow});
bad.missingFeed = questionAgeChip({
  mission: mission(),
  preview: false,
}, {now: knownNow});
bad.noMatchingAsk = questionAgeChip({
  mission: mission(),
  preview: false,
  events: [ev("e1", "mission.blocked", STAMP, {reason: "capability"})],
}, {now: knownNow});
cases.bad = bad;

const log = [
  ev("e0", "mission.started", OLDER, {mode: "live"}),
  ev("e1", "mission.question", STAMP),
  ev("e2", "user.answered", "2026-09-23T08:05:00Z", {question_id: "q1", answer: "yes"}),
];
const source = {id: "m1", goal: "Ship the note", created_at: OLDER};
cases.replayBefore = questionAgeChip(projectEvents(source, log, 0), {now: knownNow});
cases.replayAt = questionAgeChip(projectEvents(source, log, 1), {now: knownNow});
cases.replayAnswered = questionAgeChip(projectEvents(source, log, 2), {now: knownNow});

const replaced = [
  ev("q1", "mission.question", OLDER, {question_id: "q-old", question: "First?"}),
  ev("a1", "user.answered", "2026-09-23T07:30:00Z", {question_id: "q-old", answer: "yes"}),
  ev("q2", "mission.question", STAMP, {question_id: "q-new", question: "Second?"}),
];
cases.newestPending = questionAgeChip(projectEvents(source, replaced, 2), {now: knownNow});

console.log(JSON.stringify(cases));
