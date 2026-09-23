import {
  applyEvent, newState, projectEvents, verificationStatusChip, VERIFICATION_UNAVAILABLE,
} from "../app/static/state.mjs";

function mission(extra = {}) {
  return {id: "m1", goal: "ship the note", status: "running", created_at: "2026-01-01T00:00:00Z", ...extra};
}

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:01Z"};
}

function chip(events, options = {}) {
  const state = newState(options.mission === undefined ? mission() : options.mission);
  if (options.preview) state.preview = true;
  for (const item of events) applyEvent(state, item);
  return verificationStatusChip(state);
}

const log = [
  event("e1", "mission.started", {mode: "openai"}),
  event("e2", "verification.started", {summary: "claim"}),
  event("e3", "verification.evidence.passed", {kind: "pytest", ok: true, detail: "1 passed"}),
  event("e4", "verification.passed", {verdict: "pass", rationale: "grounded", evidence: ["note"]}),
];

const cases = {
  noMission: verificationStatusChip(newState(null)),
  missingState: verificationStatusChip(undefined),
  preview: chip([
    event("e1", "verification.passed", {verdict: "pass", rationale: "grounded", evidence: []}),
  ], {preview: true}),
  noVerification: chip([]),
  completedWithoutVerification: chip([], {mission: mission({status: "completed", result: {summary: "done"}})}),
  started: chip([event("e1", "verification.started", {summary: "claim", verdict: "pass"})]),
  pass: chip([
    event("e1", "verification.started", {summary: "claim"}),
    event("e2", "verification.passed", {verdict: "pass", rationale: "grounded", evidence: ["note"]}),
  ]),
  fail: chip([
    event("e1", "verification.started", {}),
    event("e2", "verification.failed", {verdict: "fail", rationale: "empty claim", failure_class: "VERIFICATION_FAILURE"}),
  ]),
  inconclusive: chip([
    event("e1", "verification.failed", {verdict: "inconclusive", rationale: "not enough evidence"}),
  ]),
  missingVerdict: chip([event("e1", "verification.passed", {rationale: "grounded"})]),
  nullPayload: chip([event("e1", "verification.failed", null)]),
  listPayload: chip([event("e1", "verification.passed", [])]),
  wrongCase: chip([event("e1", "verification.passed", {verdict: "PASS"})]),
  spaced: chip([event("e1", "verification.failed", {verdict: " fail"})]),
  numericVerdict: chip([event("e1", "verification.failed", {verdict: 0})]),
  passOnFailed: chip([event("e1", "verification.failed", {verdict: "pass"})]),
  failOnPassed: chip([event("e1", "verification.passed", {verdict: "fail"})]),
  pendingVerdictOnFailed: chip([event("e1", "verification.failed", {verdict: "pending"})]),
  evidenceOnly: chip([
    event("e1", "verification.evidence.passed", {kind: "file", ok: true, detail: "hash matched", verdict: "pass"}),
  ]),
  evidenceDoesNotUpgradePending: chip([
    event("e1", "verification.started", {summary: "claim"}),
    event("e2", "verification.evidence.passed", {kind: "pytest", ok: true, detail: "1 passed"}),
  ]),
  evidenceDoesNotDowngradePass: chip([
    event("e1", "verification.passed", {verdict: "pass", rationale: "grounded", evidence: []}),
    event("e2", "verification.evidence.failed", {kind: "http", ok: false, detail: "500"}),
  ]),
  lastStartedClearsPass: chip([
    event("e1", "verification.passed", {verdict: "pass", rationale: "grounded", evidence: []}),
    event("e2", "verification.started", {summary: "again"}),
  ]),
  lastPassReplacesFail: chip([
    event("e1", "verification.failed", {verdict: "fail", rationale: "no"}),
    event("e2", "verification.passed", {verdict: "pass", rationale: "yes", evidence: []}),
  ]),
  llmKindIsNotAVerdict: chip([
    event("e1", "llm.started", {kind: "verification"}),
  ]),
  duplicateDoesNotReplace: chip([
    event("e1", "verification.passed", {verdict: "pass", rationale: "grounded", evidence: []}),
    {...event("e1", "verification.failed", {verdict: "fail", rationale: "no"}), id: "e1"},
  ]),
  replayBefore: verificationStatusChip(projectEvents(mission(), log, 0)),
  replayPending: verificationStatusChip(projectEvents(mission(), log, 1)),
  replayEvidenceStaysPending: verificationStatusChip(projectEvents(mission(), log, 2)),
  replayPass: verificationStatusChip(projectEvents(mission(), log, 3)),
  unavailable: VERIFICATION_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
