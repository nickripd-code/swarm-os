import {
  QUESTIONS_UNAVAILABLE, pendingQuestionCountView, applyEvent, newState, projectEvents,
} from "../app/static/state.mjs";

const cases = {};
const mission = {id: "m1", goal: "Name a thing", status: "running", pending_question: null};
const readable = {question_id: "q1", question: "Which name?", kind: "question"};

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "root", payload, created_at: "2026-01-01T00:00:00Z"};
}

cases.unavailable = QUESTIONS_UNAVAILABLE;
cases.hidden = pendingQuestionCountView(null);
cases.hiddenDefault = pendingQuestionCountView(undefined, {});
cases.hiddenPreview = pendingQuestionCountView({
  ...mission,
  pending_question: readable,
}, {preview: true});
cases.none = pendingQuestionCountView(mission);
cases.missingKey = pendingQuestionCountView({id: "m1", goal: "Name a thing", status: "running"});
cases.one = pendingQuestionCountView({...mission, status: "waiting", pending_question: readable});
cases.approval = pendingQuestionCountView({
  ...mission,
  status: "waiting",
  pending_question: {
    question_id: "q-a",
    question: "Approve finish?",
    kind: "approval",
    approval_action: "finish",
  },
});
cases.blank = pendingQuestionCountView({
  ...mission,
  pending_question: {question_id: "q1", question: "   "},
});
cases.blankId = pendingQuestionCountView({
  ...mission,
  pending_question: {question_id: "  ", question: "Which name?"},
});
cases.missingText = pendingQuestionCountView({
  ...mission,
  pending_question: {question_id: "q1"},
});
cases.missingId = pendingQuestionCountView({
  ...mission,
  pending_question: {question: "Which name?"},
});
cases.number = pendingQuestionCountView({...mission, pending_question: 1});
cases.stringField = pendingQuestionCountView({...mission, pending_question: "Which name?"});
cases.boolField = pendingQuestionCountView({...mission, pending_question: true});
cases.emptyObject = pendingQuestionCountView({...mission, pending_question: {}});
cases.array = pendingQuestionCountView({
  ...mission,
  pending_question: [
    {question_id: "q1", question: "A?"},
    {question_id: "q2", question: "B?"},
  ],
});
cases.answersIgnored = pendingQuestionCountView({
  ...mission,
  answers: [{question_id: "old", question: "Old?", answer: "yes"}],
});

const asked = newState({id: "m1", goal: "Name a thing", pending_question: null});
applyEvent(asked, event(1, "mission.question", {question_id: "q-live", question: "Need a domain?"}));
cases.afterQuestion = pendingQuestionCountView(asked.mission);

const answered = newState({
  id: "m1",
  goal: "Name a thing",
  pending_question: {question_id: "q-live", question: "Need a domain?"},
});
applyEvent(answered, event(2, "user.answered", {question_id: "q-live", answer: "example.com"}));
cases.afterAnswer = pendingQuestionCountView(answered.mission);

const mismatch = newState({
  id: "m1",
  goal: "Name a thing",
  pending_question: {question_id: "q-live", question: "Need a domain?"},
});
applyEvent(mismatch, event(5, "user.answered", {question_id: "other", answer: "no"}));
cases.mismatchKeeps = pendingQuestionCountView(mismatch.mission);

const chatter = newState({id: "m1", goal: "Name a thing", pending_question: null});
applyEvent(chatter, event(3, "agent.message", {kind: "question", text: "Which customer?"}));
cases.agentMessage = pendingQuestionCountView(chatter.mission);

const bad = newState({id: "m1", goal: "Name a thing", pending_question: null});
applyEvent(bad, event(4, "mission.question", {question_id: "q-bad"}));
cases.unreadableEvent = pendingQuestionCountView(bad.mission);

const log = [
  event(1, "mission.started", {mode: "live"}),
  event(2, "mission.question", {question_id: "q-replay", question: "Before the answer?"}),
  event(3, "user.answered", {question_id: "q-replay", answer: "yes"}),
];
const source = {id: "m1", goal: "Name a thing", created_at: "2026-01-01T00:00:00Z"};
cases.replayBefore = pendingQuestionCountView(projectEvents(source, log, 0).mission);
cases.replayOpen = pendingQuestionCountView(projectEvents(source, log, 1).mission);
cases.replayAnswered = pendingQuestionCountView(projectEvents(source, log, 2).mission);

console.log(JSON.stringify(cases));
