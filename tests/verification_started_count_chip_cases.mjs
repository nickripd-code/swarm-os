import {
  recordedVerificationStartedFeed, verificationStartedCountView, VERIFICATION_STARTED_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id, extra = {}) => event(id, "verification.started", {summary: "claim", ...extra});
const log = [
  event("p0", "verification.passed", {verdict: "pass"}),
  started("s1"),
  event("e1", "verification.evidence.started", {kind: "pytest"}),
  event("f1", "verification.failed", {verdict: "fail"}),
  started("s2"),
  event("ep", "verification.evidence.passed", {kind: "http"}),
  event("t1", "tool.started", {name: "search"}),
  event("l1", "llm.started", {kind: "verification"}),
  event("m1", "mission.completed", {summary: "done"}),
  started("s3", {starts: 9, outputs: 2}),
];

const cases = {};
cases.unavailable = VERIFICATION_STARTED_UNAVAILABLE;
cases.hidden = verificationStartedCountView(log, {visible: false});
cases.hiddenDefault = verificationStartedCountView(log);
cases.preview = verificationStartedCountView(log, {visible: false});
cases.missingNull = verificationStartedCountView(null, {visible: true});
cases.missingUndefined = verificationStartedCountView(undefined, {visible: true});
cases.missingObject = verificationStartedCountView({starts: 4, events: []}, {visible: true});
cases.empty = verificationStartedCountView([], {visible: true});
cases.counted = verificationStartedCountView(log, {visible: true});
cases.ignoresPassed = verificationStartedCountView([
  event("pass", "verification.passed", {starts: 2}),
], {visible: true});
cases.ignoresFailed = verificationStartedCountView([
  event("fail", "verification.failed", {starts: 3}),
], {visible: true});
cases.ignoresEvidenceStarted = verificationStartedCountView([
  event("ev", "verification.evidence.started", {starts: 1}),
], {visible: true});
cases.ignoresEvidencePassed = verificationStartedCountView([
  event("evp", "verification.evidence.passed", {starts: 2}),
], {visible: true});
cases.ignoresEvidenceFailed = verificationStartedCountView([
  event("evf", "verification.evidence.failed", {starts: 4}),
], {visible: true});
cases.ignoresTool = verificationStartedCountView([
  event("tool", "tool.started", {name: "search", starts: 5}),
], {visible: true});
cases.ignoresLlm = verificationStartedCountView([
  event("llm", "llm.started", {kind: "task", starts: 6}),
], {visible: true});
cases.ignoresMissionCompleted = verificationStartedCountView([
  event("done", "mission.completed", {starts: 1}),
], {visible: true});
cases.oneStartNotPayload = verificationStartedCountView([
  started("big", {starts: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = verificationStartedCountView([null, {payload: {starts: 10}}, started("one")], {visible: true});
cases.unreadableType = verificationStartedCountView([
  started("ok"),
  {id: "bad", event_type: 4, payload: {starts: 1}},
], {visible: true});
cases.missingType = verificationStartedCountView([
  {id: "blank", payload: {starts: 7}},
  started("one"),
], {visible: true});
cases.prefix = verificationStartedCountView(recordedVerificationStartedFeed(log, 1, true), {visible: true});
cases.prefixFirst = verificationStartedCountView(recordedVerificationStartedFeed(log, 0, true), {visible: true});
cases.prefixOne = verificationStartedCountView(recordedVerificationStartedFeed(log, 4, true), {visible: true});
cases.prefixAll = verificationStartedCountView(recordedVerificationStartedFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = verificationStartedCountView(recordedVerificationStartedFeed(log, -1, true), {visible: true});
cases.unloaded = recordedVerificationStartedFeed(log, log.length - 1, false);
cases.unloadedView = verificationStartedCountView(recordedVerificationStartedFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedVerificationStartedFeed([], -1, true);
cases.notArrayLog = recordedVerificationStartedFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
