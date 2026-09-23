import {
  newState, applyEvent, lastVerificationView, projectEvents,
  NO_VERIFICATION, ROLE_UNAVAILABLE, SUMMARY_UNAVAILABLE,
} from "../app/static/state.mjs";

const MISSION = {id: "m1", goal: "Answer the question", status: "running", created_at: "2026-01-01T00:00:00Z"};
const EVIDENCE = "DO_NOT_SHOW_THIS_EVIDENCE_DUMP";

function event(id, type, payload, actor = "root") {
  return {id, event_type: type, actor_id: actor, payload, created_at: "2026-01-01T00:00:0" + String(id).slice(-1) + "Z"};
}

function spawn(state, id = "root", role = "mission_controller") {
  applyEvent(state, event("spawn-" + id, "agent.spawned", {id, role, status: "running"}, id));
}

function viewOf(state) {
  return lastVerificationView(state);
}

const cases = {};
cases.labels = {NO_VERIFICATION, ROLE_UNAVAILABLE, SUMMARY_UNAVAILABLE};

cases.idle = viewOf(newState());

const loaded = newState(MISSION);
cases.loaded = viewOf(loaded);

const started = newState(MISSION);
spawn(started);
applyEvent(started, event("s1", "verification.started", {summary: "The answer is 42", outputs: 1}));
cases.started = viewOf(started);

const passed = newState(MISSION);
spawn(passed);
applyEvent(passed, event("p1", "verification.passed", {
  verdict: "pass",
  rationale: "Grounded in the worker artifact.",
  evidence: [EVIDENCE],
  evidence_runs: [{detail: EVIDENCE, ok: true}],
}));
cases.passed = viewOf(passed);

const replaced = newState(MISSION);
spawn(replaced);
applyEvent(replaced, event("p1", "verification.passed", {verdict: "pass", rationale: "First pass"}));
applyEvent(replaced, event("f1", "verification.failed", {verdict: "fail", rationale: "Objective is unmet", failure_class: "VERIFICATION_FAILURE"}));
cases.replaced = viewOf(replaced);

const inconclusive = newState(MISSION);
spawn(inconclusive, "root", "mission_controller");
applyEvent(inconclusive, event("i1", "verification.failed", {verdict: "inconclusive", rationale: "Not enough evidence"}));
cases.inconclusive = viewOf(inconclusive);

const evidenceOnly = newState(MISSION);
spawn(evidenceOnly);
applyEvent(evidenceOnly, event("ev1", "verification.evidence.passed", {ok: true, kind: "pytest", detail: EVIDENCE}));
cases.evidenceOnly = viewOf(evidenceOnly);

const mismatch = newState(MISSION);
spawn(mismatch);
applyEvent(mismatch, event("p1", "verification.passed", {verdict: "pass", rationale: "First pass"}));
applyEvent(mismatch, event("bad", "verification.passed", {verdict: "fail", rationale: "Should not count as pass", evidence: [EVIDENCE]}));
cases.mismatchPass = viewOf(mismatch);

const mismatchFail = newState(MISSION);
spawn(mismatchFail);
applyEvent(mismatchFail, event("badf", "verification.failed", {verdict: "pass", rationale: "Event type disagrees"}));
cases.mismatchFail = viewOf(mismatchFail);

const missingSummary = newState(MISSION);
spawn(missingSummary);
applyEvent(missingSummary, event("ms", "verification.failed", {verdict: "fail", evidence: [EVIDENCE]}));
cases.missingSummary = viewOf(missingSummary);

const blankSummary = newState(MISSION);
spawn(blankSummary);
applyEvent(blankSummary, event("bs", "verification.passed", {verdict: "pass", rationale: "   \n  "}));
cases.blankSummary = viewOf(blankSummary);

const longText = "A".repeat(400) + " " + EVIDENCE;
const longSummary = newState(MISSION);
spawn(longSummary);
applyEvent(longSummary, event("ls", "verification.passed", {verdict: "pass", rationale: longText, evidence: [EVIDENCE]}));
cases.longSummary = viewOf(longSummary);

const preview = newState(MISSION);
preview.preview = true;
spawn(preview);
applyEvent(preview, event("pv", "verification.passed", {verdict: "pass", rationale: "Preview must not show this"}));
cases.preview = viewOf(preview);

const unknownActor = newState(MISSION);
applyEvent(unknownActor, event("ua", "verification.passed", {verdict: "pass", rationale: "Recorded without a role"}, "missing-agent"));
cases.unknownActor = viewOf(unknownActor);

const newlineRole = newState(MISSION);
spawn(newlineRole, "root", "bad\nrole dump");
applyEvent(newlineRole, event("nr", "verification.failed", {verdict: "fail", rationale: "Role was not a single recorded label"}));
cases.newlineRole = viewOf(newlineRole);

const duplicate = newState(MISSION);
spawn(duplicate);
applyEvent(duplicate, event("d1", "verification.passed", {verdict: "pass", rationale: "Kept"}));
applyEvent(duplicate, event("d1", "verification.failed", {verdict: "fail", rationale: "Ignored duplicate id"}));
cases.duplicate = viewOf(duplicate);

const restarted = newState(MISSION);
spawn(restarted);
applyEvent(restarted, event("r1", "verification.passed", {verdict: "pass", rationale: "Earlier pass"}));
applyEvent(restarted, event("r2", "verification.started", {summary: "Checking again"}));
cases.restarted = viewOf(restarted);

const log = [
  event("spawn-root", "agent.spawned", {id: "root", role: "mission_controller", status: "running"}),
  event("early", "verification.failed", {verdict: "fail", rationale: "Too early"}),
  event("late", "verification.passed", {verdict: "pass", rationale: "Later pass"}),
];
cases.replayBefore = viewOf(projectEvents(MISSION, log, 1));
cases.replayAfter = viewOf(projectEvents(MISSION, log, 2));

console.log(JSON.stringify(cases));
