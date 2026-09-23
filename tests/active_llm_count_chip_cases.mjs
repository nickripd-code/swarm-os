import {
  recordedActiveLlmFeed, activeLlmCountView, ACTIVE_LLM_UNAVAILABLE,
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
cases.hidden = activeLlmCountView(log, {visible: false});
cases.hiddenDefault = activeLlmCountView(log);
cases.missingNull = activeLlmCountView(null, {visible: true});
cases.missingUndefined = activeLlmCountView(undefined, {visible: true});
cases.missingObject = activeLlmCountView({input_tokens: 12, calls: 4}, {visible: true});
cases.empty = activeLlmCountView([], {visible: true});
cases.oneOpen = activeLlmCountView([started("only", "decision")], {visible: true});
cases.twoOpen = activeLlmCountView([
  started("a", "decision", "agent-a"),
  started("b", "work", "agent-b"),
], {visible: true});
cases.matchedComplete = activeLlmCountView([
  started("a", "decision"),
  completed("b", "decision", "agent-a", {input_tokens: 900, output_tokens: 40}),
], {visible: true});
cases.matchedFailed = activeLlmCountView([
  started("a", "decision"),
  failed("b", "decision"),
], {visible: true});
cases.retryKeepsOpen = activeLlmCountView([
  started("a", "decision"),
  retry("b", "decision"),
], {visible: true});
cases.failoverKeepsOpen = activeLlmCountView([
  started("a", "decision"),
  failover("b", "decision"),
], {visible: true});
cases.retryThenComplete = activeLlmCountView([
  started("a", "work", "agent-b"),
  retry("b", "work", "agent-b"),
  failover("c", "work", "agent-b"),
  completed("d", "work", "agent-b"),
], {visible: true});
cases.sameActorStack = activeLlmCountView([
  started("a", "decision"),
  started("b", "decision"),
  completed("c", "decision"),
], {visible: true});
cases.otherKindDoesNotClose = activeLlmCountView([
  started("a", "decision"),
  completed("b", "work"),
], {visible: true});
cases.otherActorDoesNotClose = activeLlmCountView([
  started("a", "decision", "agent-a"),
  completed("b", "decision", "agent-b"),
], {visible: true});
cases.prefixOpen = activeLlmCountView(recordedActiveLlmFeed(log, 0, true), {visible: true});
cases.prefixClosed = activeLlmCountView(recordedActiveLlmFeed(log, 1, true), {visible: true});
cases.prefixMid = activeLlmCountView(recordedActiveLlmFeed(log, 2, true), {visible: true});
cases.prefixRetry = activeLlmCountView(recordedActiveLlmFeed(log, 3, true), {visible: true});
cases.prefixAll = activeLlmCountView(recordedActiveLlmFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = activeLlmCountView(recordedActiveLlmFeed(log, -1, true), {visible: true});
cases.unloaded = activeLlmCountView(recordedActiveLlmFeed(log, log.length - 1, false), {visible: true});
cases.unloadedMissingFlag = activeLlmCountView(recordedActiveLlmFeed([], 0, undefined), {visible: true});
cases.holes = activeLlmCountView([null, {payload: {input_tokens: 5}}, started("one", "decision")], {visible: true});
cases.orphanCompleted = activeLlmCountView([
  completed("c", "decision"),
], {visible: true});
cases.orphanFailed = activeLlmCountView([
  failed("f", "decision"),
], {visible: true});
cases.orphanRetry = activeLlmCountView([
  retry("r", "decision"),
], {visible: true});
cases.missingKind = activeLlmCountView([
  event("a", "llm.started", {model: "demo"}),
], {visible: true});
cases.missingActor = activeLlmCountView([
  {...started("a", "decision"), actor_id: null},
], {visible: true});
cases.emptyKind = activeLlmCountView([
  event("a", "llm.started", {kind: "", model: "demo"}),
], {visible: true});
cases.missingId = activeLlmCountView([
  {...started("a", "decision"), id: ""},
], {visible: true});
cases.duplicateId = activeLlmCountView([
  started("same", "decision"),
  started("same", "decision"),
], {visible: true});
cases.ignoresNonLlm = activeLlmCountView([
  event("m", "mission.started", {kind: "decision"}),
  event("t", "tool.started", {tool: "echo", used: 4, kind: "decision"}),
  event("u", "budget.updated", {token_spent: 9, input_tokens: 12}),
], {visible: true});

console.log(JSON.stringify({unavailable: ACTIVE_LLM_UNAVAILABLE, cases}));
