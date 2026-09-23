import {replayView, shellModeView, SHELL_MODE_UNAVAILABLE} from "../app/static/state.mjs";

const mission = {id: "m1", goal: "Ship the landing page", status: "running"};
const log = [
  {id: 1, event_type: "mission.started", payload: {mode: "openai"}, created_at: "2026-01-01T00:00:01Z"},
  {id: 2, event_type: "agent.spawned", payload: {id: "root"}, created_at: "2026-01-01T00:00:02Z"},
  {id: 3, event_type: "mission.completed", payload: {summary: "done"}, created_at: "2026-01-01T00:00:03Z"},
];

const cases = {
  unavailable: SHELL_MODE_UNAVAILABLE,
  standby: shellModeView({preview: false, mission: null, log: [], index: -1}),
  missingLog: shellModeView({preview: false, mission, log: null, index: -1}),
  blankId: shellModeView({preview: false, mission: {id: ""}, log: [], index: -1}),
  strayLog: shellModeView({preview: false, mission: null, log, index: 0}),
  providerModeIgnored: shellModeView({
    preview: false,
    mission: {id: "m1", mode: "openai", result: {mode: "live"}},
    log,
    index: 1,
  }),
  emptyLive: shellModeView({preview: false, mission, log: [], index: -1}),
  scrubbed: shellModeView({preview: false, mission, log, index: 1}),
  liveEnd: shellModeView({preview: false, mission, log, index: 2}),
  preview: shellModeView({preview: true, mission: {id: "preview", status: "running"}, log, index: 2}),
  previewWithoutMission: shellModeView({preview: true, mission: null, log: null, index: -1}),
  replayAgrees: replayView(log, 1, {preview: false, mission}).label,
};

console.log(JSON.stringify(cases));
