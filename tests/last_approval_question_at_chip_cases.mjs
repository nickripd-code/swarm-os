import {lastApprovalQuestionAtView, LAST_APPROVAL_QUESTION_UNAVAILABLE, recordedApprovalQuestionAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};
const ask = "Approve finish and spend the remaining budget?";

function view(feed, options = visible) {
  return lastApprovalQuestionAtView(feed, options);
}

function approval(created_at, extra = {}) {
  return {
    event_type: "mission.question",
    created_at,
    payload: {kind: "approval", question: ask, question_id: "q-1", ...extra},
  };
}

cases.unavailable = LAST_APPROVAL_QUESTION_UNAVAILABLE;
cases.noMission = view([approval("2026-09-23T12:35:04Z")], {visible: false});
cases.preview = view([approval("2026-09-23T12:35:04Z")], {});
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedApprovalQuestionAtFeed([
  {id: 1, ...approval("2026-09-23T12:35:04Z")},
], -1, true));
cases.feedNotLoaded = view(recordedApprovalQuestionAtFeed([
  {id: 1, ...approval("2026-09-23T12:35:04Z")},
], 0, false));
cases.plainQuestion = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {kind: "question", question: ask}},
]);
cases.missingKind = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: ask}},
]);
cases.nullKind = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {kind: null, question: ask}},
]);
cases.nullPayload = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: null},
]);
cases.waitingApproval = view([
  {event_type: "mission.waiting", created_at: "2026-09-23T12:35:04Z", payload: {kind: "approval", question: ask}},
]);
cases.answeredApproval = view([
  {event_type: "user.answered", created_at: "2026-09-23T12:35:04Z", payload: {kind: "approval", answer: "yes"}},
]);
cases.consumed = view([
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z", payload: {kind: "approval"}},
]);
cases.nonQuestion = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
  {event_type: "payment.created", created_at: "2026-09-23T12:41:00Z"},
]);
cases.clock = view([
  {event_type: "mission.question", created_at: "2026-09-23T08:00:00Z", payload: {kind: "question", question: "Which group?"}},
  {event_type: "mission.waiting", created_at: "2026-09-23T12:00:00Z", payload: {kind: "approval"}},
  approval("2026-09-23T12:35:04.123456Z"),
]);
cases.offset = view([approval("2026-09-23T08:35:04-04:00")]);
cases.newestByTime = view([
  approval("2026-09-23T12:40:00Z"),
  {event_type: "user.answered", created_at: "2026-09-23T12:55:00Z", payload: {kind: "approval", answer: "yes"}},
  approval("2026-09-23T12:10:00Z"),
  approval("2026-09-23T12:50:09Z"),
]);
cases.plainDoesNotOverride = view([
  approval("2026-09-23T12:35:04Z"),
  {event_type: "mission.question", created_at: "2026-09-23T13:00:00Z", payload: {kind: "question", question: ask}},
]);
cases.waitingDoesNotOverride = view([
  approval("2026-09-23T12:35:04Z"),
  {event_type: "mission.waiting", created_at: "2026-09-23T13:00:00Z", payload: {kind: "approval"}},
]);
cases.answeredDoesNotOverride = view([
  approval("2026-09-23T12:35:04Z"),
  {event_type: "user.answered", created_at: "2026-09-23T13:00:00Z", payload: {kind: "approval", answer: "yes"}},
]);
cases.consumedDoesNotOverride = view([
  approval("2026-09-23T12:35:04Z"),
  {event_type: "user.answer_consumed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.replayPrefix = view(recordedApprovalQuestionAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...approval("2026-09-23T12:35:04Z")},
  {id: 3, ...approval("2026-09-23T12:36:00Z")},
], 1, true));
cases.replayAtLater = view(recordedApprovalQuestionAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...approval("2026-09-23T12:35:04Z")},
  {id: 3, ...approval("2026-09-23T12:36:00Z")},
], 2, true));
cases.replayBefore = view(recordedApprovalQuestionAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...approval("2026-09-23T12:35:04Z")},
], 0, true));
cases.missingTime = view([approval(undefined)]);
cases.blankTime = view([approval("")]);
cases.whitespace = view([approval(" 2026-09-23T12:35:04Z")]);
cases.numericZero = view([approval(0)]);
cases.numericNow = view([approval(1758630904000)]);
cases.stringZero = view([approval("0")]);
cases.epoch = view([approval("1970-01-01T00:00:00Z")]);
cases.epochFraction = view([approval("1970-01-01T00:00:00.000000Z")]);
cases.naive = view([approval("2026-09-23T12:35:04")]);
cases.garbage = view([approval("just now")]);
cases.impossibleDay = view([approval("2026-02-31T12:35:04Z")]);
cases.newestInvalid = view([
  approval("2026-09-23T12:00:00Z"),
  approval(""),
]);
cases.nonObject = view(["mission.question"]);
cases.badType = view([{event_type: 1, created_at: "2026-09-23T12:35:04Z", payload: {kind: "approval"}}]);
cases.badPayload = view([{event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: "approval"}]);
cases.badKind = view([{event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {kind: 1}}]);
cases.spendIgnored = view([
  approval("2026-09-23T12:35:04Z", {token_spent: 9, input_tokens: 100}),
]);
cases.explicitEmptyFeed = recordedApprovalQuestionAtFeed([], -1, true);
cases.notArrayLog = recordedApprovalQuestionAtFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
