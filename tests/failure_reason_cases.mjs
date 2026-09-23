import {
  newState, applyEvent, projectEvents, failureReasonView, FAILURE_REASON_EMPTY,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:0" + String(id).slice(-1) + "Z"};
}

function mission(extra = {}) {
  return {id: "m1", goal: "Ship the note", status: "running", result: null, pending_question: null, ...extra};
}

function withEvents(base, events) {
  const state = newState(base);
  for (const item of events) applyEvent(state, item);
  return state;
}

const cases = {};
cases.EMPTY = FAILURE_REASON_EMPTY;

cases.noMission = failureReasonView(newState());
cases.preview = failureReasonView(Object.assign(withEvents(mission(), [
  event("e1", "mission.failed", {error: "down", failure_class: "PROVIDER_OUTAGE"}),
]), {preview: true}));

cases.failed = failureReasonView(withEvents(mission(), [
  event("e1", "mission.running", {reason: "started"}),
  event("e2", "mission.failed", {error: "provider down", failure_class: "PROVIDER_OUTAGE"}),
]));

cases.failedClassOnly = failureReasonView(withEvents(mission(), [
  event("e1", "mission.failed", {failure_class: "TIMEOUT"}),
]));

cases.failedBlank = failureReasonView(withEvents(mission({status: "failed"}), [
  event("e1", "mission.failed", {failure_class: "  ", error: ""}),
]));

cases.numericClass = failureReasonView(withEvents(mission(), [
  event("e1", "mission.failed", {failure_class: 12, error: 0}),
]));

cases.approval = failureReasonView(withEvents(mission(), [
  event("e1", "mission.question", {
    question_id: "q1",
    question: "Approve completing this mission? Reply approve or deny.",
    reason: "Finish requires human approval",
    kind: "approval",
    approval_action: "finish",
  }),
  event("e2", "mission.waiting", {
    reason: "Finish requires human approval",
    question_id: "q1",
    question: "Approve completing this mission? Reply approve or deny.",
    kind: "approval",
    approval_action: "finish",
  }),
]));

cases.parkQuestion = failureReasonView(withEvents(mission(), [
  event("e1", "mission.question", {
    question_id: "q2",
    question: "Which region?",
    reason: "Need a region before continuing",
    kind: "question",
  }),
]));

cases.inflightWait = failureReasonView(withEvents(mission(), [
  event("e1", "mission.waiting", {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}),
]));

cases.blocked = failureReasonView(withEvents(mission(), [
  event("e1", "mission.blocked", {reason: "No browser is configured"}),
]));

cases.blockedMissing = failureReasonView(withEvents(mission({status: "blocked"}), [
  event("e1", "mission.blocked", {}),
]));

cases.taskBlockedFinding = failureReasonView(withEvents(mission(), [
  event("e1", "task.blocked", {output: {finding: "Needs a listed host"}}),
]));

cases.taskBlockedEmpty = failureReasonView(withEvents(mission(), [
  event("e1", "task.blocked", {description: "do the thing"}),
]));

cases.completedClears = failureReasonView(withEvents(mission(), [
  event("e1", "mission.failed", {error: "old", failure_class: "UNKNOWN_FAILURE"}),
  event("e2", "mission.completed", {summary: "done"}),
]));

cases.answerClearsPark = failureReasonView(withEvents(mission(), [
  event("e1", "mission.question", {
    question_id: "q1", question: "Approve?", reason: "Finish requires human approval",
    kind: "approval", approval_action: "finish",
  }),
  event("e2", "user.answered", {question_id: "q1", answer: "approve", kind: "approval"}),
]));

cases.runningClearsPark = failureReasonView(withEvents(mission(), [
  event("e1", "mission.waiting", {
    reason: "Live payment requires human approval", question_id: "q9",
    question: "Approve this live payment?", kind: "approval", approval_action: "live_payment",
  }),
  event("e2", "mission.running", {reason: "Human answer received; controller will continue"}),
]));

cases.retryThenSuccess = failureReasonView(withEvents(mission(), [
  event("e1", "llm.retry", {failure_class: "RATE_LIMIT", error: "slow down"}),
  event("e2", "llm.completed", {input_tokens: 1, output_tokens: 1}),
]));

cases.retryOpen = failureReasonView(withEvents(mission(), [
  event("e1", "llm.retry", {failure_class: "TIMEOUT", error: "timed out"}),
]));

cases.llmFailed = failureReasonView(withEvents(mission(), [
  event("e1", "llm.failed", {failure_class: "PROVIDER_OUTAGE", error: "connect failed"}),
]));

cases.verification = failureReasonView(withEvents(mission(), [
  event("e1", "verification.failed", {failure_class: "VERIFICATION_FAILURE", rationale: "tests failed"}),
]));

cases.verificationPassedClears = failureReasonView(withEvents(mission(), [
  event("e1", "verification.failed", {failure_class: "VERIFICATION_FAILURE", rationale: "nope"}),
  event("e2", "verification.passed", {verdict: "pass"}),
]));

cases.stopped = failureReasonView(withEvents(mission({status: "stopped"}), [
  event("e1", "mission.stopped", {reason: "Execution stopped"}),
]));

cases.snapshotFailure = failureReasonView(newState(mission({
  status: "failed",
  result: {error: "Mission runtime limit reached", failure_class: "TIMEOUT"},
})));

cases.snapshotBlocked = failureReasonView(newState(mission({
  status: "blocked",
  result: {reason: "Required capability or information is unavailable"},
})));

cases.snapshotApproval = failureReasonView(newState(mission({
  status: "waiting",
  pending_question: {
    question_id: "q1",
    question: "Approve organization change 'retire'? Reply approve or deny.",
    reason: "Organization retire requires human approval",
    kind: "approval",
    approval_action: "org_change",
  },
})));

cases.snapshotEmpty = failureReasonView(newState(mission({status: "failed", result: {}})));

cases.eventsIgnoreStaleResult = failureReasonView(withEvents(mission({
  status: "failed",
  result: {error: "stale", failure_class: "MODEL_FAILURE"},
}), [
  event("e1", "mission.completed", {summary: "actually done"}),
]));

const replayMission = mission({created_at: "2026-01-01T00:00:00Z"});
const replayLog = [
  event("r1", "mission.started", {mode: "openai"}),
  event("r2", "mission.failed", {error: "down", failure_class: "PROVIDER_OUTAGE"}),
];
cases.replayBefore = failureReasonView(projectEvents(replayMission, replayLog, 0));
cases.replayAtFailure = failureReasonView(projectEvents(replayMission, replayLog, 1));

console.log(JSON.stringify(cases));
