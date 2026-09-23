import {
  recordedLlmRetryFeed, llmRetryCountView, LLM_RETRIES_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const retry = (id, extra = {}) => event(id, "llm.retry", {
  attempt: 1, max_attempts: 4, delay_seconds: 0.5, failure_class: "RATE_LIMIT", error: "429", ...extra,
});
const log = [
  event("s1", "llm.started", {kind: "decision"}),
  retry("r1"),
  event("c1", "llm.completed", {input_tokens: 10, output_tokens: 4}),
  retry("r2", {attempt: 2}),
  event("f1", "llm.failed", {failure_class: "TIMEOUT", attempt: 4}),
  event("o1", "llm.failover", {from: "openai", to: "openrouter"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  retry("r3", {attempt: 3}),
];

const cases = {};
cases.unavailable = LLM_RETRIES_UNAVAILABLE;
cases.hidden = llmRetryCountView(log, {visible: false});
cases.hiddenDefault = llmRetryCountView(log);
cases.preview = llmRetryCountView(log, {visible: false});
cases.missingNull = llmRetryCountView(null, {visible: true});
cases.missingUndefined = llmRetryCountView(undefined, {visible: true});
cases.missingObject = llmRetryCountView({retries: 4, events: []}, {visible: true});
cases.empty = llmRetryCountView([], {visible: true});
cases.counted = llmRetryCountView(log, {visible: true});
cases.ignoresStarted = llmRetryCountView([event("only", "llm.started", {attempt: 2})], {visible: true});
cases.ignoresCompleted = llmRetryCountView([event("ok", "llm.completed", {retries: 3})], {visible: true});
cases.ignoresFailed = llmRetryCountView([event("fail", "llm.failed", {attempt: 4})], {visible: true});
cases.ignoresFailover = llmRetryCountView([event("move", "llm.failover", {retries: 1})], {visible: true});
cases.ignoresMissionFailed = llmRetryCountView([event("miss", "mission.failed", {failure_class: "TIMEOUT"})], {visible: true});
cases.skipsHoles = llmRetryCountView([null, {payload: {attempt: 2}}, retry("one")], {visible: true});
cases.prefix = llmRetryCountView(recordedLlmRetryFeed(log, 1, true), {visible: true});
cases.prefixFirst = llmRetryCountView(recordedLlmRetryFeed(log, 0, true), {visible: true});
cases.prefixAll = llmRetryCountView(recordedLlmRetryFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmRetryCountView(recordedLlmRetryFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmRetryFeed(log, log.length - 1, false);
cases.unloadedView = llmRetryCountView(recordedLlmRetryFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmRetryFeed([], -1, true);
cases.notArrayLog = recordedLlmRetryFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
