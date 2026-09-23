import {
  recordedModelCallFeed, modelCallCountView, MODEL_CALLS_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id, extra = {}) => event(id, "llm.started", {kind: "decision", model: "gpt-6-astra", input_tokens: 99, ...extra});
const log = [
  started("m1"),
  event("retry", "llm.retry", {kind: "decision", attempt: 1}),
  event("done", "llm.completed", {kind: "decision", input_tokens: 11, output_tokens: 7}),
  event("fail", "llm.failed", {kind: "work", failure_class: "RATE_LIMIT"}),
  event("over", "llm.failover", {from_provider: "openai", to_provider: "openrouter"}),
  started("m2"),
  event("spawn", "agent.spawned", {id: "root"}),
  event("tool", "tool.started", {tool: "echo"}),
  started("m3"),
];

const cases = {};
cases.unavailable = MODEL_CALLS_UNAVAILABLE;
cases.hidden = modelCallCountView(log, {visible: false});
cases.hiddenDefault = modelCallCountView(log);
cases.preview = modelCallCountView(log, {visible: false, preview: true});
cases.missingNull = modelCallCountView(null, {visible: true});
cases.missingUndefined = modelCallCountView(undefined, {visible: true});
cases.missingObject = modelCallCountView({calls: 4, events: []}, {visible: true});
cases.empty = modelCallCountView([], {visible: true});
cases.counted = modelCallCountView(log, {visible: true});
cases.ignoresTokenField = modelCallCountView([started("only")], {visible: true});
cases.completedOnly = modelCallCountView([
  event("done-only", "llm.completed", {input_tokens: 4, output_tokens: 2}),
  event("retry-only", "llm.retry", {attempt: 2}),
], {visible: true});
cases.skipsHoles = modelCallCountView([null, {payload: {input_tokens: 3}}, started("one")], {visible: true});
cases.prefix = modelCallCountView(recordedModelCallFeed(log, 1, true), {visible: true});
cases.prefixFirst = modelCallCountView(recordedModelCallFeed(log, 0, true), {visible: true});
cases.prefixAll = modelCallCountView(recordedModelCallFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = modelCallCountView(recordedModelCallFeed(log, -1, true), {visible: true});
cases.unloaded = recordedModelCallFeed(log, log.length - 1, false);
cases.unloadedView = modelCallCountView(recordedModelCallFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedModelCallFeed([], -1, true);
cases.notArrayLog = recordedModelCallFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
