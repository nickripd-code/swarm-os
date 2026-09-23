import {
  recordedLlmFailoverRateFeed, llmFailoverRateView, LLM_FAILOVER_RATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "llm.failed", {kind: "decision", error: "down", attempt: 9, ...extra});
const completed = (id, extra = {}) => event(id, "llm.completed", {kind: "decision", model: "demo", input_tokens: 3, ...extra});
const failover = (id, extra = {}) => event(id, "llm.failover", {from_provider: "openai", to_provider: "openrouter", ...extra});
const log = [
  event("s1", "llm.started", {kind: "decision", failovers: 4, completed: 9}),
  event("r1", "llm.retry", {kind: "decision", attempt: 1}),
  failed("f1"),
  completed("c1"),
  failover("fo1"),
  failed("f2"),
  event("a1", "agent.spawned", {id: "root", status: "running"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  event("t1", "tool.failed", {tool: "echo"}),
  event("t2", "tool.completed", {tool: "echo", ok: true}),
  completed("c3"),
  failover("fo2"),
];

const cases = {};
cases.unavailable = LLM_FAILOVER_RATE_UNAVAILABLE;
cases.hidden = llmFailoverRateView(log, {visible: false});
cases.hiddenDefault = llmFailoverRateView(log);
cases.preview = llmFailoverRateView(log, {visible: false});
cases.missingNull = llmFailoverRateView(null, {visible: true});
cases.missingUndefined = llmFailoverRateView(undefined, {visible: true});
cases.missingObject = llmFailoverRateView({llm: {failover: 4, completed: 1}, events: []}, {visible: true});
cases.empty = llmFailoverRateView([], {visible: true});
cases.counted = llmFailoverRateView(log, {visible: true});
cases.startedOnly = llmFailoverRateView([
  event("only", "llm.started", {failovers: 3, completed: 0}),
  event("retry", "llm.retry", {attempt: 1}),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.failoverOnly = llmFailoverRateView([
  failover("only"),
  event("retry", "llm.retry", {attempt: 2}),
], {visible: true});
cases.completesOnly = llmFailoverRateView([
  completed("ok1"),
  event("bad", "llm.completed", {ok: false}),
], {visible: true});
cases.half = llmFailoverRateView([failover("fo"), completed("a")], {visible: true});
cases.allFailed = llmFailoverRateView([failed("f1"), failed("f2")], {visible: true});
cases.third = llmFailoverRateView([failover("fo"), completed("a"), failed("b")], {visible: true});
cases.retriesIgnored = llmFailoverRateView([
  event("s", "llm.started"),
  event("r1", "llm.retry"),
  event("r2", "llm.retry"),
  event("job", "job.retry_scheduled"),
  completed("ok"),
], {visible: true});
cases.over = llmFailoverRateView([failover("a"), failover("b"), completed("ok")], {visible: true});
cases.tiny = llmFailoverRateView([failover("fo"), ...Array.from({length: 1000000}, (_, i) => completed("c" + i))], {visible: true});
cases.skipsHoles = llmFailoverRateView([null, {payload: {failovers: 3, rate: 1}}, failover("one"), completed("two")], {visible: true});
cases.prefix = llmFailoverRateView(recordedLlmFailoverRateFeed(log, 4, true), {visible: true});
cases.prefixFirst = llmFailoverRateView(recordedLlmFailoverRateFeed(log, 1, true), {visible: true});
cases.prefixAll = llmFailoverRateView(recordedLlmFailoverRateFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmFailoverRateView(recordedLlmFailoverRateFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmFailoverRateFeed(log, log.length - 1, false);
cases.unloadedView = llmFailoverRateView(recordedLlmFailoverRateFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmFailoverRateFeed([], -1, true);
cases.notArrayLog = recordedLlmFailoverRateFeed({length: 0, failovers: 1, completed: 1}, 0, true);

console.log(JSON.stringify(cases));
