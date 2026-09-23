import {lastPlannerProposalAtView, LAST_PLANNER_UNAVAILABLE, recordedPlannerProposalAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastPlannerProposalAtView(feed, options);
}

cases.unavailable = LAST_PLANNER_UNAVAILABLE;
cases.noMission = view(
  [{event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedPlannerProposalAtFeed([
  {id: 1, event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedPlannerProposalAtFeed([
  {id: 1, event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonProposal = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.judgeOnly = view([
  {event_type: "judge.decision", created_at: "2026-09-23T12:10:00Z"},
]);
cases.controllerOnly = view([
  {event_type: "controller.decision", created_at: "2026-09-23T12:15:00Z"},
]);
cases.llmOnly = view([
  {event_type: "llm.started", created_at: "2026-09-23T12:20:00Z", payload: {kind: "decision"}},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "judge.decision", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "controller.decision", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "planner.proposal", created_at: "2026-09-23T12:35:04.123456Z", payload: {action: "spawn"}},
]);
cases.offset = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "judge.decision", created_at: "2026-09-23T12:55:00Z"},
  {event_type: "planner.proposal", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "planner.proposal", created_at: "2026-09-23T12:50:09Z"},
]);
cases.kinds = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T01:02:03Z"},
]);
cases.judgeDoesNotOverride = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "judge.decision", created_at: "2026-09-23T13:00:00Z"},
]);
cases.controllerDoesNotOverride = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "controller.decision", created_at: "2026-09-23T13:00:00Z"},
]);
cases.llmDoesNotOverride = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "llm.started", created_at: "2026-09-23T13:00:00Z", payload: {kind: "decision"}},
]);
cases.replayPrefix = view(recordedPlannerProposalAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "planner.proposal", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedPlannerProposalAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "planner.proposal", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayBeforeProposal = view(recordedPlannerProposalAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z"},
], 0, true));
cases.missingTime = view([{event_type: "planner.proposal"}]);
cases.blankTime = view([{event_type: "planner.proposal", created_at: ""}]);
cases.whitespace = view([{event_type: "planner.proposal", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "planner.proposal", created_at: 0}]);
cases.numericNow = view([{event_type: "planner.proposal", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "planner.proposal", created_at: "0"}]);
cases.epoch = view([{event_type: "planner.proposal", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "planner.proposal", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "planner.proposal", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "planner.proposal", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "planner.proposal", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "planner.proposal", created_at: ""},
]);
cases.nonObject = view(["planner.proposal"]);
cases.spendIgnored = view([
  {event_type: "planner.proposal", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
