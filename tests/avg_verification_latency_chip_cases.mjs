import {
  recordedAvgVerificationLatencyFeed, avgVerificationLatencyView, AVG_VERIFICATION_LATENCY_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}, created_at = "2026-01-01T00:00:00Z", extra = {}) {
  return {id, event_type: type, payload, created_at, ...extra};
}

const started = (id, created_at, extra = {}) => event(
  id, "verification.started", {summary: "claim", ...(extra.payload || {})}, created_at, {actor_id: extra.actor_id || "root"},
);
const passed = (id, created_at, payload = {}, extra = {}) => event(
  id, "verification.passed", {verdict: "pass", ...payload}, created_at, {actor_id: extra.actor_id || "root"},
);
const failed = (id, created_at, payload = {}, extra = {}) => event(
  id, "verification.failed", {verdict: "fail", ...payload}, created_at, {actor_id: extra.actor_id || "root"},
);

const log = [
  event("m1", "mission.started", {goal: "Ship"}),
  started("s1", "2026-01-01T00:00:00.000Z"),
  passed("p1", "2026-01-01T00:00:00.200Z"),
  event("llm1", "llm.completed", {duration_ms: 9000, latency_ms: 9000}),
  event("ev1", "verification.evidence.passed", {ok: true, latency_ms: 9000, duration_ms: 9000}),
  started("s2", "2026-01-01T00:00:03.000Z"),
  failed("f2", "2026-01-01T00:00:03.400Z"),
  event("agent", "agent.spawned", {id: "root", status: "running"}),
];

