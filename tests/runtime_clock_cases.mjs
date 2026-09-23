import {formatRuntimeElapsed, runtimeClockView, RUNTIME_UNAVAILABLE} from "../app/static/state.mjs";

const START = "2026-01-01T00:00:00.000Z";
const START_MS = Date.parse(START);
const NOW = Date.parse("2026-01-01T00:10:00.000Z");

function mission(extra = {}) {
  return {
    id: "m1",
    goal: "Ship the clock",
    status: "running",
    created_at: "2025-12-31T00:00:00.000Z",
    updated_at: "2026-01-01T00:09:00.000Z",
    paused_seconds: 0,
    paused_at: null,
    ...extra,
  };
}

function event(id, type, created_at) {
  return {id, event_type: type, created_at, payload: {}};
}

const cases = {};
cases.unavailable = RUNTIME_UNAVAILABLE;
cases.empty = runtimeClockView(null, [], NOW);
cases.missingId = runtimeClockView({status: "running", created_at: START}, [], NOW);
cases.preview = runtimeClockView({id: "preview", status: "running", created_at: START}, [
  event("e1", "mission.started", START),
], NOW);
cases.noEvents = runtimeClockView(mission(), [], NOW);
cases.createdAtIgnored = runtimeClockView(mission(), [
  event("e1", "agent.spawned", START),
], NOW);
cases.running = runtimeClockView(mission(), [
  event("e1", "mission.started", START),
], NOW);
cases.pauseSubtracted = runtimeClockView(mission({paused_seconds: 120}), [
  event("e1", "mission.started", START),
], NOW);
cases.pausedFreeze = runtimeClockView(mission({
  status: "paused",
  paused_at: "2026-01-01T00:04:00.000Z",
  paused_seconds: 30,
}), [
  event("e1", "mission.started", START),
], NOW);
cases.pausedMissingAnchor = runtimeClockView(mission({
  status: "paused",
  paused_at: null,
  paused_seconds: 0,
}), [
  event("e1", "mission.started", START),
], NOW);
cases.terminalFreeze = runtimeClockView(mission({status: "completed"}), [
  event("e1", "mission.started", START),
  event("e2", "mission.completed", "2026-01-01T00:05:30.000Z"),
], Date.parse("2026-01-01T02:00:00.000Z"));
cases.terminalMissing = runtimeClockView(mission({status: "failed"}), [
  event("e1", "mission.started", START),
], NOW);
cases.badPause = runtimeClockView(mission({paused_seconds: "12"}), [
  event("e1", "mission.started", START),
], NOW);
cases.badStart = runtimeClockView(mission(), [
  event("e1", "mission.started", "not-a-time"),
  event("e2", "mission.resumed", START),
], NOW);
cases.resumedOnly = runtimeClockView(mission(), [
  event("e1", "mission.resumed", START),
], NOW);
cases.firstStartedWins = runtimeClockView(mission(), [
  event("e1", "mission.started", START),
  event("e2", "mission.resumed", "2026-01-01T00:08:00.000Z"),
], NOW);
cases.pending = runtimeClockView(mission({status: "pending"}), [
  event("e1", "mission.started", START),
], NOW);
cases.waiting = runtimeClockView(mission({status: "waiting"}), [
  event("e1", "mission.started", START),
], NOW);
cases.badNow = runtimeClockView(mission(), [
  event("e1", "mission.started", START),
], Number.NaN);
cases.format = {
  bad: formatRuntimeElapsed(-1),
  zero: formatRuntimeElapsed(0),
  seconds: formatRuntimeElapsed(3000),
};
cases.startMs = START_MS;

console.log(JSON.stringify(cases));
