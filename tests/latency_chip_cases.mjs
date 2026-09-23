import {applyConnectionSample, latencyChipView, LATENCY_UNAVAILABLE} from "../app/static/state.mjs";

const open = {transport: "websocket", readyState: 1, reconnecting: false};
const cases = {unavailable: LATENCY_UNAVAILABLE};

cases.missing = [
  latencyChipView(null, 1_000),
  latencyChipView(undefined, 1_000),
  latencyChipView({}, 1_000),
  latencyChipView({connected: true, latencyMs: 12}, 1_000),
  latencyChipView({className: "connection live", text: "Live connection"}, 1_000),
  latencyChipView({openai: {configured: true, status: "healthy"}}, 1_000),
];

cases.closedWithNumbers = latencyChipView({
  ...open, readyState: 3, latencyMs: 40, lastPongAt: 500,
}, 1_000);
cases.reconnecting = latencyChipView({...open, reconnecting: true, latencyMs: 40}, 1_000);
cases.connecting = latencyChipView({...open, readyState: 0, latencyMs: 8}, 1_000);
cases.stringReady = latencyChipView({...open, readyState: "1", latencyMs: 8}, 1_000);
cases.sse = latencyChipView({transport: "sse", readyState: 1, latencyMs: 8}, 1_000);

cases.openMissing = latencyChipView(open, 5_000);
cases.stringLatency = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", latency_ms: "42",
}), 5_000);
cases.boolLatency = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", latency_ms: true,
}), 5_000);
cases.negative = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", latency_ms: -5, pong_at: -1,
}), 5_000);
cases.nanLatency = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", latency_ms: Number.NaN, pong_at: Number.POSITIVE_INFINITY,
}), 5_000);

cases.measured = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", latency_ms: 42.4, pong_at: 4_000,
}), 5_500);
cases.zero = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", latency_ms: 0, pong_at: 5_000,
}), 5_000);
cases.pongOnly = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", pong_at: 1_000,
}), 2_600);
cases.futurePong = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", pong_at: 9_000,
}), 5_000);
cases.latencyDespiteFuturePong = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", latency_ms: 10, pong_at: 9_000,
}), 5_000);
cases.missingClock = latencyChipView(applyConnectionSample(open, {
  type: "connection.pong", pong_at: 1_000,
}), undefined);

const withSample = applyConnectionSample(open, {type: "connection.pong", latency_ms: 15, pong_at: 100});
cases.missionEventIgnored = applyConnectionSample(withSample, {
  id: "e1",
  event_type: "llm.completed",
  type: "connection.pong",
  payload: {latency_ms: 999, pong_at: 1},
  latency_ms: 999,
});
cases.invalidClears = applyConnectionSample(withSample, {
  type: "connection.pong", latency_ms: "nope", pong_at: null,
});
cases.omitKeeps = applyConnectionSample(withSample, {type: "connection.pong"});
cases.notAPong = applyConnectionSample(withSample, {type: "ping", latency_ms: 3});

console.log(JSON.stringify(cases));