const cases = {};
cases.unavailable = AVG_VERIFICATION_LATENCY_UNAVAILABLE;
cases.hidden = avgVerificationLatencyView(log, {visible: false});
cases.hiddenDefault = avgVerificationLatencyView(log);
cases.preview = avgVerificationLatencyView(log, {visible: false});
cases.missingNull = avgVerificationLatencyView(null, {visible: true});
cases.missingUndefined = avgVerificationLatencyView(undefined, {visible: true});
cases.missingObject = avgVerificationLatencyView({events: [], latency_ms: 40}, {visible: true});
cases.empty = avgVerificationLatencyView([], {visible: true});
cases.counted = avgVerificationLatencyView(log, {visible: true});
cases.startedOnly = avgVerificationLatencyView([
  started("only", "2026-01-01T00:00:00Z"),
  event("agent", "agent.spawned", {status: "online"}),
], {visible: true});
cases.evidenceOnly = avgVerificationLatencyView([
  event("ev", "verification.evidence.started", {count: 1}),
  event("evp", "verification.evidence.passed", {ok: true, latency_ms: 40}),
  event("evf", "verification.evidence.failed", {ok: false, duration_ms: 80}),
], {visible: true});
cases.failedOnly = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  failed("f", "2026-01-01T00:00:00.250Z"),
], {visible: true});
cases.zero = avgVerificationLatencyView([
  passed("z", "2026-01-01T00:00:02Z", {latency_ms: 0}),
], {visible: true});
cases.meanNotNewest = avgVerificationLatencyView([
  passed("a", "2026-01-01T00:00:01Z", {latency_ms: 100}),
  failed("b", "2026-01-01T00:00:02Z", {latency_ms: 500}),
], {visible: true});
cases.includesZero = avgVerificationLatencyView([
  passed("a", "2026-01-01T00:00:01Z", {latency_ms: 0}),
  failed("b", "2026-01-01T00:00:02Z", {latency_ms: 100}),
], {visible: true});
cases.spans = avgVerificationLatencyView([
  started("s1", "2026-01-01T00:00:00.000Z"),
  passed("c1", "2026-01-01T00:00:00.200Z"),
  started("s2", "2026-01-01T00:00:01.000Z"),
  failed("c2", "2026-01-01T00:00:01.400Z"),
], {visible: true});
cases.explicitBeatsStamps = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  passed("c", "2026-01-01T00:00:05.000Z", {duration_ms: 40}),
], {visible: true});
cases.blankLatency = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  passed("c", "2026-01-01T00:00:00.200Z", {latency_ms: ""}),
], {visible: true});
cases.negativeLatency = avgVerificationLatencyView([
  failed("c", "2026-01-01T00:00:02Z", {elapsed_ms: -5}),
], {visible: true});
cases.stringLatency = avgVerificationLatencyView([
  passed("c", "2026-01-01T00:00:02Z", {latency_ms: "842"}),
], {visible: true});
cases.nullLatency = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  failed("c", "2026-01-01T00:00:00.200Z", {latency_ms: null}),
], {visible: true});
cases.missingStamps = avgVerificationLatencyView([
  event("c", "verification.passed", {verdict: "pass"}, null),
], {visible: true});
cases.zeroSpan = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:02.000Z"),
  passed("c", "2026-01-01T00:00:02.000Z"),
], {visible: true});
cases.negativeSpan = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:05.000Z"),
  failed("c", "2026-01-01T00:00:04.000Z"),
], {visible: true});
cases.orphanOutcome = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  passed("a", "2026-01-01T00:00:00.100Z"),
  failed("b", "2026-01-01T00:00:00.400Z"),
], {visible: true});
cases.partialUnreadable = avgVerificationLatencyView([
  passed("a", "2026-01-01T00:00:01Z", {latency_ms: 100}),
  failed("b", "2026-01-01T00:00:02Z"),
], {visible: true});
cases.oneSecond = avgVerificationLatencyView([
  passed("a", "2026-01-01T00:00:01Z", {latency_ms: 1000}),
  failed("b", "2026-01-01T00:00:02Z", {latency_ms: 2000}),
], {visible: true});
cases.minutes = avgVerificationLatencyView([
  passed("a", "2026-01-01T00:00:01Z", {latency_ms: 90000}),
], {visible: true});
cases.hours = avgVerificationLatencyView([
  failed("a", "2026-01-01T00:00:01Z", {latency_ms: 3720000}),
], {visible: true});
cases.subMillisecond = avgVerificationLatencyView([
  passed("a", "2026-01-01T00:00:01Z", {latency_ms: 0.4}),
], {visible: true});
cases.ignoresOthers = avgVerificationLatencyView([
  event("llm", "llm.completed", {latency_ms: 8000, duration_ms: 8000}),
  event("start", "llm.started", {latency_ms: 1}),
  event("tool", "tool.completed", {latency_ms: 40, duration_ms: 40}),
  event("ev", "verification.evidence.failed", {latency_ms: 9000}),
  passed("ok", "2026-01-01T00:00:01Z", {latency_ms: 80}),
], {visible: true});
cases.evidenceDoesNotConsume = avgVerificationLatencyView([
  started("s", "2026-01-01T00:00:00.000Z"),
  event("ev", "verification.evidence.passed", {ok: true, latency_ms: 50}, "2026-01-01T00:00:00.050Z"),
  passed("ok", "2026-01-01T00:00:00.200Z"),
], {visible: true});
cases.pairedByActor = avgVerificationLatencyView([
  started("sa", "2026-01-01T00:00:00.000Z", {actor_id: "a"}),
  started("sb", "2026-01-01T00:00:00.010Z", {actor_id: "b"}),
  passed("pa", "2026-01-01T00:00:00.200Z", {}, {actor_id: "a"}),
  failed("fb", "2026-01-01T00:00:00.110Z", {}, {actor_id: "b"}),
], {visible: true});
cases.actorMismatch = avgVerificationLatencyView([
  started("sa", "2026-01-01T00:00:00.000Z", {actor_id: "a"}),
  passed("pb", "2026-01-01T00:00:00.200Z", {}, {actor_id: "b"}),
], {visible: true});
cases.skipsHoles = avgVerificationLatencyView([
  null,
  {payload: {latency_ms: 9999}},
  passed("one", "2026-01-01T00:00:01Z", {latency_ms: 40}),
], {visible: true});
cases.prefix = avgVerificationLatencyView(recordedAvgVerificationLatencyFeed(log, 2, true), {visible: true});
cases.prefixFirst = avgVerificationLatencyView(recordedAvgVerificationLatencyFeed(log, 1, true), {visible: true});
cases.prefixAll = avgVerificationLatencyView(recordedAvgVerificationLatencyFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = avgVerificationLatencyView(recordedAvgVerificationLatencyFeed(log, -1, true), {visible: true});
cases.unloaded = recordedAvgVerificationLatencyFeed([], 0, false);
cases.unloadedView = avgVerificationLatencyView(recordedAvgVerificationLatencyFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedAvgVerificationLatencyFeed([], 0, true);
cases.notArrayLog = recordedAvgVerificationLatencyFeed({length: 0, latency_ms: 10}, 0, true);

process.stdout.write(JSON.stringify(cases));
