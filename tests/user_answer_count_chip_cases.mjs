import {
  recordedUserAnswerFeed, userAnswerCountView, USER_ANSWER_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const answered = (id, extra = {}) => event(id, "user.answered", {question_id: "q1", answer: "yes", ...extra});
const log = [
  event("q0", "mission.question", {question_id: "q1", question: "Proceed?"}),
  answered("a1"),
  event("c1", "user.answer_consumed", {question_id: "q1"}),
  event("w1", "mission.waiting", {reason: "question"}),
  answered("a2"),
  event("r1", "mission.resumed"),
  event("t1", "tool.completed", {name: "search"}),
  event("l1", "llm.completed", {output_tokens: 4}),
  event("m1", "mission.completed", {summary: "done"}),
  answered("a3", {answers: 9, token_spent: 2}),
];

const cases = {};
cases.unavailable = USER_ANSWER_UNAVAILABLE;
cases.hidden = userAnswerCountView(log, {visible: false});
cases.hiddenDefault = userAnswerCountView(log);
cases.preview = userAnswerCountView(log, {visible: false});
cases.missingNull = userAnswerCountView(null, {visible: true});
cases.missingUndefined = userAnswerCountView(undefined, {visible: true});
cases.missingObject = userAnswerCountView({answers: 4, events: []}, {visible: true});
cases.empty = userAnswerCountView([], {visible: true});
cases.counted = userAnswerCountView(log, {visible: true});
cases.ignoresQuestion = userAnswerCountView([
  event("q", "mission.question", {answers: 2}),
], {visible: true});
cases.ignoresConsumed = userAnswerCountView([
  event("c", "user.answer_consumed", {answers: 3}),
], {visible: true});
cases.ignoresWaiting = userAnswerCountView([
  event("w", "mission.waiting", {answers: 1}),
], {visible: true});
cases.ignoresTool = userAnswerCountView([
  event("tool", "tool.completed", {name: "search", answers: 5}),
], {visible: true});
cases.ignoresLlm = userAnswerCountView([
  event("llm", "llm.completed", {answers: 6}),
], {visible: true});
cases.ignoresMissionCompleted = userAnswerCountView([
  event("done", "mission.completed", {answers: 1}),
], {visible: true});
cases.oneAnswerNotPayload = userAnswerCountView([
  answered("big", {answers: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = userAnswerCountView([null, {payload: {answers: 10}}, answered("one")], {visible: true});
cases.unreadableType = userAnswerCountView([
  answered("ok"),
  {id: "bad", event_type: 4, payload: {answers: 1}},
], {visible: true});
cases.missingType = userAnswerCountView([
  {id: "blank", payload: {answers: 7}},
  answered("one"),
], {visible: true});
cases.prefix = userAnswerCountView(recordedUserAnswerFeed(log, 1, true), {visible: true});
cases.prefixFirst = userAnswerCountView(recordedUserAnswerFeed(log, 0, true), {visible: true});
cases.prefixOne = userAnswerCountView(recordedUserAnswerFeed(log, 4, true), {visible: true});
cases.prefixAll = userAnswerCountView(recordedUserAnswerFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = userAnswerCountView(recordedUserAnswerFeed(log, -1, true), {visible: true});
cases.unloaded = recordedUserAnswerFeed(log, log.length - 1, false);
cases.unloadedView = userAnswerCountView(recordedUserAnswerFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedUserAnswerFeed([], -1, true);
cases.notArrayLog = recordedUserAnswerFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
