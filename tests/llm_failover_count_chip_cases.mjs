import {
  recordedLlmFailoverFeed, llmFailoverCountView, LLM_FAILOVERS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failover = (id, extra = {}) => event(id, "llm.failover", {
  from_provider: "openai", to_provider: "openrouter", reason: "PROVIDER_OUTAGE", ...extra,
});
const log = [
  event("s1", "llm.started", {kind: "decision"}),
  event("r1", "llm.retry", {attempt: 1, max_attempts: 4, failure_class: "RATE_LIMIT"}),
  event("c1", "llm.completed", {input_tokens: 10, output_tokens: 4}),
  failover("o1"),
  event("f1", "llm.failed", {failure_class: "TIMEOUT", attempt: 4}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  failover("o2", {to_provider: "anthropic"}),
  event("t1", "tool.completed", {name: "search"}),
  failover("o3", {to_provider: "mistral"}),
];

const cases = {};
cases.unavailable = LLM_FAILOVERS_UNAVAILABLE;
cases.hidden = llmFailoverCountView(log, {visible: false});
cases.hiddenDefault = llmFailoverCountView(log);
cases.preview = llmFailoverCountView(log, {visible: false});
cases.missingNull = llmFailoverCountView(null, {visible: true});
cases.missingUndefined = llmFailoverCountView(undefined, {visible: true});
cases.missingObject = llmFailoverCountView({failovers: 4, events: []}, {visible: true});
cases.empty = llmFailoverCountView([], {visible: true});
cases.counted = llmFailoverCountView(log, {visible: true});
cases.ignoresStarted = llmFailoverCountView([event("only", "llm.started", {failovers: 2})], {visible: true});
cases.ignoresCompleted = llmFailoverCountView([event("ok", "llm.completed", {failovers: 3})], {visible: true});
cases.ignoresFailed = llmFailoverCountView([event("fail", "llm.failed", {attempt: 4})], {visible: true});
cases.ignoresRetry = llmFailoverCountView([event("again", "llm.retry", {failovers: 1, attempt: 2})], {visible: true});
cases.ignoresMissionFailed = llmFailoverCountView([event("miss", "mission.failed", {failure_class: "PROVIDER_OUTAGE"})], {visible: true});
cases.ignoresUnrelated = llmFailoverCountView([event("tool", "tool.completed", {name: "search"})], {visible: true});
cases.skipsHoles = llmFailoverCountView([null, {payload: {from_provider: "openai"}}, failover("one")], {visible: true});
cases.prefix = llmFailoverCountView(recordedLlmFailoverFeed(log, 1, true), {visible: true});
cases.prefixFirst = llmFailoverCountView(recordedLlmFailoverFeed(log, 0, true), {visible: true});
cases.prefixOne = llmFailoverCountView(recordedLlmFailoverFeed(log, 3, true), {visible: true});
cases.prefixAll = llmFailoverCountView(recordedLlmFailoverFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmFailoverCountView(recordedLlmFailoverFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmFailoverFeed(log, log.length - 1, false);
cases.unloadedView = llmFailoverCountView(recordedLlmFailoverFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmFailoverFeed([], -1, true);
cases.notArrayLog = recordedLlmFailoverFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
