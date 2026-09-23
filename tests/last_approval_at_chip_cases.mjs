import {lastApprovalAtView, LAST_APPROVAL_AT_NONE, LAST_APPROVAL_AT_UNAVAILABLE, recordedApprovalAtFeed} from "../app/static/state.mjs";

const cases = {};
const visible = {visible: true};

function view(feed, options = visible) {
  return lastApprovalAtView(feed, options);
}

function approval(type, created_at, extra = {}) {
  return {
    event_type: type,
    created_at,
    payload: {kind: "approval", approval_action: extra.approval_action || "finish", question_id: extra.question_id || "q-fin", ...extra.payload},
  };
}

cases.unavailable = LAST_APPROVAL_AT_UNAVAILABLE;
cases.none = LAST_APPROVAL_AT_NONE;
cases.noMission = view(
  [approval("mission.question", "2026-09-23T12:35:04Z")],
  {visible: false},
);
cases.preview = view(
  [approval("user.answered", "2026-09-23T12:35:04Z")],
  {},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedApprovalAtFeed([
  approval("mission.question", "2026-09-23T12:35:04Z"),
], -1, true));
cases.feedNotLoaded = view(recordedApprovalAtFeed([
  approval("user.answered", "2026-09-23T12:35:04Z"),
], 0, false));
cases.nonApproval = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {kind: "question", question_id: "q-ask"}},
  {event_type: "user.answered", created_at: "2026-09-23T12:36:00Z", payload: {kind: "question", question_id: "q-ask"}},
  {event_type: "mission.waiting", created_at: "2026-09-23T12:37:00Z", payload: {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}},
  {event_type: "user.answer_consumed", created_at: "2026-09-23T12:38:00Z", payload: {question_id: "q-fin", kind: "approval"}},
  {event_type: "approval.requested", created_at: "2026-09-23T12:39:00Z", payload: {kind: "approval"}},
  {event_type: "llm.completed", created_at: "2026-09-23T12:40:00Z", payload: {kind: "approval"}},
  {event_type: "budget.updated", created_at: "2026-09-23T12:41:00Z", payload: {known: true, token_spent: 1.25, kind: "approval"}},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  approval("mission.question", "2026-09-23T12:00:00Z", {approval_action: "org_change"}),
  approval("user.answered", "2026-09-23T12:35:04.123456Z", {approval_action: "finish"}),
]);
cases.offset = view([
  approval("mission.waiting", "2026-09-23T08:35:04-04:00", {approval_action: "live_payment"}),
]);
cases.newestByTime = view([
  approval("user.answered", "2026-09-23T12:40:00Z"),
  approval("mission.question", "2026-09-23T12:10:00Z"),
  approval("mission.waiting", "2026-09-23T12:50:09Z"),
]);
cases.kinds = view([
  approval("mission.question", "2026-09-23T01:02:03Z", {approval_action: "org_change"}),
]);
cases.replayPrefix = view(recordedApprovalAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...approval("mission.question", "2026-09-23T12:35:04Z")},
  {id: 3, ...approval("user.answered", "2026-09-23T12:36:00Z")},
], 1, true));
cases.replayAtLater = view(recordedApprovalAtFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, ...approval("mission.question", "2026-09-23T12:35:04Z")},
  {id: 3, ...approval("user.answered", "2026-09-23T12:36:00Z")},
], 2, true));
cases.questionThenApproval = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:00:00Z", payload: {kind: "question", question_id: "q-ask"}},
  approval("mission.question", "2026-09-23T12:35:04Z"),
]);
cases.missingTime = view([approval("mission.question", undefined)]);
cases.blankTime = view([approval("user.answered", "")]);
cases.whitespace = view([approval("mission.waiting", " 2026-09-23T12:35:04Z")]);
cases.numericZero = view([approval("mission.question", 0)]);
cases.numericNow = view([approval("user.answered", 1758630904000)]);
cases.stringZero = view([approval("mission.waiting", "0")]);
cases.epoch = view([approval("mission.question", "1970-01-01T00:00:00Z")]);
cases.epochFraction = view([approval("user.answered", "1970-01-01T00:00:00.000000Z")]);
cases.naive = view([approval("mission.waiting", "2026-09-23T12:35:04")]);
cases.garbage = view([approval("mission.question", "just now")]);
cases.impossibleDay = view([approval("user.answered", "2026-02-31T12:35:04Z")]);
cases.newestInvalid = view([
  approval("mission.question", "2026-09-23T12:00:00Z"),
  approval("user.answered", ""),
]);
cases.nonObject = view(["mission.question"]);
cases.missingKind = view([
  {event_type: "mission.question", created_at: "2026-09-23T12:35:04Z", payload: {question_id: "q-x", question: "Approve?"}},
]);
cases.spendIgnored = view([
  approval("user.answered", "2026-09-23T12:35:04Z", {payload: {token_spent: 9, answer: "approve"}}),
]);

console.log(JSON.stringify(cases));
