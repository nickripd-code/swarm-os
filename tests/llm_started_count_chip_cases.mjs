import {
  recordedLlmStartedCountFeed, llmStartedCountView, LLM_STARTED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-09-23T12:00:00Z"};
}

const started = (id, extra = {}) => event(id, "llm.started", {
  kind: "decision", model: "gpt-6-astra", input_tokens: 99, ...extra,
});

const log = [
  event("m1", "mission.started"),
  started("s1"),
  event("retry", "llm.retry", {attempt: 1}),
  event("done", "llm.completed", {input_tokens: 11, output_tokens: 7, cost: 1.25}),
  event("fail", "llm.failed", {failure_class: "RATE_LIMIT"}),
  event("over", "llm.failover", {from_provider: "openai", to_provider: "openrouter"}),
  event("tool", "tool.started", {tool: "echo", used: 4}),
  started("s2"),
  null,
  {payload: {kind: "decision", input_tokens: 3}},
  started("s3"),
];

const cases = {};
cases.unavailable = LLM_STARTED_COUNT_UNAVAILABLE;
cases.hidden = llmStartedCountView(log, {visible: false});
cases.hiddenDefault = llmStartedCountView(log);
cases.preview = llmStartedCountView(log, {visible: false, preview: true});
cases.notComputable = llmStartedCountView(log, {visible: true, computable: false});
cases.missingNull = llmStartedCountView(null, {visible: true});
cases.missingUndefined = llmStartedCountView(undefined, {visible: true});
cases.missingObject = llmStartedCountView({calls: 4, events: []}, {visible: true});
cases.empty = llmStartedCountView([], {visible: true});
cases.counted = llmStartedCountView(log, {visible: true});
cases.ignoresCompleted = llmStartedCountView([
  event("done-only", "llm.completed", {input_tokens: 4, output_tokens: 2, cost: 0.8}),
], {visible: true});
cases.ignoresFailed = llmStartedCountView([
  event("fail-only", "llm.failed", {failure_class: "TIMEOUT"}),
], {visible: true});
cases.ignoresRetry = llmStartedCountView([
  event("retry-only", "llm.retry", {attempt: 2}),
], {visible: true});
cases.ignoresFailover = llmStartedCountView([
  event("over-only", "llm.failover", {from_provider: "openai"}),
], {visible: true});
cases.ignoresToolStarted = llmStartedCountView([
  event("tool-only", "tool.started", {tool: "echo", used: 9}),
], {visible: true});
cases.ignoresTokenField = llmStartedCountView([started("only")], {visible: true});
cases.skipsHoles = llmStartedCountView([
  null, {payload: {input_tokens: 3}}, started("one"),
], {visible: true});
cases.unreadableType = llmStartedCountView([
  started("ok"),
  {event_type: 1, payload: {kind: "decision"}},
], {visible: true});
cases.prefix = llmStartedCountView(recordedLlmStartedCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = llmStartedCountView(recordedLlmStartedCountFeed(log, 0, true), {visible: true});
cases.prefixAll = llmStartedCountView(recordedLlmStartedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmStartedCountView(recordedLlmStartedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmStartedCountFeed(log, log.length - 1, false);
cases.unloadedView = llmStartedCountView(recordedLlmStartedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmStartedCountFeed([], -1, true);
cases.notArrayLog = recordedLlmStartedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
