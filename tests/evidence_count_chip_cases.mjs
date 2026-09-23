import {
  recordedEvidenceFeed, evidenceCountView, EVIDENCE_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id) => event(id, "verification.evidence.started", {kind: "pytest"});
const passed = (id) => event(id, "verification.evidence.passed", {kind: "http"});
const failed = (id) => event(id, "verification.evidence.failed", {kind: "file"});
const log = [
  event("v0", "verification.started", {}),
  started("e1"),
  event("ok", "verification.passed", {verdict: "pass"}),
  passed("e2"),
  event("bad", "verification.failed", {verdict: "fail"}),
  failed("e3"),
  event("miss", "mission.failed", {failure_class: "VERIFICATION_FAILURE"}),
];

const cases = {};
cases.unavailable = EVIDENCE_COUNT_UNAVAILABLE;
cases.hidden = evidenceCountView(log, {visible: false});
cases.hiddenDefault = evidenceCountView(log);
cases.preview = evidenceCountView(log, {visible: false});
cases.missingNull = evidenceCountView(null, {visible: true});
cases.missingUndefined = evidenceCountView(undefined, {visible: true});
cases.missingObject = evidenceCountView({evidence: 4, events: []}, {visible: true});
cases.empty = evidenceCountView([], {visible: true});
cases.counted = evidenceCountView(log, {visible: true});
cases.ignoresVerificationStarted = evidenceCountView([
  event("only", "verification.started", {kind: "pytest"}),
], {visible: true});
cases.ignoresVerificationPassed = evidenceCountView([
  event("pass", "verification.passed", {verdict: "pass"}),
], {visible: true});
cases.ignoresVerificationFailed = evidenceCountView([
  event("fail", "verification.failed", {verdict: "fail"}),
], {visible: true});
cases.ignoresMissionFailed = evidenceCountView([
  event("miss", "mission.failed", {failure_class: "VERIFICATION_FAILURE"}),
], {visible: true});
cases.ignoresBarePrefix = evidenceCountView([
  event("bare", "verification.evidence", {kind: "pytest"}),
], {visible: true});
cases.countsEachKind = evidenceCountView([
  started("a"),
  passed("b"),
  failed("c"),
], {visible: true});
cases.skipsHoles = evidenceCountView([null, {payload: {kind: "pytest"}}, started("one")], {visible: true});
cases.unreadableType = evidenceCountView([
  started("a"),
  {id: "bad", event_type: 3, payload: {kind: "pytest"}},
], {visible: true});
cases.prefix = evidenceCountView(recordedEvidenceFeed(log, 3, true), {visible: true});
cases.prefixFirst = evidenceCountView(recordedEvidenceFeed(log, 0, true), {visible: true});
cases.prefixAll = evidenceCountView(recordedEvidenceFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = evidenceCountView(recordedEvidenceFeed(log, -1, true), {visible: true});
cases.unloaded = recordedEvidenceFeed(log, log.length - 1, false);
cases.unloadedView = evidenceCountView(recordedEvidenceFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedEvidenceFeed([], -1, true);
cases.notArrayLog = recordedEvidenceFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
