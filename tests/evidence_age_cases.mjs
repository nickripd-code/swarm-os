import {evidenceAgeChip, EVIDENCE_AGE_UNAVAILABLE, recordedEvidenceAgeFeed} from "../app/static/state.mjs";

const cases = {};
const now = Date.parse("2026-09-23T12:39:04Z");
const visible = {visible: true, now};

function view(feed, options = visible) {
  return evidenceAgeChip(feed, options);
}

cases.unavailable = EVIDENCE_AGE_UNAVAILABLE;
cases.noMission = view(
  [{event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"}],
  {visible: false, now},
);
cases.preview = view(
  [{event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"}],
  {now},
);
cases.missingNull = view(null);
cases.missingUndefined = view(undefined);
cases.missingObject = view({length: 1});
cases.empty = view([]);
cases.cursorBefore = view(recordedEvidenceAgeFeed([
  {id: 1, event_type: "verification.evidence.started", created_at: "2026-09-23T12:35:04Z"},
], -1, true));
cases.feedNotLoaded = view(recordedEvidenceAgeFeed([
  {id: 1, event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"},
], 0, false));
cases.nonEvidence = view([
  {event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "llm.completed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "budget.updated", created_at: "2026-09-23T12:40:00Z", payload: {known: true, token_spent: 1.25}},
]);
cases.verdictIgnored = view([
  {event_type: "verification.started", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "verification.passed", created_at: "2026-09-23T12:20:00Z"},
  {event_type: "verification.failed", created_at: "2026-09-23T12:30:00Z"},
]);
cases.clock = view([
  {event_type: "mission.started", created_at: "2026-09-23T08:00:00Z"},
  {event_type: "verification.evidence.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04.123456Z", payload: {kind: "pytest", ok: true}},
]);
cases.offset = view([
  {event_type: "verification.evidence.failed", created_at: "2026-09-23T08:35:04-04:00"},
]);
cases.newestByTime = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "verification.evidence.started", created_at: "2026-09-23T12:10:00Z"},
  {event_type: "verification.evidence.failed", created_at: "2026-09-23T12:30:00Z"},
]);
cases.kinds = view([
  {event_type: "verification.evidence.started", created_at: "2026-09-23T12:35:04Z"},
]);
cases.verdictDoesNotOverride = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"},
  {event_type: "verification.failed", created_at: "2026-09-23T12:38:00Z"},
]);
cases.replayPrefix = view(recordedEvidenceAgeFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "verification.evidence.started", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "verification.evidence.passed", created_at: "2026-09-23T12:36:00Z"},
], 1, true));
cases.replayAtLater = view(recordedEvidenceAgeFeed([
  {id: 1, event_type: "mission.started", created_at: "2026-09-23T12:00:00Z"},
  {id: 2, event_type: "verification.evidence.started", created_at: "2026-09-23T12:35:04Z"},
  {id: 3, event_type: "verification.evidence.passed", created_at: "2026-09-23T12:36:00Z"},
], 2, true));
cases.seconds = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:38:05Z"},
]);
cases.justNow = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:39:04Z"},
]);
cases.hours = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T10:39:04Z"},
]);
cases.oneDay = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-22T12:39:04Z"},
]);
cases.micros = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:38:04.100000Z"},
]);
cases.skewOk = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:39:34Z"},
]);
cases.noClock = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"},
], {visible: true});
cases.badNow = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"},
], {visible: true, now: Number.NaN});
cases.zeroNow = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z"},
], {visible: true, now: 0});
cases.future = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:42:04Z"},
]);
cases.missingTime = view([{event_type: "verification.evidence.started"}]);
cases.blankTime = view([{event_type: "verification.evidence.passed", created_at: ""}]);
cases.whitespace = view([{event_type: "verification.evidence.failed", created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{event_type: "verification.evidence.started", created_at: 0}]);
cases.numericNow = view([{event_type: "verification.evidence.failed", created_at: 1758630904000}]);
cases.stringZero = view([{event_type: "verification.evidence.started", created_at: "0"}]);
cases.epoch = view([{event_type: "verification.evidence.passed", created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{event_type: "verification.evidence.passed", created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.naive = view([{event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{event_type: "verification.evidence.passed", created_at: "just now"}]);
cases.impossibleDay = view([{event_type: "verification.evidence.passed", created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {event_type: "verification.evidence.started", created_at: "2026-09-23T12:00:00Z"},
  {event_type: "verification.evidence.passed", created_at: ""},
]);
cases.nonObject = view(["verification.evidence.passed"]);
cases.spendIgnored = view([
  {event_type: "verification.evidence.passed", created_at: "2026-09-23T12:35:04Z", payload: {token_spent: 9, input_tokens: 100}},
]);

console.log(JSON.stringify(cases));
