import {
  recordedAvgToolLatencyFeed, avgToolLatencyView, AVG_TOOL_LATENCY_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}, created_at = "2026-01-01T00:00:00Z", extra = {}) {
  return {id, event_type: type, payload, created_at, ...extra};
}

const started = (id, created_at, extra = {}) => event(
  id, "tool.started", {tool: "files", used: 1, ...(extra.payload || {})}, created_at, {actor_id: extra.actor_id || "a1"},
);
const completed = (id, created_at, payload = {}, extra = {}) => event(
  id, "tool.completed", {tool: "files", used: 1, ok: true, ...payload}, created_at, {actor_id: extra.actor_id || "a1"},
);
const failed = (id, created_at, payload = {}) => event(
  id, "tool.failed", {tool: "files", used: 1, error: "down", ...payload}, created_at, {actor_id: "a1"},
);

const log = [
  event("m1", "mission.started", {goal: "Ship"}),
  started("s1", "2026-01-01T00:00:00.000Z"),
  completed("c1", "2026-01-01T00:00:00.200Z"),
  event("llm1", "llm.completed", {duration_ms: 9000, latency_ms: 9000}),
  failed("f1", "2026-01-01T00:00:02.000Z", {elapsed_ms: 50000}),
  started("s2", "2026-01-01T00:00:03.000Z", {payload: {used: 2}}),
  completed("c2", "2026-01-01T00:00:03.400Z", {used: 2}),
  event("agent", "agent.spawned", {id: "root", status: "running"}),
];

const cases = {};
cases.unavailable = AVG_TOOL_LATENCY_UNAVAILABLE;
cases.hidden = avgToolLatencyView(log, {visible: false});
cases.hiddenDefault = avgToolLatencyView(log);
cases.preview = avgToolLatencyView(log, {visible: false});
cases.missingNull = avgToolLatencyView(null, {visible: true});
cases.missingUndefined = avgToolLatencyView(undefined, {visible: true});
cases.missingObject = avgToolLatencyView({events: [], latency_ms: 40}, {visible: true});
cases.empty = avgToolLatencyView([], {visible: true});
cases.counted = avgToolLatencyView(log, {visible: true});
cases.startedOnly = avgToolLatencyView([
  started("only", "2026-01-01T00:00:00Z"),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.failedOnly = avgToolLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  failed("f", "2026-01-01T00:00:09.000Z", {elapsed_ms: 90000, latency_ms: 90000}),
], {visible: true});
cases.zero = avgToolLatencyView([
  completed("z", "2026-01-01T00:00:02Z", {latency_ms: 0}),
], {visible: true});
cases.meanNotNewest = avgToolLatencyView([
  completed("a", "2026-01-01T00:00:01Z", {latency_ms: 100}),
  completed("b", "2026-01-01T00:00:02Z", {latency_ms: 500}),
], {visible: true});
cases.includesZero = avgToolLatencyView([
  completed("a", "2026-01-01T00:00:01Z", {latency_ms: 0}),
  completed("b", "2026-01-01T00:00:02Z", {latency_ms: 100}),
], {visible: true});
cases.spans = avgToolLatencyView([
  started("s1", "2026-01-01T00:00:00.000Z"),
  completed("c1", "2026-01-01T00:00:00.200Z"),
  started("s2", "2026-01-01T00:00:01.000Z", {payload: {used: 2}}),
  completed("c2", "2026-01-01T00:00:01.400Z", {used: 2}),
], {visible: true});
cases.explicitBeatsStamps = avgToolLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  completed("c", "2026-01-01T00:00:05.000Z", {duration_ms: 40}),
], {visible: true});
cases.blankLatency = avgToolLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  completed("c", "2026-01-01T00:00:00.200Z", {latency_ms: ""}),
], {visible: true});
cases.negativeLatency = avgToolLatencyView([
  completed("c", "2026-01-01T00:00:02Z", {elapsed_ms: -5}),
], {visible: true});
cases.stringLatency = avgToolLatencyView([
  completed("c", "2026-01-01T00:00:02Z", {latency_ms: "842"}),
], {visible: true});
cases.nullLatency = avgToolLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  completed("c", "2026-01-01T00:00:00.200Z", {latency_ms: null}),
], {visible: true});
cases.missingStamps = avgToolLatencyView([
  completed("c", "2026-01-01T00:00:02Z", {ok: true}),
], {visible: true});
cases.zeroSpan = avgToolLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  completed("c", "2026-01-01T00:00:00.000Z"),
], {visible: true});
cases.negativeSpan = avgToolLatencyView([
  started("s", "2026-01-01T00:00:02.000Z"),
  completed("c", "2026-01-01T00:00:00.000Z"),
], {visible: true});
cases.failedConsumesStart = avgToolLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  failed("f", "2026-01-01T00:00:10.000Z"),
  completed("c", "2026-01-01T00:00:10.100Z"),
], {visible: true});
cases.partialUnreadable = avgToolLatencyView([
  completed("a", "2026-01-01T00:00:01Z", {latency_ms: 100}),
  completed("b", "2026-01-01T00:00:02Z"),
], {visible: true});
cases.oneSecond = avgToolLatencyView([
  completed("a", "2026-01-01T00:00:01Z", {duration_ms: 1000}),
  completed("b", "2026-01-01T00:00:02Z", {duration_ms: 2000}),
], {visible: true});
cases.minutes = avgToolLatencyView([
  completed("a", "2026-01-01T00:00:01Z", {elapsed_ms: 90000}),
], {visible: true});
cases.hours = avgToolLatencyView([
  completed("a", "2026-01-01T00:00:01Z", {latency_ms: 3720000}),
], {visible: true});
cases.subMillisecond = avgToolLatencyView([
  completed("a", "2026-01-01T00:00:01Z", {latency_ms: 0.4}),
], {visible: true});
cases.ignoresLlm = avgToolLatencyView([
  event("llm", "llm.completed", {latency_ms: 8000, duration_ms: 8000}),
  event("start", "llm.started", {latency_ms: 1}),
  completed("ok", "2026-01-01T00:00:01Z", {latency_ms: 80}),
], {visible: true});
cases.pairedByTool = avgToolLatencyView([
  started("s1", "2026-01-01T00:00:00.000Z", {payload: {tool: "files", used: 1}}),
  started("s2", "2026-01-01T00:00:00.100Z", {payload: {tool: "search", used: 1}}),
  completed("c2", "2026-01-01T00:00:00.300Z", {tool: "search", used: 1}),
  completed("c1", "2026-01-01T00:00:00.400Z", {tool: "files", used: 1}),
], {visible: true});
cases.skipsHoles = avgToolLatencyView([
  null,
  {payload: {latency_ms: 9999}},
  completed("one", "2026-01-01T00:00:01Z", {latency_ms: 40}),
], {visible: true});
cases.prefix = avgToolLatencyView(recordedAvgToolLatencyFeed(log, 2, true), {visible: true});
cases.prefixFirst = avgToolLatencyView(recordedAvgToolLatencyFeed(log, 1, true), {visible: true});
cases.prefixAll = avgToolLatencyView(recordedAvgToolLatencyFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = avgToolLatencyView(recordedAvgToolLatencyFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAvgToolLatencyFeed(log, log.length - 1, false);
cases.unloadedView = avgToolLatencyView(recordedAvgToolLatencyFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAvgToolLatencyFeed([], -1, true);
cases.notArrayLog = recordedAvgToolLatencyFeed({length: 0, latency_ms: 10}, 0, true);

console.log(JSON.stringify(cases));
