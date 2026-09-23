import {lastAnswerConsumedAtView, LAST_ANSWER_CONSUMED_AT_NONE, LAST_ANSWER_CONSUMED_AT_UNAVAILABLE, recordedAnswerConsumedAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastAnswerConsumedAtView(feed, options);
}

cases.unavailable = LAST_ANSWER_CONSUMED_AT_UNAVAILABLE;
cases.none = LAST_ANSWER_CONSUMED_AT_NONE;
cases.noMission = view(
  [{event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedAnswerConsumedAtFeed([
  {id: 1, event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedAnswerConsumedAtFeed([
  {id: 1, event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonConsumed = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.answeredIgnored = view([
  {event_type: "user.answered", created_at: "2026-09-23T12:35:04Z", payload: {question_id: "q1"}},
]);
cases.questionIgnored = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:10:00Z", payload: {question_id: "q1", question: "Need a domain?"}},
]);
cases.waitingIgnored = view([
  {event_type: "mission.waiting", created_at: "2026-09-23T12:10:00Z", payload: {question_id: "q1", question: "Need a domain?"}},
]);
cases.parkIgnored = view([
  {event_type: "mission.paused", created_at: "2026-09-23T12:20:00Z", payload: {pending_question_id: "q1"}},
]);
cases.notConsumed = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "user.answered", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.waiting", created_at: "2026-09-23T12:50:00Z"},
  {event_type: "mission.paused", created_at: "2026-09-23T12:55:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "user.answered", created_at: "2026-09-23T12:30:00Z", payload: {question_id: "q1"}},
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04.123456Z", payload: {question_id: "q1"}},
]);
cases.offset = view([
  {event_type: "user.answer_consumed", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "user.answered", created_at: "2026-09-23T13:10:00Z"},
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:50:09Z"},
  {event_type: "mission.question", created_at: "2026-09-23T13:20:00Z"},
]);
cases.kinds = view([
  {event_type: "user.answer_consumed", created_at: "2026-09-23T01:02:03Z"},
]);
cases.siblingsDoNotOverride = view([
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "user.answered", created_at: "2026-09-23T13:00:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.waiting", created_at: "2026-09-23T13:05:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.question", created_at: "2026-09-23T13:10:00Z"},
  {event_type: "mission.paused", created_at: "2026-09-23T13:15:00Z"},
]);
cases.replayPrefix = view(recordedAnswerConsumedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "user.answer_consumed", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedAnswerConsumedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "user.answer_consumed", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayBeforeConsumed = view(recordedAnswerConsumedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "user.answered", created_at: "2026-09-23T12:10:00Z"},
  {id: 3, event_type: "user.answer_consumed", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.missingTime = view([{event_type: "user.answer_consumed"}]);
cases.blankTime = view([{event_type: "user.answer_consumed", created_at: ""}]);
cases.whitespace = view([{event_type: "user.answer_consumed", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "user.answer_consumed", created_at: 0}]);
cases.numericNow = view([{event_type: "user.answer_consumed", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "user.answer_consumed", created_at: "0"}]);
cases.epoch = view([{event_type: "user.answer_consumed", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "user.answer_consumed", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "user.answer_consumed", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "user.answer_consumed", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "user.answer_consumed", created_at: ""},
]);
cases.nonObject = view(["user.answer_consumed"]);
cases.spendIgnored = view([
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
