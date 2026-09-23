import {
  newState, applyEvent, projectEvents, failureClassChip, knownFailureClasses, FAILURE_CLASS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

function mission(status, result = null) {
  return {id: "m1", goal: "Ship the seed", status, created_at: "2026-01-01T00:00:00Z", result};
}

const cases = {classes: knownFailureClasses(), unavailable: FAILURE_CLASS_UNAVAILABLE};

cases.noMission = failureClassChip(newState());
cases.preview = failureClassChip({
  ...newState(mission("failed", {error: "down", failure_class: "TIMEOUT"})),
  preview: true,
});
cases.running = failureClassChip(newState(mission("running", {failure_class: "TIMEOUT"})));
cases.completed = failureClassChip(newState(mission("completed", {summary: "done", failure_class: "TIMEOUT"})));
cases.stopped = failureClassChip(newState(mission("stopped", {reason: "stop", failure_class: "TIMEOUT"})));
cases.blocked = failureClassChip(newState(mission("blocked", {reason: "missing", failure_class: "TOOL_MISSING"})));
cases.waiting = failureClassChip(newState(mission("waiting", {failure_class: "AUTHORIZATION_REQUIRED"})));
cases.paused = failureClassChip(newState(mission("paused")));
cases.known = failureClassChip(newState(mission("failed", {error: "slow", failure_class: "TIMEOUT"})));
cases.unknownRecorded = failureClassChip(newState(mission("failed", {error: "boom", failure_class: "UNKNOWN_FAILURE"})));
cases.missingResult = failureClassChip(newState(mission("failed", null)));
cases.emptyResult = failureClassChip(newState(mission("failed", {})));
cases.nullClass = failureClassChip(newState(mission("failed", {error: "down", failure_class: null})));
cases.blankClass = failureClassChip(newState(mission("failed", {error: "down", failure_class: ""})));
cases.paddedClass = failureClassChip(newState(mission("failed", {error: "down", failure_class: " TIMEOUT "})));
cases.lowerClass = failureClassChip(newState(mission("failed", {error: "timeout", failure_class: "timeout"})));
cases.inventedClass = failureClassChip(newState(mission("failed", {error: "timeout", failure_class: "NOT_A_CLASS"})));
cases.errorOnly = failureClassChip(newState(mission("failed", {error: "timeout"})));

const fromEvent = newState(mission("running"));
applyEvent(fromEvent, event("f1", "mission.failed", {error: "down", failure_class: "PROVIDER_OUTAGE"}));
cases.fromEvent = failureClassChip(fromEvent);

const eventMissing = newState(mission("running"));
applyEvent(eventMissing, event("f2", "mission.failed", {error: "down"}));
cases.eventMissing = failureClassChip(eventMissing);

const parked = newState(mission("running"));
applyEvent(parked, event("q1", "mission.question", {question_id: "q", question: "Approve?", kind: "approval"}));
cases.parked = failureClassChip(parked);

const log = [
  event("s", "mission.started", {mode: "live"}),
  event("f", "mission.failed", {error: "down", failure_class: "RATE_LIMIT"}),
];
const loaded = mission("failed", {error: "down", failure_class: "RATE_LIMIT"});
cases.replayBefore = failureClassChip(projectEvents(loaded, log, 0));
cases.replayAtFailure = failureClassChip(projectEvents(loaded, log, 1));

console.log(JSON.stringify(cases));
