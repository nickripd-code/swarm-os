import {newState, applyEvent, missionPhaseChip} from "../app/static/state.mjs";

const phases = ["pending", "running", "waiting", "paused", "blocked", "completed", "failed", "stopped"];
const cases = {known: {}, hidden: {}, unavailable: {}};

for (const status of phases) {
  cases.known[status] = missionPhaseChip({
    preview: false,
    mission: {id: "m1", status, goal: "ship"},
  });
}

cases.known.mixedCase = missionPhaseChip({
  preview: false,
  mission: {id: "m1", status: "  Paused  "},
});

const started = newState();
started.mission = {id: "m1", status: "pending", goal: "ship"};
applyEvent(started, {
  id: "e1",
  event_type: "mission.started",
  payload: {mode: "live"},
  created_at: "2026-01-01T00:00:00Z",
});
cases.known.afterStart = missionPhaseChip(started);

const waiting = newState();
waiting.mission = {id: "m1", status: "running", goal: "ship"};
applyEvent(waiting, {
  id: "e2",
  event_type: "mission.waiting",
  payload: {},
  created_at: "2026-01-01T00:00:01Z",
});
cases.known.afterWaiting = missionPhaseChip(waiting);

cases.hidden.none = missionPhaseChip(newState());
cases.hidden.preview = missionPhaseChip({
  preview: true,
  mission: {id: "preview", status: "running", goal: "preview"},
});
cases.hidden.previewStopped = missionPhaseChip({
  preview: true,
  mission: {id: "preview", status: "stopped"},
});

cases.unavailable.missing = missionPhaseChip({preview: false, mission: {id: "m1", goal: "ship"}});
cases.unavailable.blank = missionPhaseChip({preview: false, mission: {id: "m1", status: "   "}});
cases.unavailable.nullStatus = missionPhaseChip({preview: false, mission: {id: "m1", status: null}});
cases.unavailable.idle = missionPhaseChip({preview: false, mission: {id: "m1", status: "idle"}});
cases.unavailable.unknown = missionPhaseChip({preview: false, mission: {id: "m1", status: "planning"}});
cases.unavailable.numeric = missionPhaseChip({preview: false, mission: {id: "m1", status: 1}});

console.log(JSON.stringify(cases));
