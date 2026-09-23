import {
  recordedLlmStartedFeed, llmStartedCountView, LLM_START_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id, extra = {}) => event(id, "llm.started", {kind: "task", ...extra});
const log = [
  event("c0", "llm.completed", {input_tokens: 10, output_tokens: 4}),
  started("s1", {kind: "decision"}),
  event("r1", "llm.retry", {attempt: 1, max_attempts: 4, failure_class: "RATE_LIMIT"}),
  event("f1", "llm.failed", {failure_class: "TIMEOUT", attempt: 4}),
  started("s2"),
  event("o1", "llm.failover", {from_provider: "openai", to_provider: "openrouter"}),
  event("v1", "verification.started"),
  event("t1", "tool.started", {name: "search"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  started("s3", {kind: "verification", starts: 9}),
];

const cases = {};
cases.unavailable = LLM_START_UNAVAILABLE;
cases.hidden = llmStartedCountView(log, {visible: false});
cases.hiddenDefault = llmStartedCountView(log);
cases.preview = llmStartedCountView(log, {visible: false});
cases.missingNull = llmStartedCountView(null, {visible: true});
cases.missingUndefined = llmStartedCountView(undefined, {visible: true});
cases.missingObject = llmStartedCountView({starts: 4, events: []}, {visible: true});
cases.empty = llmStartedCountView([], {visible: true});
cases.counted = llmStartedCountView(log, {visible: true});
cases.ignoresCompleted = llmStartedCountView([
  event("done", "llm.completed", {input_tokens: 8, starts: 2}),
], {visible: true});
cases.ignoresFailed = llmStartedCountView([
  event("fail", "llm.failed", {attempt: 4, starts: 3}),
], {visible: true});
cases.ignoresRetry = llmStartedCountView([
  event("again", "llm.retry", {starts: 1, attempt: 2}),
], {visible: true});
cases.ignoresFailover = llmStartedCountView([
  event("over", "llm.failover", {starts: 2}),
], {visible: true});
cases.ignoresVerification = llmStartedCountView([
  event("ver", "verification.started", {starts: 4}),
], {visible: true});
cases.ignoresTool = llmStartedCountView([
  event("tool", "tool.started", {name: "search", starts: 5}),
], {visible: true});
cases.ignoresMissionFailed = llmStartedCountView([
  event("miss", "mission.failed", {failure_class: "PROVIDER_OUTAGE", starts: 1}),
], {visible: true});
cases.oneStartNotPayload = llmStartedCountView([
  started("big", {starts: 5000, input_tokens: 900, cost: 12}),
], {visible: true});
cases.skipsHoles = llmStartedCountView([null, {payload: {starts: 10}}, started("one")], {visible: true});
cases.unreadableType = llmStartedCountView([
  started("ok"),
  {id: "bad", event_type: 4, payload: {starts: 1}},
], {visible: true});
cases.missingType = llmStartedCountView([
  {id: "blank", payload: {starts: 7}},
  started("one"),
], {visible: true});
cases.prefix = llmStartedCountView(recordedLlmStartedFeed(log, 1, true), {visible: true});
cases.prefixFirst = llmStartedCountView(recordedLlmStartedFeed(log, 0, true), {visible: true});
cases.prefixOne = llmStartedCountView(recordedLlmStartedFeed(log, 4, true), {visible: true});
cases.prefixAll = llmStartedCountView(recordedLlmStartedFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmStartedCountView(recordedLlmStartedFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmStartedFeed(log, log.length - 1, false);
cases.unloadedView = llmStartedCountView(recordedLlmStartedFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmStartedFeed([], -1, true);
cases.notArrayLog = recordedLlmStartedFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
