import {
  recordedLlmSuccessFeed, llmSuccessCountView, LLM_OK_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const completed = (id, extra = {}) => event(id, "llm.completed", {
  input_tokens: 10, output_tokens: 4, ...extra,
});
const log = [
  event("s1", "llm.started", {kind: "decision"}),
  event("r1", "llm.retry", {attempt: 1, max_attempts: 4, failure_class: "RATE_LIMIT"}),
  completed("c1"),
  event("o1", "llm.failover", {from_provider: "openai", to_provider: "openrouter"}),
  event("f1", "llm.failed", {failure_class: "TIMEOUT", attempt: 4}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  completed("c2", {input_tokens: 40, output_tokens: 8}),
  event("t1", "tool.completed", {name: "search"}),
  completed("c3"),
];

const cases = {};
cases.unavailable = LLM_OK_UNAVAILABLE;
cases.hidden = llmSuccessCountView(log, {visible: false});
cases.hiddenDefault = llmSuccessCountView(log);
cases.preview = llmSuccessCountView(log, {visible: false});
cases.missingNull = llmSuccessCountView(null, {visible: true});
cases.missingUndefined = llmSuccessCountView(undefined, {visible: true});
cases.missingObject = llmSuccessCountView({successes: 4, events: []}, {visible: true});
cases.empty = llmSuccessCountView([], {visible: true});
cases.counted = llmSuccessCountView(log, {visible: true});
cases.ignoresStarted = llmSuccessCountView([event("only", "llm.started", {successes: 2})], {visible: true});
cases.ignoresFailed = llmSuccessCountView([event("fail", "llm.failed", {attempt: 4, successes: 3})], {visible: true});
cases.ignoresRetry = llmSuccessCountView([event("again", "llm.retry", {successes: 1, attempt: 2})], {visible: true});
cases.ignoresFailover = llmSuccessCountView([event("over", "llm.failover", {successes: 2})], {visible: true});
cases.ignoresMissionFailed = llmSuccessCountView([event("miss", "mission.failed", {failure_class: "PROVIDER_OUTAGE"})], {visible: true});
cases.ignoresUnrelated = llmSuccessCountView([event("tool", "tool.completed", {name: "search"})], {visible: true});
cases.oneCompletionNotTokens = llmSuccessCountView([
  completed("big", {input_tokens: 5000, output_tokens: 900, cost: 12}),
], {visible: true});
cases.skipsHoles = llmSuccessCountView([null, {payload: {input_tokens: 10}}, completed("one")], {visible: true});
cases.prefix = llmSuccessCountView(recordedLlmSuccessFeed(log, 1, true), {visible: true});
cases.prefixFirst = llmSuccessCountView(recordedLlmSuccessFeed(log, 0, true), {visible: true});
cases.prefixOne = llmSuccessCountView(recordedLlmSuccessFeed(log, 2, true), {visible: true});
cases.prefixAll = llmSuccessCountView(recordedLlmSuccessFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmSuccessCountView(recordedLlmSuccessFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmSuccessFeed(log, log.length - 1, false);
cases.unloadedView = llmSuccessCountView(recordedLlmSuccessFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmSuccessFeed([], -1, true);
cases.notArrayLog = recordedLlmSuccessFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
