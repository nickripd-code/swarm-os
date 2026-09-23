import {lastMissionStartedAtView, LAST_MISSION_STARTED_UNAVAILABLE, recordedMissionStartedAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastMissionStartedAtView(feed, options);
}

cases.unavailable = LAST_MISSION_STARTED_UNAVAILABLE;
cases.noMission = view(
  [{event_type: "mission.started", created_at: "2026-09-23T12:35:04Z", payload: {goal: "ship", mode: "openai"}}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedMissionStartedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedMissionStartedAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonStart = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.running", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.resumedOnly = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T12:10:00Z"},
]);
cases.runningOnly = view([
  {event_type: "mission.running", created_at: "2026-09-23T12:15:00Z"},
]);
cases.resumeRequestedOnly = view([
  {event_type: "mission.resume_requested", created_at: "2026-09-23T12:20:00Z", payload: {reason: "User requested resume", from_status: "paused"}},
]);
cases.pausedOnly = view([
  {event_type: "mission.paused", created_at: "2026-09-23T12:25:00Z"},
]);
cases.taskStartedOnly = view([
  {event_type: "task.started", created_at: "2026-09-23T12:26:00Z"},
]);
cases.llmStartedOnly = view([
  {event_type: "llm.started", created_at: "2026-09-23T12:27:00Z"},
]);
cases.toolStartedOnly = view([
  {event_type: "tool.started", created_at: "2026-09-23T12:28:00Z"},
]);
cases.verificationStartedOnly = view([
  {event_type: "verification.started", created_at: "2026-09-23T12:29:00Z"},
]);
cases.clock = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "task.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.running", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04.123456Z", payload: {goal: "ship the chip", mode: "openai"}},
]);
cases.offset = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:40:00Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T12:55:00Z"},
  {event_type: "mission.started", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "mission.started", created_at: "2026-09-23T12:50:09Z"},
]);
cases.kinds = view([
  {event_type: "mission.started", created_at: "2026-09-23T01:02:03Z", payload: {goal: "ship", mode: "openai"}},
]);
cases.resumedDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T13:00:00Z"},
]);
cases.runningDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.running", created_at: "2026-09-23T13:00:00Z"},
]);
cases.resumeRequestedDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.resume_requested", created_at: "2026-09-23T13:00:00Z"},
]);
cases.pausedDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.paused", created_at: "2026-09-23T13:00:00Z"},
]);
cases.taskStartedDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "task.started", created_at: "2026-09-23T13:00:00Z"},
]);
cases.llmStartedDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "llm.started", created_at: "2026-09-23T13:00:00Z"},
]);
cases.toolStartedDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "tool.started", created_at: "2026-09-23T13:00:00Z"},
]);
cases.verificationStartedDoesNotOverride = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "verification.started", created_at: "2026-09-23T13:00:00Z"},
]);
cases.replayPrefix = view(recordedMissionStartedAtFeed([
  {id: 1, event_type: "mission.paused", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "mission.started", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedMissionStartedAtFeed([
  {id: 1, event_type: "mission.paused", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "mission.started", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayBeforeStart = view(recordedMissionStartedAtFeed([
  {id: 1, event_type: "mission.paused", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.started", created_at: "2026-09-23T12:35:04Z"},
], 0, true));
cases.missingTime = view([{event_type: "mission.started"}]);
cases.blankTime = view([{event_type: "mission.started", created_at: ""}]);
cases.whitespace = view([{event_type: "mission.started", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "mission.started", created_at: 0}]);
cases.numericNow = view([{event_type: "mission.started", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "mission.started", created_at: "0"}]);
cases.epoch = view([{event_type: "mission.started", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "mission.started", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "mission.started", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "mission.started", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "mission.started", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.started", created_at: ""},
]);
cases.nonObject = view(["mission.started"]);
cases.otherStarts = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T12:30:00Z"},
  {event_type: "mission.running", created_at: "2026-09-23T12:31:00Z"},
  {event_type: "mission.resume_requested", created_at: "2026-09-23T12:32:00Z"},
  {event_type: "task.started", created_at: "2026-09-23T12:33:00Z"},
  {event_type: "llm.started", created_at: "2026-09-23T12:34:00Z"},
  {event_type: "tool.started", created_at: "2026-09-23T12:34:30Z"},
  {event_type: "verification.started", created_at: "2026-09-23T12:34:45Z"},
]);
cases.questionIgnored = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "user.answered", created_at: "2026-09-23T12:36:04Z"},
  {event_type: "payment.created", created_at: "2026-09-23T12:37:04Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T12:38:04Z"},
  {event_type: "budget.warning", created_at: "2026-09-23T12:39:04Z"},
  {event_type: "agent.spawned", created_at: "2026-09-23T12:40:04Z"},
  {event_type: "job.retry_scheduled", created_at: "2026-09-23T12:41:04Z"},
]);
cases.spendIgnored = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100, goal: "ship"}},
]);
cases.explicitEmptyFeed = recordedMissionStartedAtFeed([], -1, true);
cases.notArrayLog = recordedMissionStartedAtFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
