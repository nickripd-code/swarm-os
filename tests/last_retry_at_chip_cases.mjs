import {lastRetryAtView, LAST_RETRY_AT_NONE, LAST_RETRY_AT_UNAVAILABLE, recordedRetryAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastRetryAtView(feed, options);
}

cases.unavailable = LAST_RETRY_AT_UNAVAILABLE;
cases.none = LAST_RETRY_AT_NONE;
cases.noMission = view(
  [{event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedRetryAtFeed([
  {id: 1, event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedRetryAtFeed([
  {id: 1, event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonRetry = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "tool.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.otherLlm = view([
  {event_type: "llm.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "llm.failover", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "llm.failed", created_at: "2026-09-23T12:50:09Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "llm.failover", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.retry", created_at: "2026-09-23T12:35:04.123456Z", payload: {attempt: 2}},
]);
cases.offset = view([
  {event_type: "llm.retry", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "llm.retry", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "llm.failed", created_at: "2026-09-23T12:55:00Z"},
  {event_type: "llm.retry", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "llm.failover", created_at: "2026-09-23T12:50:09Z"},
]);
cases.ignoresLaterNonRetry = view([
  {event_type: "llm.retry", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "llm.failover", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "llm.failed", created_at: "2026-09-23T12:50:09Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.replayPrefix = view(recordedRetryAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "llm.retry", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedRetryAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "llm.retry", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayBeforeRetry = view(recordedRetryAtFeed([
  {id: 1, event_type: "llm.failover", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"},
], 0, true));
cases.missingTime = view([{event_type: "llm.retry"}]);
cases.blankTime = view([{event_type: "llm.retry", created_at: ""}]);
cases.whitespace = view([{event_type: "llm.retry", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "llm.retry", created_at: 0}]);
cases.numericNow = view([{event_type: "llm.retry", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "llm.retry", created_at: "0"}]);
cases.epoch = view([{event_type: "llm.retry", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "llm.retry", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "llm.retry", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "llm.retry", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "llm.retry", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "llm.retry", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.retry", created_at: ""},
]);
cases.trailingInvalidOther = view([
  {event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "llm.failed", created_at: "not-a-time"},
  {event_type: "llm.failover", created_at: ""},
]);
cases.nonObject = view(["llm.retry"]);
cases.spendIgnored = view([
  {event_type: "llm.retry", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
