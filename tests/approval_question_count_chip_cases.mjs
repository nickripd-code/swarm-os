import {
  recordedApprovalQuestionFeed, approvalQuestionCountView, APPROVAL_QUESTION_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-09-23T12:35:04Z"};
}

const question = (id, extra = {}) => event(id, "mission.question", {
  question_id: id, question: "Need a decision", kind: "question", ...extra,
});
const approval = (id, extra = {}) => event(id, "mission.question", {
  question_id: id, question: "Approve the next step?", kind: "approval", approval_action: "finish", ...extra,
});
const log = [
  event("w1", "mission.waiting", {reason: "ask", kind: "approval", question_id: "a1"}),
  question("q1"),
  approval("a1"),
  event("ans1", "user.answered", {question_id: "a1", answer: "approve", kind: "approval"}),
  event("c1", "user.answer_consumed", {question_id: "a1", kind: "approval"}),
  approval("a2"),
  event("p1", "mission.paused"),
  event("t1", "tool.completed", {name: "search", kind: "approval", question: "not a mission question"}),
  question("q3", {kind: undefined}),
];

const cases = {};
cases.unavailable = APPROVAL_QUESTION_COUNT_UNAVAILABLE;
cases.hidden = approvalQuestionCountView(log, {visible: false});
cases.hiddenDefault = approvalQuestionCountView(log);
cases.preview = approvalQuestionCountView(log, {visible: false});
cases.missingNull = approvalQuestionCountView(null, {visible: true});
cases.missingUndefined = approvalQuestionCountView(undefined, {visible: true});
cases.missingObject = approvalQuestionCountView({
  questions: 4, pending_question: {question: "hi", kind: "approval"}, events: [],
}, {visible: true});
cases.empty = approvalQuestionCountView([], {visible: true});
cases.counted = approvalQuestionCountView(log, {visible: true});
cases.plainQuestions = approvalQuestionCountView([
  question("only"),
  question("also", {question: "Should we spend the budget?"}),
], {visible: true});
cases.missingKind = approvalQuestionCountView([
  event("blank-kind", "mission.question", {question_id: "q", question: "Which name?"}),
], {visible: true});
cases.nullPayload = approvalQuestionCountView([
  {id: "no-payload", event_type: "mission.question", payload: null},
], {visible: true});
cases.ignoresAnswered = approvalQuestionCountView([
  event("answered", "user.answered", {question_id: "q", answer: "approve", kind: "approval", questions: 4}),
], {visible: true});
cases.ignoresConsumed = approvalQuestionCountView([
  event("consumed", "user.answer_consumed", {question_id: "q", kind: "approval", questions: 2}),
], {visible: true});
cases.ignoresWaiting = approvalQuestionCountView([
  event("wait", "mission.waiting", {kind: "approval", pending_question: {question: "Still waiting?"}, questions: 1}),
], {visible: true});
cases.ignoresPaused = approvalQuestionCountView([
  event("pause", "mission.paused", {question: "Paused for review", kind: "approval"}),
], {visible: true});
cases.ignoresUnrelated = approvalQuestionCountView([
  event("tool", "tool.completed", {name: "search", kind: "approval", question: "What happened?"}),
], {visible: true});
cases.oneApprovalNotText = approvalQuestionCountView([
  approval("long", {question: "Should we spend the budget?"}),
], {visible: true});
cases.otherKind = approvalQuestionCountView([
  question("maybe", {kind: "maybe"}),
  approval("real"),
], {visible: true});
cases.caseMismatch = approvalQuestionCountView([
  question("cap", {kind: "Approval"}),
], {visible: true});
cases.skipsHoles = approvalQuestionCountView([
  null, {payload: {question: "hole", kind: "approval"}}, approval("one"),
], {visible: true});
cases.unreadableType = approvalQuestionCountView([
  approval("ok"),
  {id: "bad", event_type: 4, payload: {kind: "approval", question: "bad"}},
], {visible: true});
cases.unreadableKind = approvalQuestionCountView([
  approval("ok"),
  event("bad-kind", "mission.question", {question_id: "bad", kind: 4, question: "bad"}),
], {visible: true});
cases.unreadablePayload = approvalQuestionCountView([
  approval("ok"),
  {id: "bad-payload", event_type: "mission.question", payload: "approval"},
], {visible: true});
cases.missingType = approvalQuestionCountView([
  {id: "blank", payload: {question: "missing type", kind: "approval"}},
  approval("one"),
], {visible: true});
cases.prefix = approvalQuestionCountView(recordedApprovalQuestionFeed(log, 2, true), {visible: true});
cases.prefixFirst = approvalQuestionCountView(recordedApprovalQuestionFeed(log, 0, true), {visible: true});
cases.prefixTwo = approvalQuestionCountView(recordedApprovalQuestionFeed(log, 5, true), {visible: true});
cases.prefixAll = approvalQuestionCountView(recordedApprovalQuestionFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = approvalQuestionCountView(recordedApprovalQuestionFeed(log, -1, true), {visible: true});
cases.unloaded = recordedApprovalQuestionFeed(log, log.length - 1, false);
cases.unloadedView = approvalQuestionCountView(recordedApprovalQuestionFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedApprovalQuestionFeed([], -1, true);
cases.notArrayLog = recordedApprovalQuestionFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
