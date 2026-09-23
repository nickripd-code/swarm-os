import {lastModelLatencyView} from "../app/static/state.mjs";

const mission = {id: "m1", goal: "Ship the note", status: "running"};
const cases = {};

function view(events, options = {}) {
  return lastModelLatencyView({
    mission,
    preview: false,
    events,
    ...options,
  });
}

cases.noMission = lastModelLatencyView({
  mission: null,
  preview: false,
  events: [{event_type: "llm.completed", payload: {latency_ms: 400}, created_at: "2026-09-23T12:00:02Z"}],
});
cases.preview = view(
  [{event_type: "llm.completed", payload: {latency_ms: 400}, created_at: "2026-09-23T12:00:02Z"}],
  {preview: true},
);
cases.noModelCall = view([
  {event_type: "mission.started", payload: {goal: "Ship the note"}, created_at: "2026-09-23T12:00:00Z"},
]);
cases.notAnArray = view(null);
cases.startedOnly = view([
  {event_type: "llm.started", actor_id: "a1", payload: {kind: "decision"}, created_at: "2026-09-23T12:00:00Z"},
]);
cases.missingStamps = view([
  {event_type: "llm.completed", actor_id: "a1", payload: {kind: "decision", model: "gpt-test"}},
  {event_type: "llm.started", actor_id: "a1", payload: {kind: "decision"}},
]);
cases.blankLatency = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {latency_ms: ""},
    created_at: "2026-09-23T12:00:02Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "decision"},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.whitespaceLatency = view([
  {event_type: "llm.completed", payload: {duration_ms: "  "}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.zeroLatency = view([
  {event_type: "llm.completed", payload: {latency_ms: 0}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.negativeLatency = view([
  {event_type: "llm.completed", payload: {elapsed_ms: -5}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.stringLatency = view([
  {event_type: "llm.completed", payload: {latency_ms: "842"}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.nullLatency = view([
  {event_type: "llm.completed", payload: {latency_ms: null}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.subSecond = view([
  {event_type: "llm.completed", payload: {latency_ms: 842}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.oneSecond = view([
  {event_type: "llm.completed", payload: {duration_ms: 1500}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.minutes = view([
  {event_type: "llm.failed", payload: {elapsed_ms: 90000}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.hours = view([
  {event_type: "llm.completed", payload: {latency_ms: 3720000}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.timestampSpan = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "decision", input_tokens: 11, delay_seconds: 9},
    created_at: "2026-09-23T12:00:02.500Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "decision"},
    created_at: "2026-09-23T12:00:00.000Z",
  },
]);
cases.zeroSpan = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "work"},
    created_at: "2026-09-23T12:00:00Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "work"},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.explicitBeatsStamps = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "decision", latency_ms: 842},
    created_at: "2026-09-23T12:00:05Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "decision"},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.invalidDoesNotFallback = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {latency_ms: 0},
    created_at: "2026-09-23T12:00:02Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "decision"},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.newestWins = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "work", latency_ms: 1800},
    created_at: "2026-09-23T12:05:00Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "work"},
    created_at: "2026-09-23T12:04:00Z",
  },
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "decision", latency_ms: 400},
    created_at: "2026-09-23T12:01:00Z",
  },
]);
cases.inFlightAfterFinish = view([
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "work"},
    created_at: "2026-09-23T12:06:00Z",
  },
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "decision", latency_ms: 400},
    created_at: "2026-09-23T12:01:00Z",
  },
]);
cases.otherActorIgnored = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "work"},
    created_at: "2026-09-23T12:00:03Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a2",
    payload: {kind: "work"},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.retryIsNotLatency = view([
  {
    event_type: "llm.retry",
    actor_id: "a1",
    payload: {delay_seconds: 2, kind: "decision"},
    created_at: "2026-09-23T12:00:01Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "decision"},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.tokensAreNotLatency = view([
  {
    event_type: "llm.completed",
    actor_id: "a1",
    payload: {kind: "decision", input_tokens: 11, output_tokens: 7},
    created_at: "2026-09-23T12:00:04Z",
  },
  {
    event_type: "llm.started",
    actor_id: "a1",
    payload: {kind: "decision"},
    created_at: "2026-09-23T12:00:00Z",
  },
]);

console.log(JSON.stringify(cases));
