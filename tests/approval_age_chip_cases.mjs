import {
  applyEvent, approvalAgeChip, newState, projectEvents,
  APPROVAL_AGE_NONE, APPROVAL_AGE_UNAVAILABLE,
} from "../app/static/state.mjs";

const STAMP = "2026-09-23T08:00:00Z";
const AT = Date.parse(STAMP);
const NOW = AT + 4 * 60 * 1000;

function mission(extra = {}) {
  return {
    id: "m1",
    goal: "Ship the readout",
    status: "waiting",
    created_at: "2026-09-23T07:00:00Z",
    pending_question: null,
    ...extra,
  };
}

function ev(id, type, created_at, payload = {}) {
  return {id, event_type: type, actor_id: "controller", payload, created_at};
}

function approval(question_id, action = "org_change") {
  return {
    question_id,
    question: "Approve " + action + "?",
    kind: "approval",
    approval_action: action,
  };
}

function withEvents(events, extra = {}) {
  const state = newState(mission());
  for (const event of events) applyEvent(state, event);
  Object.assign(state, extra);
  return state;
}

const cases = {unavailable: APPROVAL_AGE_UNAVAILABLE, none: APPROVAL_AGE_NONE, stamp: STAMP};

cases.idle = approvalAgeChip(newState());
cases.noMission = approvalAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "mission.question", STAMP, approval("q-org"))],
});
cases.preview = approvalAgeChip(withEvents(
  [ev("e1", "mission.question", STAMP, approval("q-org"))],
  {preview: true},
), {now: NOW});

cases.explicitNull = approvalAgeChip({
  preview: false,
  mission: mission(),
  events: [ev("e1", "mission.question", STAMP, approval("q-old"))],
}, {now: NOW});
cases.humanQuestion = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, {question_id: "q-ask", question: "Which name?", kind: "question"}),
]), {now: NOW});
cases.answeredHistoryIsNotPending = approvalAgeChip({
  preview: false,
  mission: mission({
    answers: [{question_id: "q-old", kind: "approval", approval_action: "org_change", answer: "approve"}],
  }),
  events: [ev("e1", "mission.question", STAMP, approval("q-old"))],
}, {now: NOW});

cases.known = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: NOW});
cases.offset = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "2026-09-23T09:00:00+01:00", approval("q-fin", "finish")),
]), {now: NOW});
cases.payment = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-pay", "live_payment")),
]), {now: NOW});
cases.seconds = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: AT + 59000});
cases.justNow = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: AT + 400});
cases.hours = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "2026-09-23T08:00:00.500000Z", approval("q-org")),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: AT - 30000});
cases.noClock = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]));
cases.badNow = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: Number.NaN});
cases.zeroNow = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: 0});

const replaced = newState(mission());
applyEvent(replaced, ev("e1", "mission.question", "2026-09-23T07:00:00Z", approval("q-a")));
applyEvent(replaced, ev("e2", "user.answered", "2026-09-23T07:30:00Z", {question_id: "q-a", answer: "approve"}));
applyEvent(replaced, ev("e3", "mission.question", STAMP, approval("q-b", "finish")));
cases.secondApproval = approvalAgeChip(replaced, {now: NOW});

const cleared = newState(mission());
applyEvent(cleared, ev("e1", "mission.question", STAMP, approval("q-org")));
applyEvent(cleared, ev("e2", "user.answered", "2026-09-23T08:02:00Z", {question_id: "q-org", answer: "approve"}));
cases.afterAnswer = approvalAgeChip(cleared, {now: NOW});

const waitingWork = newState(mission());
applyEvent(waitingWork, ev("e1", "mission.waiting", STAMP, {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}));
cases.inFlightWait = approvalAgeChip(waitingWork, {now: NOW});

cases.slotWithoutEvent = approvalAgeChip({
  preview: false,
  mission: mission({pending_question: approval("q-org")}),
  events: [],
}, {now: NOW});
cases.payloadClockIgnored = approvalAgeChip({
  preview: false,
  mission: mission({
    pending_question: {...approval("q-org"), created_at: STAMP},
  }),
  events: [ev("e1", "mission.waiting", STAMP, {question_id: "q-org", kind: "approval"})],
}, {now: NOW});
cases.missionStartIgnored = approvalAgeChip({
  preview: false,
  mission: mission({pending_question: approval("q-org")}),
  events: [ev("e1", "mission.question", "", approval("q-org"))],
}, {now: NOW});

const bad = {};
bad.missingField = approvalAgeChip({
  preview: false,
  mission: {id: "m1", goal: "Ship the readout", created_at: "2026-09-23T07:00:00Z"},
  events: [ev("e1", "mission.question", STAMP, approval("q-org"))],
}, {now: NOW});
bad.missingKind = approvalAgeChip({
  preview: false,
  mission: mission({pending_question: {question_id: "q-x", question: "Approve?"}}),
  events: [ev("e1", "mission.question", STAMP, {question_id: "q-x", question: "Approve?"})],
}, {now: NOW});
bad.blankApprovalId = approvalAgeChip({
  preview: false,
  mission: mission({pending_question: {question_id: "  ", question: "Approve?", kind: "approval"}}),
  events: [ev("e1", "mission.question", STAMP, {question_id: "  ", question: "Approve?", kind: "approval"})],
}, {now: NOW});
bad.unknownKind = approvalAgeChip({
  preview: false,
  mission: mission({pending_question: {question_id: "q-x", kind: "maybe"}}),
  events: [ev("e1", "mission.question", STAMP, {question_id: "q-x", kind: "maybe"})],
}, {now: NOW});
bad.blank = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "", approval("q-org")),
]), {now: NOW});
bad.whitespace = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "   ", approval("q-org")),
]), {now: NOW});
bad.missing = approvalAgeChip(withEvents([
  {id: "e1", event_type: "mission.question", actor_id: "controller", payload: approval("q-org")},
]), {now: NOW});
bad.garbage = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "yesterday", approval("q-org")),
]), {now: NOW});
bad.epoch = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "1970-01-01T00:00:00Z", approval("q-org")),
]), {now: NOW});
bad.epochMillis = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "1970-01-01T00:00:00.000Z", approval("q-org")),
]), {now: NOW});
bad.numericZero = approvalAgeChip(withEvents([
  ev("e1", "mission.question", 0, approval("q-org")),
]), {now: NOW});
bad.future = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
]), {now: AT - 121000});
bad.invalidNewest = approvalAgeChip(withEvents([
  ev("e1", "mission.question", STAMP, approval("q-org")),
  ev("e2", "mission.question", "", approval("q-org")),
]), {now: NOW});
bad.impossibleDay = approvalAgeChip(withEvents([
  ev("e1", "mission.question", "2026-02-31T08:00:00Z", approval("q-org")),
]), {now: NOW});
bad.eventsMissing = approvalAgeChip({
  preview: false,
  mission: mission({pending_question: approval("q-org")}),
}, {now: NOW});
cases.bad = bad;

const log = [
  ev("e0", "mission.started", "2026-09-23T07:00:00Z", {mode: "demo"}),
  ev("e1", "mission.question", STAMP, approval("q-org")),
];
cases.replayBefore = approvalAgeChip(projectEvents(mission(), log, 0), {now: NOW});
cases.replayAt = approvalAgeChip(projectEvents(mission(), log, 1), {now: NOW});

console.log(JSON.stringify(cases));
