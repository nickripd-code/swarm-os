import {lastToolAtView, LAST_TOOL_AT_NONE, LAST_TOOL_AT_UNAVAILABLE, recordedToolAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastToolAtView(feed, options);
}

cases.unavailable = LAST_TOOL_AT_UNAVAILABLE;
cases.none = LAST_TOOL_AT_NONE;
cases.noMission = view(
  [{event_type: "tool.completed", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "tool.completed", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedToolAtFeed([
  {id: 1, event_type: "tool.started", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedToolAtFeed([
  {id: 1, event_type: "tool.completed", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonTool = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "tool.success", created_at: "2026-09-23T12:36:00Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "tool.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "tool.completed", created_at: "2026-09-23T12:35:04.123456Z", payload: {tool: "workspace.read", ok: true}},
]);
cases.offset = view([
  {event_type: "tool.failed", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "tool.completed", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "tool.started", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "tool.failed", created_at: "2026-09-23T12:50:09Z"},
]);
cases.kinds = view([
  {event_type: "tool.started", created_at: "2026-09-23T01:02:03Z"},
]);
cases.replayPrefix = view(recordedToolAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "tool.started", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "tool.completed", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedToolAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "tool.started", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "tool.completed", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.missingTime = view([{event_type: "tool.started"}]);
cases.blankTime = view([{event_type: "tool.completed", created_at: ""}]);
cases.whitespace = view([{event_type: "tool.failed", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "tool.started", created_at: 0}]);
cases.numericNow = view([{event_type: "tool.completed", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "tool.failed", created_at: "0"}]);
cases.epoch = view([{event_type: "tool.completed", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "tool.completed", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "tool.completed", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "tool.completed", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "tool.completed", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "tool.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "tool.completed", created_at: ""},
]);
cases.nonObject = view(["tool.completed"]);
cases.spendIgnored = view([
  {event_type: "tool.completed", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, tool: "workspace.read"}},
]);

console.log(JSON.stringify(cases));
