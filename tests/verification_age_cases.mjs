import {newState, applyEvent, projectEvents, verificationAgeChip, VERIFICATION_AGE_UNAVAILABLE} from "../app/static/state.mjs";

const STAMP = "2026-09-23T08:00:00Z";
const AT = Date.parse(STAMP);

function mission() {
  return {id: "m1", goal: "Ship the note", status: "running", created_at: "2026-09-23T07:00:00Z"};
}

function withEvents(events, extra = {}) {
  const state = newState(mission());
  for (const event of events) applyEvent(state, event);
  Object.assign(state, extra);
  return state;
}

function ev(id, type, created_at, payload = {}) {
  return {id, event_type: type, actor_id: "verifier", payload, created_at};
}

const cases = {unavailable: VERIFICATION_AGE_UNAVAILABLE, stamp: STAMP};

cases.idle = verificationAgeChip(newState());
cases.noMission = verificationAgeChip({
  mission: null,
  preview: false,
  events: [ev("e1", "verification.passed", STAMP, {verdict: "pass"})],
});
cases.preview = verificationAgeChip(withEvents(
  [ev("e1", "verification.passed", STAMP, {verdict: "pass"})],
  {preview: true},
), {now: AT + 4 * 60 * 1000});

const knownNow = AT + 4 * 60 * 1000;
cases.known = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: knownNow});
cases.offset = verificationAgeChip(withEvents([
  ev("e1", "verification.failed", "2026-09-23T09:00:00+01:00", {verdict: "fail"}),
]), {now: knownNow});
cases.evidence = verificationAgeChip(withEvents([
  ev("e1", "verification.evidence.passed", STAMP, {kind: "file", ok: true}),
]), {now: knownNow});
cases.started = verificationAgeChip(withEvents([
  ev("e1", "verification.started", STAMP, {summary: "claim"}),
]), {now: knownNow});
cases.newerWins = verificationAgeChip(withEvents([
  ev("e1", "verification.started", "2026-09-23T07:00:00Z", {}),
  ev("e2", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: knownNow});
cases.evidenceNewer = verificationAgeChip(withEvents([
  ev("e1", "verification.started", "2026-09-23T07:00:00Z", {}),
  ev("e2", "verification.evidence.failed", STAMP, {kind: "pytest", ok: false}),
]), {now: knownNow});
cases.llmStartedIgnored = verificationAgeChip(withEvents([
  ev("e1", "llm.started", STAMP, {kind: "verification"}),
]), {now: knownNow});
cases.seconds = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: AT + 59000});
cases.justNow = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: AT + 400});
cases.hours = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: AT + 2 * 60 * 60 * 1000});
cases.oneDay = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: AT + 24 * 60 * 60 * 1000});
cases.micros = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", "2026-09-23T08:00:00.500000Z", {verdict: "pass"}),
]), {now: Date.parse("2026-09-23T08:00:00.500000Z") + 59000});
cases.skewOk = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: AT - 30000});
cases.noClock = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]));
cases.badNow = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: Number.NaN});
cases.zeroNow = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: 0});

const bad = {};
bad.blank = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", "", {verdict: "pass"}),
]), {now: knownNow});
bad.whitespace = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", "   ", {verdict: "pass"}),
]), {now: knownNow});
bad.missing = verificationAgeChip(withEvents([
  {id: "e1", event_type: "verification.failed", actor_id: "verifier", payload: {verdict: "fail"}},
]), {now: knownNow});
bad.garbage = verificationAgeChip(withEvents([
  ev("e1", "verification.started", "yesterday", {}),
]), {now: knownNow});
bad.epoch = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", "1970-01-01T00:00:00Z", {verdict: "pass"}),
]), {now: knownNow});
bad.epochMillis = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", "1970-01-01T00:00:00.000Z", {verdict: "pass"}),
]), {now: knownNow});
bad.numericZero = verificationAgeChip(withEvents([
  ev("e1", "verification.evidence.started", 0, {count: 1}),
]), {now: knownNow});
bad.future = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
]), {now: AT - 121000});
bad.invalidNewest = verificationAgeChip(withEvents([
  ev("e1", "verification.started", STAMP, {}),
  ev("e2", "verification.failed", "", {verdict: "fail"}),
]), {now: knownNow});
bad.impossibleDay = verificationAgeChip(withEvents([
  ev("e1", "verification.passed", "2026-02-31T08:00:00Z", {verdict: "pass"}),
]), {now: knownNow});
cases.bad = bad;

const log = [
  ev("e0", "mission.started", "2026-09-23T07:00:00Z", {mode: "demo"}),
  ev("e1", "verification.passed", STAMP, {verdict: "pass"}),
];
const before = projectEvents(mission(), log, 0);
const atFailure = projectEvents(mission(), log, 1);
cases.replayBefore = verificationAgeChip(before, {now: knownNow});
cases.replayAt = verificationAgeChip(atFailure, {now: knownNow});

console.log(JSON.stringify(cases));
