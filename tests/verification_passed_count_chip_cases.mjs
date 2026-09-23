import {
  recordedVerificationPassedFeed, verificationPassedCountView, VERIFICATION_PASSED_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const passed = (id, extra = {}) => event(id, "verification.passed", {verdict: "pass", ...extra});
const log = [
  event("s1", "verification.started", {kind: "verification", passed: 9}),
  passed("p1"),
  event("f1", "verification.failed", {verdict: "fail", passes: 4}),
  event("ep", "verification.evidence.passed", {step: "pytest", passes: 2}),
  passed("p2", {verdict: "inconclusive"}),
  event("l1", "llm.completed", {kind: "verification", passes: 2, token_spent: 1}),
  event("m1", "mission.completed", {summary: "done", passes: 3}),
  event("t1", "tool.completed", {name: "search", passes: 1}),
  passed("p3", {ok: false, passes: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = VERIFICATION_PASSED_UNAVAILABLE;
cases.hidden = verificationPassedCountView(log, {visible: false});
cases.hiddenDefault = verificationPassedCountView(log);
cases.preview = verificationPassedCountView(log, {visible: false});
cases.missingNull = verificationPassedCountView(null, {visible: true});
cases.missingUndefined = verificationPassedCountView(undefined, {visible: true});
cases.missingObject = verificationPassedCountView({passes: 4, events: []}, {visible: true});
cases.empty = verificationPassedCountView([], {visible: true});
cases.counted = verificationPassedCountView(log, {visible: true});
cases.ignoresStarted = verificationPassedCountView([
  event("only", "verification.started", {verdict: "pass", passes: 2}),
], {visible: true});
cases.ignoresFailed = verificationPassedCountView([
  event("bad", "verification.failed", {verdict: "pass", passes: 3}),
], {visible: true});
cases.ignoresEvidencePassed = verificationPassedCountView([
  event("ev", "verification.evidence.passed", {ok: true, passes: 1}),
], {visible: true});
cases.ignoresEvidenceFailed = verificationPassedCountView([
  event("evf", "verification.evidence.failed", {passes: 2}),
], {visible: true});
cases.ignoresEvidenceStarted = verificationPassedCountView([
  event("evs", "verification.evidence.started", {passes: 4}),
], {visible: true});
cases.ignoresLlmCompleted = verificationPassedCountView([
  event("llm", "llm.completed", {kind: "verification", passes: 2, token_spent: 1}),
], {visible: true});
cases.ignoresMissionCompleted = verificationPassedCountView([
  event("done", "mission.completed", {summary: "ok", passes: 6}),
], {visible: true});
cases.ignoresToolCompleted = verificationPassedCountView([
  event("tool", "tool.completed", {name: "search", passes: 1}),
], {visible: true});
cases.countsPassedWithoutVerdict = verificationPassedCountView([
  event("bare", "verification.passed"),
], {visible: true});
cases.onePassNotPayload = verificationPassedCountView([
  passed("big", {passes: 5000, token_spent: 12, ok: false}),
], {visible: true});
cases.skipsHoles = verificationPassedCountView([
  null, {payload: {verdict: "pass", passes: 10}}, passed("one"),
], {visible: true});
cases.unreadableType = verificationPassedCountView([
  passed("ok"),
  {id: "bad", event_type: 4, payload: {passes: 1}},
], {visible: true});
cases.missingType = verificationPassedCountView([
  {id: "blank", payload: {passes: 7}},
  passed("one"),
], {visible: true});
cases.prefix = verificationPassedCountView(recordedVerificationPassedFeed(log, 1, true), {visible: true});
cases.prefixFirst = verificationPassedCountView(recordedVerificationPassedFeed(log, 0, true), {visible: true});
cases.prefixOne = verificationPassedCountView(recordedVerificationPassedFeed(log, 4, true), {visible: true});
cases.prefixAll = verificationPassedCountView(recordedVerificationPassedFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = verificationPassedCountView(recordedVerificationPassedFeed(log, -1, true), {visible: true});
cases.unloaded = recordedVerificationPassedFeed(log, log.length - 1, false);
cases.unloadedView = verificationPassedCountView(recordedVerificationPassedFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedVerificationPassedFeed([], -1, true);
cases.notArrayLog = recordedVerificationPassedFeed({length: 0, passes: 1}, 0, true);

console.log(JSON.stringify(cases));
