import {lastTaskPendingAtView, LAST_TASK_PENDING_UNAVAILABLE, recordedTaskPendingAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastTaskPendingAtView(feed, options);
}

cases.unavailable = LAST_TASK_PENDING_UNAVAILABLE;
cases.noMission = view(
  [{event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedTaskPendingAtFeed([
  {id: 1, event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedTaskPendingAtFeed([
  {id: 1, event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonTaskPending = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.startedOnly = view([
  {event_type: "task.started", created_at: "2026-09-23T12:10:00Z"},
]);
cases.completedOnly = view([
  {event_type: "task.completed", created_at: "2026-09-23T12:20:00Z"},
]);
cases.failedOnly = view([
  {event_type: "task.failed", created_at: "2026-09-23T12:21:00Z"},
]);
cases.blockedOnly = view([
  {event_type: "task.blocked", created_at: "2026-09-23T12:22:00Z"},
  {event_type: "mission.blocked", created_at: "2026-09-23T12:23:00Z"},
]);
cases.suspendedOnly = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T12:24:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "task.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "task.pending", created_at: "2026-09-23T12:35:04.123456Z"},
  {event_type: "mission.blocked", created_at: "2026-09-23T12:40:00Z"},
]);
cases.offset = view([
  {event_type: "task.pending", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "task.pending", created_at: "2026-09-23T12:50:09Z"},
  {event_type: "task.pending", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "task.started", created_at: "2026-09-23T12:55:00Z"},
]);
cases.kinds = view([
  {event_type: "task.pending", created_at: "2026-09-23T01:02:03Z"},
]);
cases.startedDoesNotOverride = view([
  {event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "task.started", created_at: "2026-09-23T13:00:00Z"},
]);
cases.completedDoesNotOverride = view([
  {event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "task.completed", created_at: "2026-09-23T13:05:00Z"},
]);
cases.failedDoesNotOverride = view([
  {event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "task.failed", created_at: "2026-09-23T13:06:00Z"},
]);
cases.blockedDoesNotOverride = view([
  {event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "task.blocked", created_at: "2026-09-23T13:07:00Z"},
  {event_type: "mission.blocked", created_at: "2026-09-23T13:08:00Z"},
  {event_type: "mission.suspended", created_at: "2026-09-23T13:09:00Z"},
]);
cases.replayBefore = view(recordedTaskPendingAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "task.pending", created_at: "2026-09-23T12:36:00Z"},
  {id: 4, event_type: "task.started", created_at: "2026-09-23T12:37:00Z"},
], 0, true));
cases.replayPrefix = view(recordedTaskPendingAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "task.pending", created_at: "2026-09-23T12:36:00Z"},
  {id: 4, event_type: "task.started", created_at: "2026-09-23T12:37:00Z"},
], 1, true));
cases.replayAtLater = view(recordedTaskPendingAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "task.pending", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "task.pending", created_at: "2026-09-23T12:36:00Z"},
  {id: 4, event_type: "task.started", created_at: "2026-09-23T12:37:00Z"},
], 3, true));
cases.missingTime = view([{event_type: "task.pending"}]);
cases.blankTime = view([{event_type: "task.pending", created_at: ""}]);
cases.whitespace = view([{event_type: "task.pending", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "task.pending", created_at: 0}]);
cases.numericNow = view([{event_type: "task.pending", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "task.pending", created_at: "0"}]);
cases.epoch = view([{event_type: "task.pending", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "task.pending", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "task.pending", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "task.pending", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "task.pending", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "task.pending", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "task.pending", created_at: ""},
]);
cases.nonObject = view(["task.pending"]);
cases.spendIgnored = view([
  {event_type: "task.pending", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
