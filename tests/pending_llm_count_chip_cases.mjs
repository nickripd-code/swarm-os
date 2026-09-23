import {
  recordedPendingLlmFeed, pendingLlmCountView, PENDING_LLM_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}, actor = "agent-a") {
  return {id, event_type: type, payload, actor_id: actor, created_at: "2026-01-01T00:00:00Z"};
}
function started(id, kind, actor = "agent-a", extra = {}) {
  return event(id, "llm.started", {kind, model: "demo", ...extra}, actor);
}
function completed(id, kind, actor = "agent-a", extra = {}) {
  return event(id, "llm.completed", {kind, model: "demo", input_tokens: 12, output_tokens: 3, ...extra}, actor);
}
function failed(id, kind, actor = "agent-a") {
  return event(id, "llm.failed", {kind, model: "demo", failure_class: "PROVIDER_OUTAGE"}, actor);
}
function retry(id, kind, actor = "agent-a") {
  return event(id, "llm.retry", {kind, model: "demo", attempt: 1}, actor);
}
function failover(id, kind, actor = "agent-a") {
  return event(id, "llm.failover", {kind, model: "other", from_provider: "openai"}, actor);
}

const log = [
  started("s1", "decision"),
  completed("c1", "decision"),
  started("s2", "work", "agent-b"),
  retry("r2", "work", "agent-b"),
  started("s3", "decision"),
];

const cases = {};
cases.hidden = pendingLlmCountView(log, {visible: false});
cases.hiddenDefault = pendingLlmCountView(log);
cases.missingNull = pendingLlmCountView(null, {visible: true});
cases.missingUndefined = pendingLlmCountView(undefined, {visible: true});
cases.missingObject = pendingLlmCountView({input_tokens: 12, calls: 4, token_spent: 1.5}, {visible: true});
cases.empty = pendingLlmCountView([], {visible: true});
cases.oneOpen = pendingLlmCountView([started("only", "decision")], {visible: true});
cases.twoOpen = pendingLlmCountView([
  started("a", "decision", "agent-a"),
  started("b", "work", "agent-b"),
], {visible: true});
cases.matchedComplete = pendingLlmCountView([
  started("a", "decision"),
  completed("b", "decision", "agent-a", {input_tokens: 900, output_tokens: 40}),
], {visible: true});
cases.matchedFailed = pendingLlmCountView([
  started("a", "decision"),
  failed("b", "decision"),
], {visible: true});
cases.retryKeepsOpen = pendingLlmCountView([
  started("a", "decision"),
  retry("b", "decision"),
], {visible: true});
cases.failoverKeepsOpen = pendingLlmCountView([
  started("a", "decision"),
  failover("b", "decision"),
], {visible: true});
cases.retryThenComplete = pendingLlmCountView([
  started("a", "work", "agent-b"),
  retry("b", "work", "agent-b"),
  failover("c", "work", "agent-b"),
  completed("d", "work", "agent-b"),
], {visible: true});
cases.sameActorStack = pendingLlmCountView([
  started("a", "decision"),
  started("b", "decision"),
  completed("c", "decision"),
], {visible: true});
cases.otherKindDoesNotClose = pendingLlmCountView([
  started("a", "decision"),
  completed("b", "work"),
], {visible: true});
cases.otherActorDoesNotClose = pendingLlmCountView([
  started("a", "decision", "agent-a"),
  completed("b", "decision", "agent-b"),
], {visible: true});
cases.prefixOpen = pendingLlmCountView(recordedPendingLlmFeed(log, 0, true), {visible: true});
cases.prefixClosed = pendingLlmCountView(recordedPendingLlmFeed(log, 1, true), {visible: true});
cases.prefixMid = pendingLlmCountView(recordedPendingLlmFeed(log, 2, true), {visible: true});
cases.prefixRetry = pendingLlmCountView(recordedPendingLlmFeed(log, 3, true), {visible: true});
cases.prefixAll = pendingLlmCountView(recordedPendingLlmFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = pendingLlmCountView(recordedPendingLlmFeed(log, -1, true), {visible: true});
cases.unloaded = pendingLlmCountView(recordedPendingLlmFeed(log, log.length - 1, false), {visible: true});
cases.unloadedMissingFlag = pendingLlmCountView(recordedPendingLlmFeed([], 0, undefined), {visible: true});
cases.holes = pendingLlmCountView([null, {payload: {input_tokens: 5}}, started("one", "decision")], {visible: true});
cases.orphanCompleted = pendingLlmCountView([
  completed("c", "decision"),
], {visible: true});
cases.orphanFailed = pendingLlmCountView([
  failed("f", "decision"),
], {visible: true});
cases.orphanRetry = pendingLlmCountView([
  retry("r", "decision"),
], {visible: true});
cases.missingKind = pendingLlmCountView([
  event("a", "llm.started", {model: "demo"}),
], {visible: true});
cases.missingActor = pendingLlmCountView([
  {...started("a", "decision"), actor_id: null},
], {visible: true});
cases.emptyKind = pendingLlmCountView([
  event("a", "llm.started", {kind: "", model: "demo"}),
], {visible: true});
cases.missingId = pendingLlmCountView([
  {...started("a", "decision"), id: ""},
], {visible: true});
cases.duplicateId = pendingLlmCountView([
  started("same", "decision"),
  started("same", "decision"),
], {visible: true});
cases.ignoresNonLlm = pendingLlmCountView([
  event("m", "mission.started", {kind: "decision"}),
  event("t", "tool.started", {tool: "echo", used: 4, kind: "decision"}),
  event("u", "budget.updated", {token_spent: 9, input_tokens: 12}),
], {visible: true});
cases.noModelEvents = pendingLlmCountView([
  event("ms", "model.started", {kind: "decision"}),
  event("mc", "model.completed", {kind: "decision", input_tokens: 8}),
], {visible: true});

console.log(JSON.stringify({unavailable: PENDING_LLM_UNAVAILABLE, cases}));
