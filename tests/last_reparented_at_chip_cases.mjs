import {lastReparentedAtView, LAST_REPARENT_UNAVAILABLE, recordedReparentedAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastReparentedAtView(feed, options);
}

cases.unavailable = LAST_REPARENT_UNAVAILABLE;
cases.noMission = view(
  [{event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedReparentedAtFeed([
  {id: 1, event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedReparentedAtFeed([
  {id: 1, event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonReparent = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.spawnOnly = view([
  {event_type: "agent.spawned", created_at: "2026-09-23T12:10:00Z"},
]);
cases.updatedOnly = view([
  {event_type: "agent.updated", created_at: "2026-09-23T12:15:00Z"},
]);
cases.retiredOnly = view([
  {event_type: "agent.retired", created_at: "2026-09-23T12:20:00Z"},
]);
cases.killedOnly = view([
  {event_type: "agent.killed", created_at: "2026-09-23T12:25:00Z"},
]);
cases.orgOnly = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:28:00Z"},
]);
cases.missionFailOnly = view([
  {event_type: "mission.failed", created_at: "2026-09-23T12:30:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "agent.updated", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "agent.reparented", created_at: "2026-09-23T12:35:04.123456Z", payload: {parent_id: "p2"}},
]);
cases.offset = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "agent.retired", created_at: "2026-09-23T12:55:00Z"},
  {event_type: "agent.reparented", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "agent.reparented", created_at: "2026-09-23T12:50:09Z"},
]);
cases.kinds = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T01:02:03Z"},
]);
cases.spawnDoesNotOverride = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T13:00:00Z"},
]);
cases.updatedDoesNotOverride = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.updated", created_at: "2026-09-23T13:00:00Z"},
]);
cases.retiredDoesNotOverride = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.retired", created_at: "2026-09-23T13:00:00Z"},
]);
cases.killedDoesNotOverride = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.killed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.missionFailDoesNotOverride = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.failed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.replayPrefix = view(recordedReparentedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "agent.reparented", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedReparentedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "agent.reparented", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayBeforeReparent = view(recordedReparentedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z"},
], 0, true));
cases.missingTime = view([{event_type: "agent.reparented"}]);
cases.blankTime = view([{event_type: "agent.reparented", created_at: ""}]);
cases.whitespace = view([{event_type: "agent.reparented", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "agent.reparented", created_at: 0}]);
cases.numericNow = view([{event_type: "agent.reparented", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "agent.reparented", created_at: "0"}]);
cases.epoch = view([{event_type: "agent.reparented", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "agent.reparented", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "agent.reparented", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "agent.reparented", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "agent.reparented", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "agent.reparented", created_at: ""},
]);
cases.nonObject = view(["agent.reparented"]);
cases.otherAgentStates = view([
  {event_type: "agent.spawned", created_at: "2026-09-23T12:30:00Z"},
  {event_type: "agent.updated", created_at: "2026-09-23T12:31:00Z"},
  {event_type: "agent.retired", created_at: "2026-09-23T12:32:00Z"},
  {event_type: "agent.killed", created_at: "2026-09-23T12:33:00Z"},
]);
cases.spendIgnored = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
