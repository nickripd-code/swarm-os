import {applyEvent, errorParkSnippet, newState} from "../app/static/state.mjs";

function mission(extra = {}) {
  return {id: "m1", goal: "Ship the launch", status: "pending", ...extra};
}

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-09-23T00:00:00Z"};
}

function project(base, events = [], preview = false) {
  const state = newState(base);
  state.preview = preview;
  for (const item of events) applyEvent(state, item);
  return errorParkSnippet(state);
}

const cases = {};

cases.noMission = errorParkSnippet(newState(null));
cases.noState = errorParkSnippet(null);

cases.previewFailed = project(mission({
  status: "failed",
  result: {error: "provider down", failure_class: "PROVIDER_OUTAGE"},
}), [], true);

cases.loadedFailed = errorParkSnippet(newState(mission({
  status: "failed",
  result: {error: "Mission runtime limit reached", failure_class: "TIMEOUT"},
})));

cases.failedEvent = project(mission(), [
  event("e1", "mission.failed", {error: "provider down", failure_class: "PROVIDER_OUTAGE"}),
]);

cases.classOnly = errorParkSnippet(newState(mission({
  status: "failed",
  result: {failure_class: "POLICY_REFUSAL"},
})));

cases.errorOnly = errorParkSnippet(newState(mission({
  status: "failed",
  result: {error: "Unexpected runtime error"},
})));

cases.reasonOnlyFailed = errorParkSnippet(newState(mission({
  status: "failed",
  result: {reason: "Verification did not accept the claimed result"},
})));

cases.blankFailed = errorParkSnippet(newState(mission({
  status: "failed",
  result: {error: "  ", failure_class: "", reason: "\n"},
})));

cases.numericFailed = errorParkSnippet(newState(mission({
  status: "failed",
  result: {error: 0, failure_class: 12, reason: false},
})));

cases.summaryIsNotReason = errorParkSnippet(newState(mission({
  status: "failed",
  result: {summary: "Looks done"},
})));

cases.runningIgnoresError = errorParkSnippet(newState(mission({
  status: "running",
  result: {error: "stale", failure_class: "MODEL_FAILURE"},
})));

cases.loadedPark = errorParkSnippet(newState(mission({
  status: "waiting",
  pending_question: {
    question_id: "q1",
    question: "Approve finish?",
    reason: "Finish requires human approval",
    kind: "approval",
    approval_action: "finish",
  },
})));

cases.questionWithoutReason = errorParkSnippet(newState(mission({
  status: "waiting",
  pending_question: {question_id: "q1", question: "Which region?", reason: null},
})));

cases.missingParkReason = errorParkSnippet(newState(mission({status: "waiting"})));

cases.whitespacePark = errorParkSnippet(newState(mission({
  status: "waiting",
  pending_question: {question: "Which region?", reason: "   "},
})));

cases.waitingEvent = project(mission(), [
  event("e1", "mission.waiting", {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}),
]);

cases.blankWaiting = project(mission(), [
  event("e1", "mission.waiting", {reason: "  ", pending_tasks: ["t1"]}),
]);

cases.runningClearsPark = project(mission(), [
  event("e1", "mission.waiting", {reason: "Waiting for in-flight work"}),
  event("e2", "mission.running", {reason: "In-flight work finished; controller will continue"}),
]);

cases.questionClearsOlderPark = project(mission(), [
  event("e1", "mission.waiting", {reason: "Waiting for in-flight work"}),
  event("e2", "mission.question", {question_id: "q2", question: "Need a region", reason: "  "}),
]);

cases.blockedHidden = errorParkSnippet(newState(mission({
  status: "blocked",
  result: {reason: "No browser is configured"},
})));

cases.stoppedHidden = errorParkSnippet(newState(mission({
  status: "stopped",
  result: {reason: "Execution stopped"},
})));

cases.completedHidden = errorParkSnippet(newState(mission({
  status: "completed",
  result: {summary: "Done", reason: "Done"},
})));

cases.pausedHidden = errorParkSnippet(newState(mission({status: "paused"})));

const inconsistentFailed = newState(mission({
  status: "failed",
  result: {error: "stale", failure_class: "MODEL_FAILURE"},
}));
inconsistentFailed.events = [event("e1", "mission.running", {reason: "continue"})];
cases.inconsistentFailed = errorParkSnippet(inconsistentFailed);

const inconsistentPark = newState(mission({
  status: "waiting",
  pending_question: {question: "Approve?", reason: "Finish requires human approval"},
}));
inconsistentPark.events = [event("e1", "mission.running", {reason: "continue"})];
cases.inconsistentPark = errorParkSnippet(inconsistentPark);

cases.failedPayloadNotStaleResult = project(mission({
  result: {error: "stale", failure_class: "MODEL_FAILURE"},
}), [
  event("e1", "mission.failed", {error: "provider down", failure_class: "PROVIDER_OUTAGE"}),
]);

cases.emptyFailedPayload = project(mission({
  result: {error: "stale", failure_class: "MODEL_FAILURE"},
}), [
  event("e1", "mission.failed", {error: "", failure_class: "  "}),
]);

cases.recordedFallbackIsShown = project(mission(), [
  event("e1", "mission.waiting", {reason: "Waiting for a human answer", question_id: "q9"}),
]);

console.log(JSON.stringify(cases));
