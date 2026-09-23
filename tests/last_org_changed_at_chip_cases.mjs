import {lastOrgChangedAtView, LAST_ORG_CHANGE_UNAVAILABLE, recordedOrgChangedAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastOrgChangedAtView(feed, options);
}

cases.unavailable = LAST_ORG_CHANGE_UNAVAILABLE;
cases.noMission = view(
  [{event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedOrgChangedAtFeed([
  {id: 1, event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedOrgChangedAtFeed([
  {id: 1, event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonOrg = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.spawnedOnly = view([
  {event_type: "agent.spawned", created_at: "2026-09-23T12:10:00Z"},
]);
cases.updatedOnly = view([
  {event_type: "agent.updated", created_at: "2026-09-23T12:11:00Z"},
]);
cases.reparentedOnly = view([
  {event_type: "agent.reparented", created_at: "2026-09-23T12:12:00Z"},
]);
cases.retiredOnly = view([
  {event_type: "agent.retired", created_at: "2026-09-23T12:13:00Z"},
]);
cases.killedOnly = view([
  {event_type: "agent.killed", created_at: "2026-09-23T12:14:00Z"},
]);
cases.toolFailedOnly = view([
  {event_type: "tool.failed", created_at: "2026-09-23T12:15:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "agent.reparented", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04.123456Z", payload: {op: "spawn"}},
]);
cases.offset = view([
  {event_type: "org.changed", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:40:00Z", payload: {op: "spawn"}},
  {event_type: "agent.reparented", created_at: "2026-09-23T12:55:00Z"},
  {event_type: "org.changed", created_at: "2026-09-23T12:10:00Z", payload: {op: "retire"}},
  {event_type: "org.changed", created_at: "2026-09-23T12:50:09Z", payload: {op: "reparent"}},
]);
cases.ops = view([
  {event_type: "org.changed", created_at: "2026-09-23T01:02:03Z", payload: {op: "replace"}},
]);
cases.spawnedDoesNotOverride = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T13:00:00Z"},
]);
cases.reparentedDoesNotOverride = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.reparented", created_at: "2026-09-23T13:00:00Z"},
]);
cases.retiredDoesNotOverride = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.retired", created_at: "2026-09-23T13:00:00Z"},
]);
cases.killedDoesNotOverride = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.killed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.toolFailedDoesNotOverride = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "tool.failed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.replayPrefix = view(recordedOrgChangedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "org.changed", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedOrgChangedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "org.changed", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayBeforeOrg = view(recordedOrgChangedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
], 0, true));
cases.missingTime = view([{event_type: "org.changed"}]);
cases.blankTime = view([{event_type: "org.changed", created_at: ""}]);
cases.whitespace = view([{event_type: "org.changed", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "org.changed", created_at: 0}]);
cases.numericNow = view([{event_type: "org.changed", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "org.changed", created_at: "0"}]);
cases.epoch = view([{event_type: "org.changed", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "org.changed", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "org.changed", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "org.changed", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "org.changed", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "org.changed", created_at: ""},
]);
cases.nonObject = view(["org.changed"]);
cases.otherAgentStates = view([
  {event_type: "agent.spawned", created_at: "2026-09-23T12:30:00Z"},
  {event_type: "agent.updated", created_at: "2026-09-23T12:31:00Z"},
  {event_type: "agent.reparented", created_at: "2026-09-23T12:32:00Z"},
  {event_type: "agent.retired", created_at: "2026-09-23T12:33:00Z"},
  {event_type: "agent.killed", created_at: "2026-09-23T12:34:00Z"},
]);
cases.questionIgnored = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "user.answered", created_at: "2026-09-23T12:36:04Z"},
  {event_type: "payment.created", created_at: "2026-09-23T12:37:04Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T12:38:04Z"},
  {event_type: "mission.resume_requested", created_at: "2026-09-23T12:38:30Z"},
  {event_type: "budget.warning", created_at: "2026-09-23T12:39:04Z"},
  {event_type: "tool.failed", created_at: "2026-09-23T12:40:04Z"},
  {event_type: "verification.evidence.started", created_at: "2026-09-23T12:41:04Z"},
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:42:04Z"},
]);
cases.spawnedDoesNotOverrideLate = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T13:00:00Z"},
]);
cases.spendIgnored = view([
  {event_type: "org.changed", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100, op: "spawn"}},
]);
cases.explicitEmptyFeed = recordedOrgChangedAtFeed([], -1, true);
cases.notArrayLog = recordedOrgChangedAtFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
