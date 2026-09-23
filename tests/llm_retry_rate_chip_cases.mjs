import {
  recordedLlmRetryRateFeed, llmRetryRateView, LLM_RETRY_RATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "llm.failed", {kind: "decision", error: "down", attempt: 9, ...extra});
const completed = (id, extra = {}) => event(id, "llm.completed", {kind: "decision", model: "demo", input_tokens: 3, ...extra});
const retry = (id, extra = {}) => event(id, "llm.retry", {kind: "decision", attempt: 1, ...extra});
const log = [
  event("s1", "llm.started", {kind: "decision", retries: 4, failed: 9}),
  retry("r1"),
  failed("f1"),
  completed("c1"),
  event("fo1", "llm.failover", {from_provider: "a", to_provider: "b"}),
  retry("r2"),
  failed("f2"),
  event("a1", "agent.spawned", {id: "root", status: "running"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  event("t1", "tool.failed", {tool: "echo"}),
  event("t2", "tool.completed", {tool: "echo", ok: true}),
  completed("c3"),
];

const cases = {};
cases.unavailable = LLM_RETRY_RATE_UNAVAILABLE;
cases.hidden = llmRetryRateView(log, {visible: false});
cases.hiddenDefault = llmRetryRateView(log);
cases.preview = llmRetryRateView(log, {visible: false});
cases.missingNull = llmRetryRateView(null, {visible: true});
cases.missingUndefined = llmRetryRateView(undefined, {visible: true});
cases.missingObject = llmRetryRateView({llm: {retry: 4, failed: 1}, events: []}, {visible: true});
cases.empty = llmRetryRateView([], {visible: true});
cases.counted = llmRetryRateView(log, {visible: true});
cases.startedOnly = llmRetryRateView([
  event("only", "llm.started", {retries: 3, failed: 0}),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.retriesOnly = llmRetryRateView([
  retry("r1"),
  retry("r2"),
  event("fo", "llm.failover"),
  event("s", "llm.started"),
], {visible: true});
cases.zero = llmRetryRateView([
  completed("ok1"),
  failed("f1"),
  event("fo", "llm.failover"),
], {visible: true});
cases.half = llmRetryRateView([retry("r"), failed("f"), completed("a")], {visible: true});
cases.over = llmRetryRateView([
  retry("r1"),
  retry("r2"),
  completed("ok"),
], {visible: true});
cases.third = llmRetryRateView([retry("r"), completed("a"), failed("b"), completed("c")], {visible: true});
cases.failoverIgnored = llmRetryRateView([
  event("s", "llm.started"),
  event("fo", "llm.failover", {retries: 9}),
  event("t", "tool.completed", {duration_ms: 40}),
  completed("ok"),
], {visible: true});
cases.tiny = llmRetryRateView([retry("r"), ...Array.from({length: 1000000}, (_, i) => completed("c" + i))], {visible: true});
cases.skipsHoles = llmRetryRateView([null, {payload: {retries: 3, rate: 1}}, retry("one"), failed("two")], {visible: true});
cases.prefix = llmRetryRateView(recordedLlmRetryRateFeed(log, 2, true), {visible: true});
cases.prefixFirst = llmRetryRateView(recordedLlmRetryRateFeed(log, 1, true), {visible: true});
cases.prefixAll = llmRetryRateView(recordedLlmRetryRateFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmRetryRateView(recordedLlmRetryRateFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmRetryRateFeed(log, log.length - 1, false);
cases.unloadedView = llmRetryRateView(recordedLlmRetryRateFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmRetryRateFeed([], -1, true);
cases.notArrayLog = recordedLlmRetryRateFeed({length: 0, retries: 1, failed: 1}, 0, true);

console.log(JSON.stringify(cases));
