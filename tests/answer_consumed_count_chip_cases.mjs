import {
  recordedAnswerConsumedFeed, answerConsumedCountView, ANSWER_CONSUMED_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const consumed = (id, extra = {}) => event(id, "user.answer_consumed", {question_id: "q1", ...extra});
const log = [
  event("q0", "mission.question", {question_id: "q1", question: "Proceed?", kind: "approval"}),
  event("a1", "user.answered", {question_id: "q1", answer: "yes"}),
  consumed("c1"),
  event("w1", "mission.waiting", {reason: "question"}),
  event("a2", "user.answered", {question_id: "q2", answer: "no"}),
  consumed("c2"),
  event("r1", "mission.resumed"),
  event("t1", "tool.completed", {name: "search"}),
  event("l1", "llm.completed", {output_tokens: 4}),
  event("m1", "mission.completed", {summary: "done"}),
  consumed("c3", {answers: 9, token_spent: 2}),
];

const cases = {};
cases.unavailable = ANSWER_CONSUMED_UNAVAILABLE;
cases.hidden = answerConsumedCountView(log, {visible: false});
cases.hiddenDefault = answerConsumedCountView(log);
cases.preview = answerConsumedCountView(log, {visible: false});
cases.missingNull = answerConsumedCountView(null, {visible: true});
cases.missingUndefined = answerConsumedCountView(undefined, {visible: true});
cases.missingObject = answerConsumedCountView({consumed: 4, events: []}, {visible: true});
cases.empty = answerConsumedCountView([], {visible: true});
cases.counted = answerConsumedCountView(log, {visible: true});
cases.ignoresQuestion = answerConsumedCountView([
  event("q", "mission.question", {kind: "approval", consumed: 2}),
], {visible: true});
cases.ignoresAnswered = answerConsumedCountView([
  event("a", "user.answered", {answer: "yes", consumed: 3}),
], {visible: true});
cases.ignoresWaiting = answerConsumedCountView([
  event("w", "mission.waiting", {consumed: 1}),
], {visible: true});
cases.ignoresTool = answerConsumedCountView([
  event("tool", "tool.completed", {name: "search", consumed: 5}),
], {visible: true});
cases.ignoresLlm = answerConsumedCountView([
  event("llm", "llm.completed", {consumed: 6}),
], {visible: true});
cases.ignoresMissionCompleted = answerConsumedCountView([
  event("done", "mission.completed", {consumed: 1}),
], {visible: true});
cases.oneConsumedNotPayload = answerConsumedCountView([
  consumed("big", {consumed: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = answerConsumedCountView([null, {payload: {consumed: 10}}, consumed("one")], {visible: true});
cases.unreadableType = answerConsumedCountView([
  consumed("ok"),
  {id: "bad", event_type: 4, payload: {consumed: 1}},
], {visible: true});
cases.missingType = answerConsumedCountView([
  {id: "blank", payload: {consumed: 7}},
  consumed("one"),
], {visible: true});
cases.prefix = answerConsumedCountView(recordedAnswerConsumedFeed(log, 2, true), {visible: true});
cases.prefixFirst = answerConsumedCountView(recordedAnswerConsumedFeed(log, 1, true), {visible: true});
cases.prefixOne = answerConsumedCountView(recordedAnswerConsumedFeed(log, 5, true), {visible: true});
cases.prefixAll = answerConsumedCountView(recordedAnswerConsumedFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = answerConsumedCountView(recordedAnswerConsumedFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAnswerConsumedFeed(log, log.length - 1, false);
cases.unloadedView = answerConsumedCountView(recordedAnswerConsumedFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAnswerConsumedFeed([], -1, true);
cases.notArrayLog = recordedAnswerConsumedFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
