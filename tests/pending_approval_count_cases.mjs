import {
  applyEvent, newState, pendingApprovalCountView, projectEvents,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

const mission = {
  id: "m1",
  goal: "Ship the readout",
  created_at: "2026-01-01T00:00:00Z",
  pending_question: null,
};

const cases = {};

cases.noMission = pendingApprovalCountView(newState());
cases.preview = pendingApprovalCountView({
  preview: true,
  mission: {
    ...mission,
    pending_question: {question_id: "q-org", question: "Approve?", kind: "approval", approval_action: "org_change"},
  },
});
cases.explicitNull = pendingApprovalCountView({preview: false, mission: {...mission, pending_question: null}});
cases.humanQuestion = pendingApprovalCountView({
  preview: false,
  mission: {
    ...mission,
    pending_question: {question_id: "q-ask", question: "Which name?", kind: "question"},
  },
});
cases.orgApproval = pendingApprovalCountView({
  preview: false,
  mission: {
    ...mission,
    pending_question: {
      question_id: "q-org",
      question: "Approve organization change 'retire'?",
      kind: "approval",
      approval_action: "org_change",
    },
  },
});
cases.finishApproval = pendingApprovalCountView({
  preview: false,
  mission: {
    ...mission,
    pending_question: {question_id: "q-fin", question: "Approve finish?", kind: "approval", approval_action: "finish"},
  },
});
cases.paymentApproval = pendingApprovalCountView({
  preview: false,
  mission: {
    ...mission,
    pending_question: {question_id: "q-pay", question: "Approve payment?", kind: "approval", approval_action: "live_payment"},
  },
});
cases.missingField = pendingApprovalCountView({preview: false, mission: {id: "m1", goal: "Ship the readout"}});
cases.missingKind = pendingApprovalCountView({
  preview: false,
  mission: {...mission, pending_question: {question_id: "q-x", question: "Approve?"}},
});
cases.blankApprovalId = pendingApprovalCountView({
  preview: false,
  mission: {...mission, pending_question: {question_id: "  ", question: "Approve?", kind: "approval"}},
});
cases.unknownKind = pendingApprovalCountView({
  preview: false,
  mission: {...mission, pending_question: {question_id: "q-x", kind: "maybe"}},
});
cases.orgOpWithoutKind = pendingApprovalCountView({
  preview: false,
  mission: {...mission, pending_question: {question_id: "q-x", org_op: "retire"}},
});
cases.answeredHistoryIsNotPending = pendingApprovalCountView({
  preview: false,
  mission: {
    ...mission,
    pending_question: null,
    answers: [{question_id: "q-old", kind: "approval", approval_action: "org_change", answer: "approve"}],
  },
});

const parked = newState({...mission});
applyEvent(parked, event("e1", "mission.question", {
  question_id: "q-org",
  question: "Approve organization change 'retire'?",
  kind: "approval",
  approval_action: "org_change",
}));
cases.afterQuestionEvent = pendingApprovalCountView(parked);

const cleared = newState({...mission});
applyEvent(cleared, event("e1", "mission.question", {
  question_id: "q-org", question: "Approve?", kind: "approval", approval_action: "org_change",
}));
applyEvent(cleared, event("e2", "user.answered", {question_id: "q-org", answer: "approve"}));
cases.afterAnswer = pendingApprovalCountView(cleared);

const replaced = newState({...mission});
applyEvent(replaced, event("e1", "mission.question", {
  question_id: "q-a", question: "Approve retire?", kind: "approval", approval_action: "org_change",
}));
applyEvent(replaced, event("e2", "user.answered", {question_id: "q-a"}));
applyEvent(replaced, event("e3", "mission.question", {
  question_id: "q-b", question: "Approve finish?", kind: "approval", approval_action: "finish",
}));
cases.secondApprovalIsStillOne = pendingApprovalCountView(replaced);

const unclassified = newState({...mission});
applyEvent(unclassified, event("e1", "mission.question", {question_id: "q-raw", question: "Approve?"}));
cases.questionEventWithoutKind = pendingApprovalCountView(unclassified);

const waitingWork = newState({...mission, pending_question: null});
applyEvent(waitingWork, event("e1", "mission.waiting", {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}));
cases.inFlightWaitIsZero = pendingApprovalCountView(waitingWork);

const projected = projectEvents(mission, [
  event("e1", "mission.question", {
    question_id: "q-org", question: "Approve retire?", kind: "approval", approval_action: "org_change",
  }),
], 0);
cases.projectedApproval = pendingApprovalCountView(projected);

const projectedClear = projectEvents(mission, [
  event("e1", "mission.question", {
    question_id: "q-org", question: "Approve retire?", kind: "approval", approval_action: "org_change",
  }),
  event("e2", "user.answered", {question_id: "q-org"}),
], 1);
cases.projectedAnswered = pendingApprovalCountView(projectedClear);

const projectedAsk = projectEvents(mission, [
  event("e1", "mission.question", {question_id: "q-ask", question: "Which name?", kind: "question"}),
], 0);
cases.projectedQuestion = pendingApprovalCountView(projectedAsk);

cases.emptyProjection = pendingApprovalCountView(projectEvents(mission, [], null));

process.stdout.write(JSON.stringify(cases));
