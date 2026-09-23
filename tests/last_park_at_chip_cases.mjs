import {lastParkAtView, LAST_PARK_NONE, LAST_PARK_UNAVAILABLE, recordedParkAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastParkAtView(feed, options);
}

cases.unavailable = LAST_PARK_UNAVAILABLE;
cases.none = LAST_PARK_NONE;
cases.noMission = view(
  [{event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}}],
  {visible: false},
);
cases.preview = view(
  [{event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}}],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedParkAtFeed([
  {id: 1, event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}},
], -1, true));
cases.feedNotLoaded = view(recordedParkAtFeed([
  {id: 1, event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}},
], 0, false));
cases.nonPark = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.pauseIgnored = view([
  {event_type: "mission.paused", created_at: "2026-09-23T12:10:00Z", payload: {reason: "Execution paused by user"}},
]);
cases.waitingIgnored = view([
  {event_type: "mission.waiting", created_at: "2026-09-23T12:10:00Z", payload: {question_id: "q1", reason: "Waiting for a human answer"}},
  {event_type: "mission.waiting", created_at: "2026-09-23T12:20:00Z", payload: {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}},
]);
cases.failIgnored = view([
  {event_type: "mission.failed", created_at: "2026-09-23T12:30:00Z", payload: {failure_class: "TOOL_FAILURE", error: "tool failed"}},
]);
cases.completeIgnored = view([
  {event_type: "mission.completed", created_at: "2026-09-23T12:40:00Z", payload: {summary: "done"}},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "mission.waiting", created_at: "2026-09-23T12:00:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04.123456Z", payload: {question_id: "q1", question: "Need a domain?"}},
  {event_type: "user.answered", created_at: "2026-09-23T12:40:00Z", payload: {question_id: "q1", answer: "yes"}},
]);
cases.offset = view([
  {event_type: "mission.question", created_at: "2026-09-23T08:35:04-04:00", payload: {question: "Need a domain?"}},
]);
cases.newestByTime = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:50:09Z", payload: {question: "Later ask"}},
  {event_type: "mission.question", created_at: "2026-09-23T12:10:00Z", payload: {question: "Earlier ask"}},
  {event_type: "mission.running", created_at: "2026-09-23T12:55:00Z"},
]);
cases.approvalQuestion = view([
  {event_type: "mission.question", created_at: "2026-09-23T01:02:03Z", payload: {kind: "approval", question: "Approve finish?", approval_action: "finish"}},
]);
cases.waitingDoesNotOverride = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}},
  {event_type: "mission.waiting", created_at: "2026-09-23T13:00:00Z", payload: {question_id: "q1"}},
  {event_type: "mission.paused", created_at: "2026-09-23T13:05:00Z"},
  {event_type: "mission.failed", created_at: "2026-09-23T13:06:00Z", payload: {error: "no"}},
  {event_type: "mission.completed", created_at: "2026-09-23T13:07:00Z", payload: {summary: "done"}},
]);
cases.replayPrefix = view(recordedParkAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.waiting", created_at: "2026-09-23T12:10:00Z", payload: {question_id: "q1"}},
  {id: 3, event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}},
  {id: 4, event_type: "user.answered", created_at: "2026-09-23T12:36:00Z", payload: {question_id: "q1", answer: "yes"}},
], 1, true));
cases.replayAtPark = view(recordedParkAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.waiting", created_at: "2026-09-23T12:10:00Z", payload: {question_id: "q1"}},
  {id: 3, event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}},
  {id: 4, event_type: "user.answered", created_at: "2026-09-23T12:36:00Z", payload: {question_id: "q1", answer: "yes"}},
], 2, true));
cases.replayAfter = view(recordedParkAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "mission.waiting", created_at: "2026-09-23T12:10:00Z", payload: {question_id: "q1"}},
  {id: 3, event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}},
  {id: 4, event_type: "user.answered", created_at: "2026-09-23T12:36:00Z", payload: {question_id: "q1", answer: "yes"}},
], 3, true));
cases.missingTime = view([{event_type: "mission.question", payload: {question: "Need a domain?"}}]);
cases.blankTime = view([{event_type: "mission.question", created_at: "", payload: {question: "Need a domain?"}}]);
cases.whitespace = view([{event_type: "mission.question", created_at: " 2026-09-23T12:35:04Z", payload: {question: "Need a domain?"}}]);
cases.numericZero = view([{event_type: "mission.question", created_at: 0, payload: {question: "Need a domain?"}}]);
cases.numericNow = view([{event_type: "mission.question", created_at: 1758630904000, payload: {question: "Need a domain?"}}]);
cases.stringZero = view([{event_type: "mission.question", created_at: "0", payload: {question: "Need a domain?"}}]);
cases.epoch = view([{event_type: "mission.question", created_at: "1970-01-01T00:00:00Z", payload: {question: "Need a domain?"}}]);
cases.epochFraction = view([{event_type: "mission.question", created_at: "1970-01-01T00:00:00.000000Z", payload: {question: "Need a domain?"}}]);
cases.naive = view([{event_type: "mission.question", created_at: "2026-09-23T12:35:04", payload: {question: "Need a domain?"}}]);
cases.garbage = view([{event_type: "mission.question", created_at: "just now", payload: {question: "Need a domain?"}}]);
cases.impossibleDay = view([{event_type: "mission.question", created_at: "2026-02-31T12:35:04Z", payload: {question: "Need a domain?"}}]);
cases.newestInvalid = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:00:00Z", payload: {question: "Earlier ask"}},
  {event_type: "mission.question", created_at: "", payload: {question: "Broken stamp"}},
]);
cases.nonObject = view(["mission.question"]);
cases.spendIgnored = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question: "Need a domain?", token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
