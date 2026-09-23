import {
  recordedActiveVerificationFeed, activeVerificationCountView, ACTIVE_VERIFY_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}, actor = "root-a") {
  return {id, event_type: type, payload, actor_id: actor, created_at: "2026-01-01T00:00:00Z"};
}
function started(id, actor = "root-a", extra = {}) {
  return event(id, "verification.started", {summary: "claimed", outputs: 1, ...extra}, actor);
}
function passed(id, actor = "root-a", extra = {}) {
  return event(id, "verification.passed", {verdict: "pass", rationale: "grounded", ...extra}, actor);
}
function failed(id, actor = "root-a", extra = {}) {
  return event(id, "verification.failed", {verdict: "fail", rationale: "unsupported", failure_class: "VERIFICATION_FAILURE", ...extra}, actor);
}

const log = [
  started("s1"),
  passed("p1"),
  started("s2", "root-b"),
  event("e2", "verification.evidence.started", {count: 1, kinds: ["pytest"]}, "root-b"),
  event("e3", "verification.evidence.passed", {ok: true, kind: "pytest"}, "root-b"),
  started("s3"),
];

const cases = {};
cases.hidden = activeVerificationCountView(log, {visible: false});
cases.hiddenDefault = activeVerificationCountView(log);
cases.missingNull = activeVerificationCountView(null, {visible: true});
cases.missingUndefined = activeVerificationCountView(undefined, {visible: true});
cases.missingObject = activeVerificationCountView({outputs: 4, calls: 2}, {visible: true});
cases.empty = activeVerificationCountView([], {visible: true});
cases.oneOpen = activeVerificationCountView([started("only", "root-a", {outputs: 4})], {visible: true});
cases.twoOpen = activeVerificationCountView([
  started("a", "root-a"),
  started("b", "root-b"),
], {visible: true});
cases.matchedPass = activeVerificationCountView([
  started("a"),
  passed("b", "root-a", {evidence: ["note"], outputs: 9}),
], {visible: true});
cases.matchedFail = activeVerificationCountView([
  started("a"),
  failed("b"),
], {visible: true});
cases.evidenceDoesNotOpenOrClose = activeVerificationCountView([
  started("a", "root-b"),
  event("e", "verification.evidence.started", {count: 3, kinds: ["pytest"]}, "root-b"),
  event("p", "verification.evidence.passed", {ok: true}, "root-b"),
  event("f", "verification.evidence.failed", {ok: false}, "root-b"),
], {visible: true});
cases.evidenceAloneIsZero = activeVerificationCountView([
  event("e", "verification.evidence.started", {count: 2}),
  event("p", "verification.evidence.passed", {ok: true}),
  event("f", "verification.evidence.failed", {ok: false}),
], {visible: true});
cases.sameActorStack = activeVerificationCountView([
  started("a"),
  started("b"),
  passed("c"),
], {visible: true});
cases.otherActorDoesNotClose = activeVerificationCountView([
  started("a", "root-a"),
  passed("b", "root-b"),
], {visible: true});
cases.prefixOpen = activeVerificationCountView(recordedActiveVerificationFeed(log, 0, true), {visible: true});
cases.prefixClosed = activeVerificationCountView(recordedActiveVerificationFeed(log, 1, true), {visible: true});
cases.prefixOtherOpen = activeVerificationCountView(recordedActiveVerificationFeed(log, 2, true), {visible: true});
cases.prefixEvidence = activeVerificationCountView(recordedActiveVerificationFeed(log, 4, true), {visible: true});
cases.prefixAll = activeVerificationCountView(recordedActiveVerificationFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = activeVerificationCountView(recordedActiveVerificationFeed(log, -1, true), {visible: true});
cases.unloaded = activeVerificationCountView(recordedActiveVerificationFeed(log, log.length - 1, false), {visible: true});
cases.unloadedMissingFlag = activeVerificationCountView(recordedActiveVerificationFeed([], 0, undefined), {visible: true});
cases.holes = activeVerificationCountView([null, {payload: {outputs: 5}}, started("one")], {visible: true});
cases.orphanPassed = activeVerificationCountView([
  passed("p"),
], {visible: true});
cases.orphanFailed = activeVerificationCountView([
  failed("f"),
], {visible: true});
cases.missingActor = activeVerificationCountView([
  {...started("a"), actor_id: null},
], {visible: true});
cases.emptyActor = activeVerificationCountView([
  {...started("a"), actor_id: ""},
], {visible: true});
cases.missingId = activeVerificationCountView([
  {...started("a"), id: ""},
], {visible: true});
cases.duplicateId = activeVerificationCountView([
  started("same"),
  started("same"),
], {visible: true});
cases.ignoresNonVerification = activeVerificationCountView([
  event("m", "mission.completed", {outputs: 4}),
  event("t", "tool.started", {tool: "echo", used: 1}),
  event("l", "llm.started", {kind: "verification", model: "demo"}),
  event("u", "budget.updated", {token_spent: 9}),
], {visible: true});
cases.missionCompletedDoesNotClose = activeVerificationCountView([
  started("a"),
  event("m", "mission.completed", {}),
], {visible: true});

console.log(JSON.stringify({unavailable: ACTIVE_VERIFY_UNAVAILABLE, cases}));
