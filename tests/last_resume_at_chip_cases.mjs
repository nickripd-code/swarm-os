import {lastResumeAtView, LAST_RESUME_NONE, LAST_RESUME_UNAVAILABLE, recordedResumeAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastResumeAtView(feed, options);
}

cases.unavailable = LAST_RESUME_UNAVAILABLE;
cases.none = LAST_RESUME_NONE;
cases.noMission = view(
  [{event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedResumeAtFeed([
  {id: 1, event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedResumeAtFeed([
  {id: 1, event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonResume = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.pauseIgnored = view([
  {event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z", payload: {reason: "Execution paused by user"}},
  {event_type: "mission.waiting", created_at: "2026-09-23T12:20:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.suspended", created_at: "2026-09-23T12:21:00Z"},
  {event_type: "mission.resume_requested", created_at: "2026-09-23T12:22:00Z"},
]);
cases.waitingIgnored = view([
  {event_type: "mission.waiting", created_at: "2026-09-23T12:10:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.question", created_at: "2026-09-23T12:20:00Z", payload: {question_id: "q1", question: "Need a domain?"}},
]);
cases.suspendIgnored = view([
  {event_type: "mission.suspended", created_at: "2026-09-23T12:31:00Z"},
  {event_type: "agent.updated", created_at: "2026-09-23T12:32:00Z", payload: {status: "running"}},
  {event_type: "mission.running", created_at: "2026-09-23T12:33:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "mission.paused", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T12:35:04.123456Z", payload: {reason: "Human resume"}},
  {event_type: "mission.suspended", created_at: "2026-09-23T12:40:00Z"},
]);
cases.offset = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T12:50:09Z"},
  {event_type: "mission.resumed", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "mission.running", created_at: "2026-09-23T12:55:00Z"},
]);
cases.kinds = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T01:02:03Z", payload: {reason: "Human resume"}},
]);
cases.pauseDoesNotOverride = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "mission.paused", created_at: "2026-09-23T13:00:00Z"},
  {event_type: "mission.waiting", created_at: "2026-09-23T13:05:00Z"},
  {event_type: "mission.suspended", created_at: "2026-09-23T13:06:00Z"},
  {event_type: "mission.resume_requested", created_at: "2026-09-23T13:07:00Z"},
]);
cases.requestIgnored = view([
  {event_type: "mission.resume_requested", created_at: "2026-09-23T12:35:04Z"},
]);
cases.replayPrefix = view(recordedResumeAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z"},
  {id: 3, event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"},
  {id: 4, event_type: "mission.waiting", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtResume = view(recordedResumeAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z"},
  {id: 3, event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"},
  {id: 4, event_type: "mission.waiting", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.replayAfter = view(recordedResumeAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z"},
  {id: 3, event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z"},
  {id: 4, event_type: "mission.waiting", created_at: "2026-09-23T12:36:00Z"},
], 3, true));
cases.missingTime = view([{event_type: "mission.resumed"}]);
cases.blankTime = view([{event_type: "mission.resumed", created_at: ""}]);
cases.whitespace = view([{event_type: "mission.resumed", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "mission.resumed", created_at: 0}]);
cases.numericNow = view([{event_type: "mission.resumed", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "mission.resumed", created_at: "0"}]);
cases.epoch = view([{event_type: "mission.resumed", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "mission.resumed", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "mission.resumed", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "mission.resumed", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "mission.resumed", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.resumed", created_at: ""},
]);
cases.nonObject = view(["mission.resumed"]);
cases.spendIgnored = view([
  {event_type: "mission.resumed", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
