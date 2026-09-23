import {lastBudgetWarningAtView, LAST_BUDGET_WARN_AT_NONE, LAST_BUDGET_WARN_AT_UNAVAILABLE, recordedBudgetWarningAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};
const warning = (created_at, token_spent = 1.25, extra = {}) => ({
  event_type: "budget.warning",
  created_at,
  payload: {token_spent, token_budget: 3, fraction: 0.8, estimate: true, currency: "USD", ...extra},
});

function view(feed, options = visible) {
  return lastBudgetWarningAtView(feed, options);
}

cases.unavailable = LAST_BUDGET_WARN_AT_UNAVAILABLE;
cases.none = LAST_BUDGET_WARN_AT_NONE;
cases.noMission = view([warning("2026-09-23T12:35:04Z")], {visible: false});
cases.preview = view([warning("2026-09-23T12:35:04Z")], {});
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedBudgetWarningAtFeed([
  {id: 1, ...warning("2026-09-23T12:35:04Z")},
], -1, true));
cases.feedNotLoaded = view(recordedBudgetWarningAtFeed([
  {id: 1, ...warning("2026-09-23T12:35:04Z")},
], 0, false));
cases.nonWarning = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z", payload: {input_tokens: 100, output_tokens: 9}},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25, token_budget: 3}},
  {event_type: "payment.created", created_at: "2026-09-23T12:41:00Z", payload: {amount: 1.25}},
  {event_type: "budget.warning", created_at: "2026-09-23T12:42:00Z", payload: {token_spent: "1.25", token_budget: 3}},
  {event_type: "budget.warning", created_at: "2026-09-23T12:43:00Z", payload: {token_spent: 1.25}},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:00:00Z", payload: {input_tokens: 3, output_tokens: 1}},
  warning("2026-09-23T12:35:04.123456Z", 1.25),
]);
cases.offset = view([warning("2026-09-23T08:35:04-04:00", 2.5)]);
cases.newestByTime = view([
  warning("2026-09-23T12:40:00Z", 1),
  warning("2026-09-23T12:10:00Z", 0.5),
  warning("2026-09-23T12:50:09Z", 4),
]);
cases.zeroSpend = view([warning("2026-09-23T01:02:03Z", 0)]);
cases.spendAfterWarning = view([
  warning("2026-09-23T12:35:04Z", 1.25),
  {event_type: "budget.updated", created_at: "2026-09-23T12:50:00Z", payload: {known: true, token_spent: 9.5, token_budget: 3}},
]);
cases.replayPrefix = view(recordedBudgetWarningAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...warning("2026-09-23T12:35:04Z")},
  {id: 3, ...warning("2026-09-23T12:36:00Z", 2)},
], 1, true));
cases.replayAtLater = view(recordedBudgetWarningAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...warning("2026-09-23T12:35:04Z")},
  {id: 3, ...warning("2026-09-23T12:36:00Z", 2)},
], 2, true));
cases.replayBeforeWarning = view(recordedBudgetWarningAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...warning("2026-09-23T12:35:04Z")},
], 0, true));
cases.missingTime = view([{event_type: "budget.warning", payload: {token_spent: 1, token_budget: 3}}]);
cases.blankTime = view([warning("", 1)]);
cases.whitespace = view([warning(" 2026-09-23T12:35:04Z", 1)]);
cases.numericZero = view([{event_type: "budget.warning", created_at: 0, payload: {token_spent: 1, token_budget: 3}}]);
cases.numericNow = view([{event_type: "budget.warning", created_at: 1758630904000, payload: {token_spent: 1, token_budget: 3}}]);
cases.stringZero = view([warning("0", 1)]);
cases.epoch = view([warning("1970-01-01T00:00:00Z", 1)]);
cases.epochFraction = view([warning("1970-01-01T00:00:00.000000Z", 1)]);
cases.naive = view([warning("2026-09-23T12:35:04", 1)]);
cases.garbage = view([warning("just now", 1)]);
cases.impossibleDay = view([warning("2026-02-31T12:35:04Z", 1)]);
cases.newestInvalid = view([
  warning("2026-09-23T12:00:00Z", 1),
  warning("", 2),
]);
cases.nonObject = view(["budget.warning"]);
cases.amountIgnored = view([warning("2026-09-23T12:35:04Z", 9.5, {remaining: 0.5, fraction: 0.8})]);

console.log(JSON.stringify(cases));
