import {
  recordedQuestionFeed, questionCountView, QUESTION_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-09-23T12:35:04Z"};
}

const question = (id, extra = {}) => event(id, "mission.question", {
  question_id: id, question: "Need a decision", ...extra,
});
const log = [
  event("w1", "mission.waiting", {reason: "ask"}),
  question("q1"),
  event("a1", "user.answered", {question_id: "q1", answer: "yes"}),
  event("c1", "user.answer_consumed", {question_id: "q1"}),
  question("q2", {kind: "approval", question: "Approve the next step?"}),
  event("p1", "mission.paused"),
  event("t1", "tool.completed", {name: "search", question: "not a mission question"}),
  question("q3"),
];

const cases = {};
cases.unavailable = QUESTION_COUNT_UNAVAILABLE;
cases.hidden = questionCountView(log, {visible: false});
cases.hiddenDefault = questionCountView(log);
cases.preview = questionCountView(log, {visible: false});
cases.missingNull = questionCountView(null, {visible: true});
cases.missingUndefined = questionCountView(undefined, {visible: true});
cases.missingObject = questionCountView({questions: 4, pending_question: {question: "hi"}, events: []}, {visible: true});
cases.empty = questionCountView([], {visible: true});
cases.counted = questionCountView(log, {visible: true});
cases.ignoresAnswered = questionCountView([
  event("answered", "user.answered", {question_id: "q", answer: "yes", questions: 4}),
], {visible: true});
cases.ignoresConsumed = questionCountView([
  event("consumed", "user.answer_consumed", {question_id: "q", questions: 2}),
], {visible: true});
cases.ignoresWaiting = questionCountView([
  event("wait", "mission.waiting", {pending_question: {question: "Still waiting?"}, questions: 1}),
], {visible: true});
cases.ignoresPaused = questionCountView([
  event("pause", "mission.paused", {question: "Paused for review"}),
], {visible: true});
cases.ignoresUnrelated = questionCountView([
  event("tool", "tool.completed", {name: "search", question: "What happened?"}),
], {visible: true});
cases.oneQuestionNotText = questionCountView([
  question("long", {question: "Should we spend the budget?", kind: "approval"}),
], {visible: true});
cases.skipsHoles = questionCountView([null, {payload: {question: "hole"}}, question("one")], {visible: true});
cases.unreadableType = questionCountView([
  question("ok"),
  {id: "bad", event_type: 4, payload: {question: "bad"}},
], {visible: true});
cases.missingType = questionCountView([
  {id: "blank", payload: {question: "missing type"}},
  question("one"),
], {visible: true});
cases.prefix = questionCountView(recordedQuestionFeed(log, 1, true), {visible: true});
cases.prefixFirst = questionCountView(recordedQuestionFeed(log, 0, true), {visible: true});
cases.prefixTwo = questionCountView(recordedQuestionFeed(log, 4, true), {visible: true});
cases.prefixAll = questionCountView(recordedQuestionFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = questionCountView(recordedQuestionFeed(log, -1, true), {visible: true});
cases.unloaded = recordedQuestionFeed(log, log.length - 1, false);
cases.unloadedView = questionCountView(recordedQuestionFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedQuestionFeed([], -1, true);
cases.notArrayLog = recordedQuestionFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
