import {lastPaymentAtView, LAST_PAYMENT_AT_NONE, LAST_PAYMENT_AT_UNAVAILABLE, recordedPaymentAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastPaymentAtView(feed, options);
}

cases.unavailable = LAST_PAYMENT_AT_UNAVAILABLE;
cases.none = LAST_PAYMENT_AT_NONE;
cases.noMission = view(
  [{event_type: "payment.created", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "payment.created", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedPaymentAtFeed([
  {id: 1, event_type: "payment.created", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedPaymentAtFeed([
  {id: 1, event_type: "payment.created", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonPayment = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:35:04Z", payload: {known: true, token_spent: 1.25}},
  {event_type: "llm.completed", created_at: "2026-09-23T12:40:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "payment.created", created_at: "2026-09-23T12:35:04.123456Z", payload: {amount: 3, recipient: "vendor"}},
]);
cases.offset = view([
  {event_type: "payment.created", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "payment.created", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "payment.created", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "payment.created", created_at: "2026-09-23T12:50:09Z"},
]);
cases.replayPrefix = view(recordedPaymentAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "payment.created", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "payment.created", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedPaymentAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "payment.created", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "payment.created", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.missingTime = view([{event_type: "payment.created"}]);
cases.blankTime = view([{event_type: "payment.created", created_at: ""}]);
cases.whitespace = view([{event_type: "payment.created", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "payment.created", created_at: 0}]);
cases.numericNow = view([{event_type: "payment.created", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "payment.created", created_at: "0"}]);
cases.epoch = view([{event_type: "payment.created", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "payment.created", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "payment.created", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "payment.created", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "payment.created", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "payment.created", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "payment.created", created_at: ""},
]);
cases.nonObject = view(["payment.created"]);
cases.amountIgnored = view([
  {event_type: "payment.created", created_at: "2026-09-23T12:35:04Z", payload: {amount: 9, spent: 100, token_spent: 1.25}},
]);
cases.otherPaymentType = view([
  {event_type: "payment.settled", created_at: "2026-09-23T12:35:04Z", payload: {amount: 4}},
]);

console.log(JSON.stringify(cases));
