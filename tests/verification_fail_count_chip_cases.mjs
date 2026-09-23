import {
  recordedVerificationFailFeed, verificationFailCountView, VERIFICATION_FAIL_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "verification.failed", {verdict: "fail", ...extra});
const log = [
  event("s1", "verification.started", {kind: "verification"}),
  failed("f1"),
  event("p1", "verification.passed", {verdict: "pass"}),
  event("e1", "verification.evidence.failed", {step: "pytest"}),
  failed("f2"),
  event("a1", "agent.spawned", {id: "root"}),
  event("m1", "mission.failed", {failure_class: "VERIFICATION_FAILURE"}),
  failed("f3", {verdict: "inconclusive"}),
];

const cases = {};
cases.unavailable = VERIFICATION_FAIL_UNAVAILABLE;
cases.hidden = verificationFailCountView(log, {visible: false});
cases.hiddenDefault = verificationFailCountView(log);
cases.preview = verificationFailCountView(log, {visible: false});
cases.missingNull = verificationFailCountView(null, {visible: true});
cases.missingUndefined = verificationFailCountView(undefined, {visible: true});
cases.missingObject = verificationFailCountView({fails: 4, events: []}, {visible: true});
cases.empty = verificationFailCountView([], {visible: true});
cases.counted = verificationFailCountView(log, {visible: true});
cases.ignoresStarted = verificationFailCountView([event("only", "verification.started", {verdict: "fail"})], {visible: true});
cases.ignoresPassed = verificationFailCountView([event("ok", "verification.passed", {verdict: "pass"})], {visible: true});
cases.ignoresEvidenceFailed = verificationFailCountView([event("ev", "verification.evidence.failed", {ok: false})], {visible: true});
cases.ignoresMissionFailed = verificationFailCountView([event("done", "mission.failed", {failure_class: "VERIFICATION_FAILURE"})], {visible: true});
cases.countsFailedWithoutVerdict = verificationFailCountView([event("bare", "verification.failed")], {visible: true});
cases.skipsHoles = verificationFailCountView([null, {payload: {verdict: "fail"}}, failed("one")], {visible: true});
cases.prefix = verificationFailCountView(recordedVerificationFailFeed(log, 1, true), {visible: true});
cases.prefixFirst = verificationFailCountView(recordedVerificationFailFeed(log, 0, true), {visible: true});
cases.prefixAll = verificationFailCountView(recordedVerificationFailFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = verificationFailCountView(recordedVerificationFailFeed(log, -1, true), {visible: true});
cases.unloaded = recordedVerificationFailFeed(log, log.length - 1, false);
cases.unloadedView = verificationFailCountView(recordedVerificationFailFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedVerificationFailFeed([], -1, true);
cases.notArrayLog = recordedVerificationFailFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
