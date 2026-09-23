import {
  recordedVerificationPassFeed, verificationPassCountView, VERIFICATION_PASS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const passed = (id, extra = {}) => event(id, "verification.passed", {verdict: "pass", ...extra});
const log = [
  event("s1", "verification.started", {kind: "verification"}),
  passed("p1"),
  event("f1", "verification.failed", {verdict: "fail"}),
  event("e1", "verification.evidence.passed", {step: "pytest"}),
  passed("p2"),
  event("a1", "agent.spawned", {id: "root"}),
  event("m1", "mission.completed", {summary: "done"}),
  passed("p3", {verdict: "inconclusive"}),
];

const cases = {};
cases.unavailable = VERIFICATION_PASS_UNAVAILABLE;
cases.hidden = verificationPassCountView(log, {visible: false});
cases.hiddenDefault = verificationPassCountView(log);
cases.preview = verificationPassCountView(log, {visible: false});
cases.missingNull = verificationPassCountView(null, {visible: true});
cases.missingUndefined = verificationPassCountView(undefined, {visible: true});
cases.missingObject = verificationPassCountView({passes: 4, events: []}, {visible: true});
cases.empty = verificationPassCountView([], {visible: true});
cases.counted = verificationPassCountView(log, {visible: true});
cases.ignoresStarted = verificationPassCountView([event("only", "verification.started", {verdict: "pass"})], {visible: true});
cases.ignoresFailed = verificationPassCountView([event("bad", "verification.failed", {verdict: "fail"})], {visible: true});
cases.ignoresEvidencePassed = verificationPassCountView([event("ev", "verification.evidence.passed", {ok: true})], {visible: true});
cases.ignoresMissionCompleted = verificationPassCountView([event("done", "mission.completed", {summary: "ok"})], {visible: true});
cases.countsPassedWithoutVerdict = verificationPassCountView([event("bare", "verification.passed")], {visible: true});
cases.skipsHoles = verificationPassCountView([null, {payload: {verdict: "pass"}}, passed("one")], {visible: true});
cases.prefix = verificationPassCountView(recordedVerificationPassFeed(log, 1, true), {visible: true});
cases.prefixFirst = verificationPassCountView(recordedVerificationPassFeed(log, 0, true), {visible: true});
cases.prefixAll = verificationPassCountView(recordedVerificationPassFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = verificationPassCountView(recordedVerificationPassFeed(log, -1, true), {visible: true});
cases.unloaded = recordedVerificationPassFeed(log, log.length - 1, false);
cases.unloadedView = verificationPassCountView(recordedVerificationPassFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedVerificationPassFeed([], -1, true);
cases.notArrayLog = recordedVerificationPassFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
