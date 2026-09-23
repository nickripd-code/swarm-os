import {
  recordedLlmSuccessRateFeed, llmSuccessRateView, LLM_SUCCESS_RATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const failed = (id, extra = {}) => event(id, "llm.failed", {kind: "decision", error: "down", attempt: 9, ...extra});
const completed = (id, extra = {}) => event(id, "llm.completed", {kind: "decision", model: "demo", input_tokens: 3, ...extra});
const log = [
  event("s1", "llm.started", {kind: "decision", failed: 4, completed: 9}),
  event("r1", "llm.retry", {kind: "decision", attempt: 1}),
  failed("f1"),
  completed("c1"),
  event("fo1", "llm.failover", {from_provider: "a", to_provider: "b"}),
  failed("f2"),
  event("a1", "agent.spawned", {id: "root", status: "running"}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "PROVIDER_OUTAGE"}),
  event("t1", "tool.failed", {tool: "echo"}),
  event("t2", "tool.completed", {tool: "echo", ok: true}),
  completed("c3"),
];

const cases = {};
cases.unavailable = LLM_SUCCESS_RATE_UNAVAILABLE;
cases.hidden = llmSuccessRateView(log, {visible: false});
cases.hiddenDefault = llmSuccessRateView(log);
cases.preview = llmSuccessRateView(log, {visible: false});
cases.missingNull = llmSuccessRateView(null, {visible: true});
cases.missingUndefined = llmSuccessRateView(undefined, {visible: true});
cases.missingObject = llmSuccessRateView({llm: {failed: 4, completed: 1}, events: []}, {visible: true});
cases.empty = llmSuccessRateView([], {visible: true});
cases.counted = llmSuccessRateView(log, {visible: true});
cases.startedOnly = llmSuccessRateView([
  event("only", "llm.started", {failed: 3, completed: 0}),
  event("retry", "llm.retry", {attempt: 1}),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.completesOnly = llmSuccessRateView([
  completed("ok1"),
  event("bad", "llm.completed", {ok: false}),
], {visible: true});
cases.half = llmSuccessRateView([failed("f"), completed("a")], {visible: true});
cases.allFailed = llmSuccessRateView([failed("f1"), failed("f2")], {visible: true});
cases.third = llmSuccessRateView([failed("f"), completed("a"), completed("b")], {visible: true});
cases.retriesIgnored = llmSuccessRateView([
  event("s", "llm.started"),
  event("r1", "llm.retry"),
  event("r2", "llm.retry"),
  event("fo", "llm.failover"),
  completed("ok"),
], {visible: true});
cases.tiny = llmSuccessRateView([completed("ok"), ...Array.from({length: 1000000}, (_, i) => failed("f" + i))], {visible: true});
cases.skipsHoles = llmSuccessRateView([null, {payload: {failed: 3, rate: 1}}, failed("one"), completed("two")], {visible: true});
cases.prefix = llmSuccessRateView(recordedLlmSuccessRateFeed(log, 4, true), {visible: true});
cases.prefixFirst = llmSuccessRateView(recordedLlmSuccessRateFeed(log, 1, true), {visible: true});
cases.prefixAll = llmSuccessRateView(recordedLlmSuccessRateFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmSuccessRateView(recordedLlmSuccessRateFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmSuccessRateFeed(log, log.length - 1, false);
cases.unloadedView = llmSuccessRateView(recordedLlmSuccessRateFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmSuccessRateFeed([], -1, true);
cases.notArrayLog = recordedLlmSuccessRateFeed({length: 0, failed: 1, completed: 1}, 0, true);

console.log(JSON.stringify(cases));
