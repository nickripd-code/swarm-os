import {applyEvent, lastErrorAtChip, LAST_ERROR_AT_UNAVAILABLE, newState, projectEvents} from "../app/static/state.mjs";

const STAMP = "2026-09-23T11:56:00Z";
const NOW = Date.parse("2026-09-23T12:00:00Z");
const UPDATED = "2026-09-23T11:50:00Z";

function mission(status, extra = {}) {
  return {
    id: "m1",
    goal: "Ship it",
    status,
    created_at: "2026-09-23T08:00:00Z",
    updated_at: UPDATED,
    ...extra,
  };
}

function stateWith(status, events, extra = {}) {
  const state = newState(mission(status, extra));
  for (const event of events) applyEvent(state, event);
  return state;
}

function event(id, event_type, created_at, payload = {}) {
  return {id, event_type, created_at, payload};
}

function view(state, now = NOW) {
  return lastErrorAtChip(state, {now});
}

const failed = event(1, "mission.failed", STAMP, {error: "boom", failure_class: "TIMEOUT"});
const cases = {
  unavailable: LAST_ERROR_AT_UNAVAILABLE,
  stamp: STAMP,
  updated: UPDATED,
  noMission: view(newState(null)),
  preview: view({...stateWith("failed", [failed]), preview: true}),
  running: view(stateWith("running", [])),
  completed: view(stateWith("running", [
    failed,
    event(2, "mission.completed", "2026-09-23T11:57:00Z", {summary: "done"}),
  ])),
  taskWait: view(stateWith("running", [
    event(1, "mission.waiting", STAMP, {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}),
  ])),
  blocked: view(stateWith("blocked", [
    event(1, "mission.blocked", STAMP, {reason: "Needs a tool"}),
  ])),
  known: view(stateWith("running", [failed])),
  trimmed: view(stateWith("running", [
    event(1, "mission.failed", "  " + STAMP + "  ", {error: "boom", failure_class: "TIMEOUT"}),
  ])),
  offset: view(stateWith("running", [
    event(1, "mission.failed", "2026-09-23T07:56:00-04:00", {error: "boom", failure_class: "TIMEOUT"}),
  ])),
  parkedQuestion: view(stateWith("running", [
    event(1, "mission.question", STAMP, {question_id: "q1", question: "Which group?", reason: "Need a choice"}),
  ])),
  parkedApproval: view(stateWith("running", [
    event(1, "mission.waiting", STAMP, {
      kind: "approval", question_id: "q1", question: "Approve finish?",
      reason: "Need approval", approval_action: "finish",
    }),
  ])),
  llmFailed: view(stateWith("running", [
    event(1, "llm.failed", STAMP, {error: "timeout", failure_class: "TIMEOUT"}),
  ])),
  clearedLlm: view(stateWith("running", [
    event(1, "llm.failed", STAMP, {error: "timeout", failure_class: "TIMEOUT"}),
    event(2, "llm.completed", "2026-09-23T11:57:00Z", {input_tokens: 1, output_tokens: 1}),
  ])),
  newerWins: view(stateWith("running", [
    event(1, "llm.failed", "2026-09-23T11:40:00Z", {error: "earlier", failure_class: "TIMEOUT"}),
    event(2, "mission.failed", STAMP, {error: "boom", failure_class: "TIMEOUT"}),
  ])),
  missingResult: view(stateWith("failed", [], {result: {error: "boom", failure_class: "TIMEOUT"}})),
  blank: view(stateWith("running", [event(1, "mission.failed", "  ", {error: "boom", failure_class: "TIMEOUT"})])),
  nullStamp: view(stateWith("running", [event(1, "mission.failed", null, {error: "boom"})])),
  numericZero: view(stateWith("running", [event(1, "mission.failed", 0, {error: "boom"})])),
  epoch: view(stateWith("running", [event(1, "mission.failed", "1970-01-01T00:00:00Z", {error: "boom"})])),
  epochFraction: view(stateWith("running", [event(1, "mission.failed", "1970-01-01T00:00:00.000Z", {error: "boom"})])),
  garbage: view(stateWith("running", [event(1, "mission.failed", "not-a-time", {error: "boom"})])),
  impossibleDay: view(stateWith("running", [event(1, "mission.failed", "2026-02-31T00:00:00Z", {error: "boom"})])),
  naive: view(stateWith("running", [event(1, "mission.failed", "2026-09-23T11:56:00", {error: "boom"})])),
  dateOnly: view(stateWith("running", [event(1, "mission.failed", "2026-09-23", {error: "boom"})])),
  parkedNoStamp: view(stateWith("waiting", [], {
    pending_question: {question_id: "q1", question: "Which group?", reason: "Need a choice"},
  })),
  parkedBlank: view(stateWith("running", [
    event(1, "mission.question", "", {question_id: "q1", question: "Which group?", reason: "Need a choice"}),
  ])),
  noClock: lastErrorAtChip(stateWith("running", [failed]), {}),
  badNow: lastErrorAtChip(stateWith("running", [failed]), {now: Number.NaN}),
  zeroNow: lastErrorAtChip(stateWith("running", [failed]), {now: 0}),
  seconds: view(stateWith("running", [failed]), Date.parse(STAMP) + 59000),
  justNow: view(stateWith("running", [failed]), Date.parse(STAMP)),
  hours: view(stateWith("running", [failed]), Date.parse(STAMP) + 2 * 60 * 60 * 1000),
  oneDay: view(stateWith("running", [failed]), Date.parse(STAMP) + 24 * 60 * 60 * 1000),
  micros: view(stateWith("running", [
    event(1, "mission.failed", "2026-09-23T11:59:00.123456Z", {error: "boom", failure_class: "TIMEOUT"}),
  ])),
  skewOk: view(stateWith("running", [failed]), Date.parse(STAMP) - 119000),
  skewHide: view(stateWith("running", [failed]), Date.parse(STAMP) - 121000),
  updatedIgnored: view(stateWith("failed", [], {updated_at: STAMP, result: {error: "boom", failure_class: "TIMEOUT"}})),
  createdIgnored: view(stateWith("running", [])),
};

const source = mission("pending");
const log = [
  event(1, "mission.started", "2026-09-23T11:00:00Z", {mode: "cloud"}),
  failed,
];
cases.replayBefore = view(projectEvents(source, log, 0));
cases.replayAtFailure = view(projectEvents(source, log, 1));
cases.resumedPark = view(stateWith("running", [
  event(1, "mission.question", STAMP, {question_id: "q1", question: "Which group?", reason: "Need a choice"}),
  event(2, "user.answered", "2026-09-23T11:57:00Z", {question_id: "q1", answer: "First"}),
  event(3, "mission.running", "2026-09-23T11:58:00Z", {reason: "Answer consumed"}),
]));

process.stdout.write(JSON.stringify(cases));
