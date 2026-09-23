import {
  recordedLlmFailRateFeed, llmFailRateView, LLM_FAIL_RATE_UNAVAILABLE,
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
cases.unavailable = LLM_FAIL_RATE_UNAVAILABLE;
cases.hidden = llmFailRateView(log, {visible: false});
cases.hiddenDefault = llmFailRateView(log);
cases.preview = llmFailRateView(log, {visible: false});
cases.missingNull = llmFailRateView(null, {visible: true});
cases.missingUndefined = llmFailRateView(undefined, {visible: true});
cases.missingObject = llmFailRateView({llm: {failed: 4, completed: 1}, events: []}, {visible: true});
cases.empty = llmFailRateView([], {visible: true});
cases.counted = llmFailRateView(log, {visible: true});
cases.startedOnly = llmFailRateView([
  event("only", "llm.started", {failed: 3, completed: 0}),
  event("retry", "llm.retry", {attempt: 1}),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.completesOnly = llmFailRateView([
  completed("ok1"),
  event("bad", "llm.completed", {ok: false}),
], {visible: true});
cases.half = llmFailRateView([failed("f"), completed("a")], {visible: true});
cases.allFailed = llmFailRateView([failed("f1"), failed("f2")], {visible: true});
cases.third = llmFailRateView([failed("f"), completed("a"), completed("b")], {visible: true});
cases.retriesIgnored = llmFailRateView([
  event("s", "llm.started"),
  event("r1", "llm.retry"),
  event("r2", "llm.retry"),
  event("fo", "llm.failover"),
  completed("ok"),
], {visible: true});
cases.tiny = llmFailRateView([failed("f"), ...Array.from({length: 1000000}, (_, i) => completed("c" + i))], {visible: true});
cases.skipsHoles = llmFailRateView([null, {payload: {failed: 3, rate: 1}}, failed("one"), completed("two")], {visible: true});
cases.prefix = llmFailRateView(recordedLlmFailRateFeed(log, 4, true), {visible: true});
cases.prefixFirst = llmFailRateView(recordedLlmFailRateFeed(log, 1, true), {visible: true});
cases.prefixAll = llmFailRateView(recordedLlmFailRateFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = llmFailRateView(recordedLlmFailRateFeed(log, -1, true), {visible: true});
cases.unloaded = recordedLlmFailRateFeed(log, log.length - 1, false);
cases.unloadedView = llmFailRateView(recordedLlmFailRateFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedLlmFailRateFeed([], -1, true);
cases.notArrayLog = recordedLlmFailRateFeed({length: 0, failed: 1, completed: 1}, 0, true);

console.log(JSON.stringify(cases));
