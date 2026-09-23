import {
  recordedLlmFailFeed, llmFailCountView, LLM_FAILS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "llm.failed", {error: "timeout", failure_class: "TIMEOUT", ...extra});
const log = [
  event("s1", "llm.started", {kind: "decision"}),
  failed("f1"),
  event("c1", "llm.completed", {input_tokens: 10, output_tokens: 4}),
  failed("f2"),
  event("r1", "llm.retry", {attempt: 1, failure_class: "RATE_LIMIT"}),
  event("o1", "llm.failover", {from: "openai", to: "openrouter"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  failed("f3"),
];

const cases = {};
cases.unavailable = LLM_FAILS_UNAVAILABLE;
cases.hidden = llmFailCountView(log, {visible: false});
cases.hiddenDefault = llmFailCountView(log);
cases.preview = llmFailCountView(log, {visible: false});
cases.missingNull = llmFailCountView(null, {visible: true});
cases.missingUndefined = llmFailCountView(undefined, {visible: true});
cases.missingObject = llmFailCountView({llm_calls: {failed: 4}, events: []}, {visible: true});
cases.empty = llmFailCountView([], {visible: true});
cases.counted = llmFailCountView(log, {visible: true});
cases.ignoresStarted = llmFailCountView([event("only", "llm.started", {failed: 3})], {visible: true});
cases.ignoresCompleted = llmFailCountView([event("ok", "llm.completed", {ok: false})], {visible: true});
cases.ignoresRetry = llmFailCountView([event("retry", "llm.retry", {attempt: 2})], {visible: true});
cases.ignoresFailover = llmFailCountView([event("move", "llm.failover", {failed: 1})], {visible: true});
cases.ignoresMissionFailed = llmFailCountView([event("miss", "mission.failed", {failure_class: "TIMEOUT"})], {visible: true});
cases.skipsHoles = llmFailCountView([null, {payload: {failed: 3}}, failed("one")], {visible: true});
cases.prefix = llmFailCountView(recordedLlmFailFeed(log, 1, true), {visible: true});
cases.prefixFirst = llmFailCountView(recordedLlmFailFeed(log, 0, true), {visible: true});
cases.prefixAll = llmFailCountView(recordedLlmFailFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmFailCountView(recordedLlmFailFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmFailFeed(log, log.length - 1, false);
cases.unloadedView = llmFailCountView(recordedLlmFailFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmFailFeed([], -1, true);
cases.notArrayLog = recordedLlmFailFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
