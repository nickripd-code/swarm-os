import {
  recordedVerificationPassRateFeed, verificationPassRateView, VERIFICATION_PASS_RATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "verification.failed", {reason: "mismatch", attempt: 9, ...extra});
const passed = (id, extra = {}) => event(id, "verification.passed", {verdict: "pass", ...extra});
const log = [
  event("s1", "verification.started", {failed: 4, passed: 9}),
  event("es", "verification.evidence.started"),
  event("ef", "verification.evidence.failed", {check: "pytest"}),
  failed("f1"),
  passed("p1"),
  event("ep", "verification.evidence.passed"),
  failed("f2"),
  event("a1", "agent.spawned", {id: "root", status: "running"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "VERIFICATION_FAILURE"}),
  event("l1", "llm.failed", {kind: "verification"}),
  event("l2", "llm.completed", {kind: "verification"}),
  event("t1", "tool.failed", {tool: "echo"}),
  passed("p2"),
];

const cases = {};
cases.unavailable = VERIFICATION_PASS_RATE_UNAVAILABLE;
cases.hidden = verificationPassRateView(log, {visible: false});
cases.hiddenDefault = verificationPassRateView(log);
cases.preview = verificationPassRateView(log, {visible: false});
cases.missingNull = verificationPassRateView(null, {visible: true});
cases.missingUndefined = verificationPassRateView(undefined, {visible: true});
cases.missingObject = verificationPassRateView({verification: {failed: 4, passed: 1}, events: []}, {visible: true});
cases.empty = verificationPassRateView([], {visible: true});
cases.counted = verificationPassRateView(log, {visible: true});
cases.startedOnly = verificationPassRateView([
  event("only", "verification.started", {failed: 3, passed: 0}),
  event("ev", "verification.evidence.failed", {failed: 2}),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.passesOnly = verificationPassRateView([
  passed("ok1"),
  event("bad", "verification.passed", {ok: false}),
], {visible: true});
cases.half = verificationPassRateView([failed("f"), passed("a")], {visible: true});
cases.allFailed = verificationPassRateView([failed("f1"), failed("f2")], {visible: true});
cases.third = verificationPassRateView([failed("f"), passed("a"), passed("b")], {visible: true});
cases.evidenceIgnored = verificationPassRateView([
  event("s", "verification.started"),
  event("ef1", "verification.evidence.failed"),
  event("ef2", "verification.evidence.failed"),
  event("ep", "verification.evidence.passed"),
  passed("ok"),
], {visible: true});
cases.tiny = verificationPassRateView([passed("p"), ...Array.from({length: 100000}, (_, i) => failed("f" + i))], {visible: true});
cases.skipsHoles = verificationPassRateView([null, {payload: {failed: 3, rate: 1}}, failed("one"), passed("two")], {visible: true});
cases.prefix = verificationPassRateView(recordedVerificationPassRateFeed(log, 4, true), {visible: true});
cases.prefixFirst = verificationPassRateView(recordedVerificationPassRateFeed(log, 2, true), {visible: true});
cases.prefixAll = verificationPassRateView(recordedVerificationPassRateFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = verificationPassRateView(recordedVerificationPassRateFeed(log, -1, true), {visible: true});
cases.unloaded = recordedVerificationPassRateFeed(log, log.length - 1, false);
cases.unloadedView = verificationPassRateView(recordedVerificationPassRateFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedVerificationPassRateFeed([], -1, true);
cases.notArrayLog = recordedVerificationPassRateFeed({length: 0, failed: 1, passed: 1}, 0, true);

console.log(JSON.stringify(cases));
