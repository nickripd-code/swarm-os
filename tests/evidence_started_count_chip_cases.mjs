import {
  recordedEvidenceStartedCountFeed, evidenceStartedCountView, EVIDENCE_STARTED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id, extra = {}) => event(id, "verification.evidence.started", {
  count: 2, kinds: ["pytest", "http"], ...extra,
});
const log = [
  event("mission", "mission.started", {mode: "runtime"}),
  event("verify", "verification.started"),
  started("e1"),
  event("passed-step", "verification.evidence.passed", {ok: true, kind: "pytest"}),
  event("failed-step", "verification.evidence.failed", {ok: false, kind: "http"}),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  started("e2"),
  event("verdict-pass", "verification.passed"),
  event("verdict-fail", "verification.failed", {failure_class: "VERIFICATION_FAILURE"}),
  event("budget", "budget.updated", {known: true, token_spent: 9}),
  started("e3", {count: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = EVIDENCE_STARTED_COUNT_UNAVAILABLE;
cases.hidden = evidenceStartedCountView(log, {visible: false});
cases.hiddenDefault = evidenceStartedCountView(log);
cases.preview = evidenceStartedCountView(log, {visible: false});
cases.missingNull = evidenceStartedCountView(null, {visible: true});
cases.missingUndefined = evidenceStartedCountView(undefined, {visible: true});
cases.missingObject = evidenceStartedCountView({started: 4, events: []}, {visible: true});
cases.empty = evidenceStartedCountView([], {visible: true});
cases.counted = evidenceStartedCountView(log, {visible: true});
cases.ignoresEvidencePassed = evidenceStartedCountView([
  event("passed-step", "verification.evidence.passed", {count: 3, ok: true}),
], {visible: true});
cases.ignoresEvidenceFailed = evidenceStartedCountView([
  event("failed-step", "verification.evidence.failed", {count: 3, ok: false}),
], {visible: true});
cases.ignoresVerificationStarted = evidenceStartedCountView([
  event("verify", "verification.started", {count: 4}),
], {visible: true});
cases.ignoresVerificationPassed = evidenceStartedCountView([
  event("verdict-pass", "verification.passed", {count: 1}),
], {visible: true});
cases.ignoresVerificationFailed = evidenceStartedCountView([
  event("verdict-fail", "verification.failed", {count: 1}),
], {visible: true});
cases.ignoresToolStarted = evidenceStartedCountView([
  event("tool", "tool.started", {count: 6}),
], {visible: true});
cases.ignoresMissionStarted = evidenceStartedCountView([
  event("mission", "mission.started", {count: 3, status: "running"}),
], {visible: true});
cases.ignoresBudget = evidenceStartedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, count: 1}),
], {visible: true});
cases.oneStartedNotPayload = evidenceStartedCountView([
  started("big", {count: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = evidenceStartedCountView([null, {payload: {count: 10}}, started("one")], {visible: true});
cases.unreadableType = evidenceStartedCountView([
  started("ok"),
  {id: "bad", event_type: 4, payload: {count: 1}},
], {visible: true});
cases.missingType = evidenceStartedCountView([
  {id: "blank", payload: {count: 7}},
  started("one"),
], {visible: true});
cases.prefix = evidenceStartedCountView(recordedEvidenceStartedCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = evidenceStartedCountView(recordedEvidenceStartedCountFeed(log, 0, true), {visible: true});
cases.prefixTwo = evidenceStartedCountView(recordedEvidenceStartedCountFeed(log, 6, true), {visible: true});
cases.prefixAll = evidenceStartedCountView(recordedEvidenceStartedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = evidenceStartedCountView(recordedEvidenceStartedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedEvidenceStartedCountFeed(log, log.length - 1, false);
cases.unloadedView = evidenceStartedCountView(recordedEvidenceStartedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedEvidenceStartedCountFeed([], -1, true);
cases.notArrayLog = recordedEvidenceStartedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
