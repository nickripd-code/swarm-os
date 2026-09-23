import {lastLeaseClaimedAtView, LAST_LEASE_CLAIM_UNAVAILABLE, recordedLeaseClaimedAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastLeaseClaimedAtView(feed, options);
}

cases.unavailable = LAST_LEASE_CLAIM_UNAVAILABLE;
cases.noMission = view(
  [{event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedLeaseClaimedAtFeed([
  {id: 1, event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedLeaseClaimedAtFeed([
  {id: 1, event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonClaim = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "lease.expired", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.expiredOnly = view([
  {event_type: "lease.expired", created_at: "2026-09-23T12:10:00Z"},
]);
cases.releasedOnly = view([
  {event_type: "lease.released", created_at: "2026-09-23T12:15:00Z"},
]);
cases.jobOnly = view([
  {event_type: "job.enqueued", created_at: "2026-09-23T12:20:00Z"},
]);
cases.toolStartedOnly = view([
  {event_type: "tool.started", created_at: "2026-09-23T12:25:00Z"},
]);
cases.toolCompletedOnly = view([
  {event_type: "tool.completed", created_at: "2026-09-23T12:26:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "lease.expired", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "lease.released", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04.123456Z", payload: {scope: "mission", lease_id: "c1"}},
]);
cases.offset = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "lease.released", created_at: "2026-09-23T12:55:00Z"},
  {event_type: "lease.claimed", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "lease.claimed", created_at: "2026-09-23T12:50:09Z"},
]);
cases.kinds = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T01:02:03Z"},
]);
cases.expiredDoesNotOverride = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "lease.expired", created_at: "2026-09-23T13:00:00Z"},
]);
cases.releasedDoesNotOverride = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "lease.released", created_at: "2026-09-23T13:00:00Z"},
]);
cases.jobDoesNotOverride = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "job.enqueued", created_at: "2026-09-23T13:00:00Z"},
]);
cases.toolStartedDoesNotOverride = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "tool.started", created_at: "2026-09-23T13:00:00Z"},
]);
cases.toolCompletedDoesNotOverride = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "tool.completed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.replayPrefix = view(recordedLeaseClaimedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "lease.claimed", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedLeaseClaimedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "lease.claimed", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayBeforeClaim = view(recordedLeaseClaimedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
], 0, true));
cases.missingTime = view([{event_type: "lease.claimed"}]);
cases.blankTime = view([{event_type: "lease.claimed", created_at: ""}]);
cases.whitespace = view([{event_type: "lease.claimed", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "lease.claimed", created_at: 0}]);
cases.numericNow = view([{event_type: "lease.claimed", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "lease.claimed", created_at: "0"}]);
cases.epoch = view([{event_type: "lease.claimed", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "lease.claimed", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "lease.claimed", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "lease.claimed", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "lease.claimed", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "lease.claimed", created_at: ""},
]);
cases.nonObject = view(["lease.claimed"]);
cases.otherLeaseStates = view([
  {event_type: "lease.expired", created_at: "2026-09-23T12:30:00Z"},
  {event_type: "lease.released", created_at: "2026-09-23T12:31:00Z"},
]);
cases.questionIgnored = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "user.answered", created_at: "2026-09-23T12:36:04Z"},
  {event_type: "payment.created", created_at: "2026-09-23T12:37:04Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T12:38:04Z"},
  {event_type: "budget.warning", created_at: "2026-09-23T12:39:04Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T12:40:04Z"},
  {event_type: "job.enqueued", created_at: "2026-09-23T12:41:04Z"},
]);
cases.releasedDoesNotOverrideLate = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "lease.released", created_at: "2026-09-23T13:00:00Z"},
]);
cases.spendIgnored = view([
  {event_type: "lease.claimed", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);
cases.explicitEmptyFeed = recordedLeaseClaimedAtFeed([], -1, true);
cases.notArrayLog = recordedLeaseClaimedAtFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
