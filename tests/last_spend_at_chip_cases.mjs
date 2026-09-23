import {lastSpendAtView, LAST_SPEND_AT_NONE, LAST_SPEND_AT_UNAVAILABLE, recordedSpendAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};
const spend = (created_at, token_spent = 1.25, extra = {}) => ({
  event_type: "budget.updated",
  created_at,
  payload: {known: true, token_spent, token_budget: 3, ...extra},
});

function view(feed, options = visible) {
  return lastSpendAtView(feed, options);
}

cases.unavailable = LAST_SPEND_AT_UNAVAILABLE;
cases.none = LAST_SPEND_AT_NONE;
cases.noMission = view([spend("2026-09-23T12:35:04Z")], {visible: false});
cases.preview = view([spend("2026-09-23T12:35:04Z")], {});
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedSpendAtFeed([
  {id: 1, ...spend("2026-09-23T12:35:04Z")},
], -1, true));
cases.feedNotLoaded = view(recordedSpendAtFeed([
  {id: 1, ...spend("2026-09-23T12:35:04Z")},
], 0, false));
cases.nonSpend = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z", payload: {input_tokens: 100, output_tokens: 9}},
  {event_type: "budget.warning", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
  {event_type: "payment.created", created_at: "2026-09-23T12:41:00Z", payload: {amount: 1.25}},
  {event_type: "budget.updated", created_at: "2026-09-23T12:42:00Z", payload: {known: false, token_spent: 0}},
  {event_type: "budget.updated", created_at: "2026-09-23T12:43:00Z", payload: {known: true, token_spent: "1.25"}},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:00:00Z", payload: {input_tokens: 3, output_tokens: 1}},
  spend("2026-09-23T12:35:04.123456Z", 1.25),
]);
cases.offset = view([spend("2026-09-23T08:35:04-04:00", 2.5)]);
cases.newestByTime = view([
  spend("2026-09-23T12:40:00Z", 1),
  spend("2026-09-23T12:10:00Z", 0.5),
  spend("2026-09-23T12:50:09Z", 4),
]);
cases.zeroSpend = view([spend("2026-09-23T01:02:03Z", 0)]);
cases.unknownAfterKnown = view([
  spend("2026-09-23T12:35:04Z", 1.25),
  {event_type: "budget.updated", created_at: "2026-09-23T12:50:00Z", payload: {known: false, token_spent: 0}},
]);
cases.replayPrefix = view(recordedSpendAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...spend("2026-09-23T12:35:04Z")},
  {id: 3, ...spend("2026-09-23T12:36:00Z", 2)},
], 1, true));
cases.replayAtLater = view(recordedSpendAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...spend("2026-09-23T12:35:04Z")},
  {id: 3, ...spend("2026-09-23T12:36:00Z", 2)},
], 2, true));
cases.replayBeforeSpend = view(recordedSpendAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...spend("2026-09-23T12:35:04Z")},
], 0, true));
cases.missingTime = view([{event_type: "budget.updated", payload: {known: true, token_spent: 1}}]);
cases.blankTime = view([spend("", 1)]);
cases.whitespace = view([spend(" 2026-09-23T12:35:04Z", 1)]);
cases.numericZero = view([{event_type: "budget.updated", created_at: 0, payload: {known: true, token_spent: 1}}]);
cases.numericNow = view([{event_type: "budget.updated", created_at: 1758630904000, payload: {known: true, token_spent: 1}}]);
cases.stringZero = view([spend("0", 1)]);
cases.epoch = view([spend("1970-01-01T00:00:00Z", 1)]);
cases.epochFraction = view([spend("1970-01-01T00:00:00.000000Z", 1)]);
cases.naive = view([spend("2026-09-23T12:35:04", 1)]);
cases.garbage = view([spend("just now", 1)]);
cases.impossibleDay = view([spend("2026-02-31T12:35:04Z", 1)]);
cases.newestInvalid = view([
  spend("2026-09-23T12:00:00Z", 1),
  spend("", 2),
]);
cases.nonObject = view(["budget.updated"]);
cases.amountIgnored = view([spend("2026-09-23T12:35:04Z", 9.5, {input_tokens: 100})]);

console.log(JSON.stringify(cases));
