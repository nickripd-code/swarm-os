import {lastToolLatencyView, projectEvents} from "../app/static/state.mjs";

const mission = {id: "m1", goal: "Ship the note", status: "running", created_at: "2026-09-23T11:59:00Z"};
const cases = {};

function view(events, options = {}) {
  return lastToolLatencyView({
    mission,
    preview: false,
    events,
    ...options,
  });
}

cases.noMission = lastToolLatencyView({
  mission: null,
  preview: false,
  events: [{event_type: "tool.completed", payload: {latency_ms: 400}, created_at: "2026-09-23T12:00:02Z"}],
});
cases.preview = view(
  [{event_type: "tool.completed", payload: {latency_ms: 400}, created_at: "2026-09-23T12:00:02Z"}],
  {preview: true},
);
cases.missingFeed = view(null);
cases.notAnArray = view("tool.completed");
cases.emptyFeed = view([]);
cases.replayBeforeAnyEvent = lastToolLatencyView(projectEvents(
  mission,
  [{
    id: "tool-1",
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", latency_ms: 400},
    created_at: "2026-09-23T12:00:02Z",
  }],
  -1,
));
cases.noToolYet = view([
  {event_type: "mission.started", payload: {goal: "Ship the note"}, created_at: "2026-09-23T12:00:00Z"},
]);
cases.startedOnly = view([
  {event_type: "tool.started", actor_id: "a1", payload: {tool: "files", used: 1}, created_at: "2026-09-23T12:00:00Z"},
]);
cases.missingStamps = view([
  {event_type: "tool.completed", actor_id: "a1", payload: {tool: "files", ok: true}},
  {event_type: "tool.started", actor_id: "a1", payload: {tool: "files", used: 1}},
]);
cases.blankLatency = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", latency_ms: ""},
    created_at: "2026-09-23T12:00:02Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.whitespaceLatency = view([
  {event_type: "tool.completed", payload: {tool: "files", duration_ms: "  "}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.zeroLatency = view([
  {event_type: "tool.completed", payload: {tool: "files", latency_ms: 0}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.negativeLatency = view([
  {event_type: "tool.completed", payload: {tool: "files", elapsed_ms: -5}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.stringLatency = view([
  {event_type: "tool.completed", payload: {tool: "files", latency_ms: "842"}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.nullLatency = view([
  {event_type: "tool.completed", payload: {tool: "files", latency_ms: null}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.subSecond = view([
  {event_type: "tool.completed", payload: {tool: "files", latency_ms: 842}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.oneSecond = view([
  {event_type: "tool.completed", payload: {tool: "files", duration_ms: 1500}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.minutes = view([
  {event_type: "tool.failed", payload: {tool: "files", elapsed_ms: 90000}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.hours = view([
  {event_type: "tool.completed", payload: {tool: "files", latency_ms: 3720000}, created_at: "2026-09-23T12:00:02Z"},
]);
cases.timestampSpan = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1, ok: true, output: {bytes: 9}},
    created_at: "2026-09-23T12:00:02.500Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00.000Z",
  },
]);
cases.zeroSpan = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.explicitBeatsStamps = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1, latency_ms: 842},
    created_at: "2026-09-23T12:00:05Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.invalidDoesNotFallback = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", latency_ms: 0},
    created_at: "2026-09-23T12:00:02Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.newestWins = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "browser", used: 2, latency_ms: 1800},
    created_at: "2026-09-23T12:05:00Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "browser", used: 2},
    created_at: "2026-09-23T12:04:00Z",
  },
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1, latency_ms: 400},
    created_at: "2026-09-23T12:01:00Z",
  },
]);
cases.inFlightAfterFinish = view([
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "browser", used: 2},
    created_at: "2026-09-23T12:06:00Z",
  },
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1, latency_ms: 400},
    created_at: "2026-09-23T12:01:00Z",
  },
]);
cases.otherActorIgnored = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:03Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a2",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.otherToolIgnored = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:03Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "browser", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.otherUseIgnored = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 2},
    created_at: "2026-09-23T12:00:03Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "files", used: 1},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.outputIsNotLatency = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", used: 1, ok: true, output: {latency_ms: 50, bytes: 9}},
    created_at: "2026-09-23T12:00:04Z",
  },
  {
    event_type: "tool.started",
    actor_id: "a1",
    payload: {tool: "files", used: 1, latency_ms: 50},
    created_at: "2026-09-23T12:00:00Z",
  },
]);
cases.catalogFieldIgnored = view([
  {
    event_type: "tool.completed",
    actor_id: "a1",
    payload: {tool: "files", spec_latency_ms: 12, delay_seconds: 9},
  },
]);
cases.replayAtCompletion = lastToolLatencyView(projectEvents(
  mission,
  [
    {
      id: "start-1",
      event_type: "tool.started",
      actor_id: "a1",
      payload: {tool: "files", used: 1},
      created_at: "2026-09-23T12:00:00.000Z",
    },
    {
      id: "done-1",
      event_type: "tool.completed",
      actor_id: "a1",
      payload: {tool: "files", used: 1, ok: true},
      created_at: "2026-09-23T12:00:02.500Z",
    },
  ],
  1,
));

console.log(JSON.stringify(cases));
