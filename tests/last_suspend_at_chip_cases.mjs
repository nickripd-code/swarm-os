import {lastSuspendAtView, LAST_SUSPEND_NONE, LAST_SUSPEND_UNAVAILABLE, recordedSuspendAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastSuspendAtView(feed, options);
}

cases.unavailable = LAST_SUSPEND_UNAVAILABLE;
cases.none = LAST_SUSPEND_NONE;
cases.noMission = view(
  [{event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedSuspendAtFeed([
  {id: 1, event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedSuspendAtFeed([
  {id: 1, event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonSuspend = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.siblingsOnly = view([
  {event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z", payload: {reason: "Execution paused by user"}},
  {event_type: "mission.stopped", created_at: "2026-09-23T12:20:00Z", payload: {reason: "Execution stopped"}},
  {event_type: "mission.failed", created_at: "2026-09-23T12:25:00Z", payload: {error: "failed", failure_class: "UNKNOWN_FAILURE"}},
  {event_type: "mission.waiting", created_at: "2026-09-23T12:30:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.question", created_at: "2026-09-23T12:31:00Z", payload: {question_id: "q1", question: "Need a domain?"}},
  {event_type: "mission.completed", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "agent.updated", created_at: "2026-09-23T12:41:00Z", payload: {status: "paused"}},
]);
cases.nonObject = view(["mission.suspended"]);
cases.replayPrefix = view(recordedSuspendAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z"},
  {id: 3, event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"},
  {id: 4, event_type: "mission.resumed", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "mission.paused", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.suspended", created_at: "2026-09-23T12:35:04.123456Z", payload: {reason: "Runtime is shutting down; unfinished work remains recoverable", mode: "live"}},
  {event_type: "mission.resumed", created_at: "2026-09-23T12:40:00Z"},
]);
cases.offset = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T12:50:09Z"},
  {event_type: "mission.suspended", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "mission.running", created_at: "2026-09-23T12:55:00Z"},
]);
cases.kinds = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T01:02:03Z", payload: {reason: "Runtime is shutting down; unfinished work remains recoverable", mode: "live"}},
]);
cases.siblingsDoNotOverride = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.paused", created_at: "2026-09-23T13:00:00Z"},
  {event_type: "mission.stopped", created_at: "2026-09-23T13:01:00Z"},
  {event_type: "mission.failed", created_at: "2026-09-23T13:02:00Z"},
  {event_type: "mission.waiting", created_at: "2026-09-23T13:03:00Z"},
  {event_type: "mission.question", created_at: "2026-09-23T13:04:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.completed", created_at: "2026-09-23T13:05:00Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T13:06:00Z"},
]);
cases.replayAtSuspend = view(recordedSuspendAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z"},
  {id: 3, event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"},
  {id: 4, event_type: "mission.resumed", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayAfter = view(recordedSuspendAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z"},
  {id: 3, event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z"},
  {id: 4, event_type: "mission.resumed", created_at: "2026-09-23T12:36:00Z"},
], 3, true));
cases.missingTime = view([{event_type: "mission.suspended"}]);
cases.blankTime = view([{event_type: "mission.suspended", created_at: ""}]);
cases.whitespace = view([{event_type: "mission.suspended", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "mission.suspended", created_at: 0}]);
cases.numericNow = view([{event_type: "mission.suspended", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "mission.suspended", created_at: "0"}]);
cases.epoch = view([{event_type: "mission.suspended", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "mission.suspended", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "mission.suspended", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "mission.suspended", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "mission.suspended", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.suspended", created_at: ""},
]);
cases.spendIgnored = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
