import {MISSION_STATUS_LABELS, missionStatusBadgeStrip} from "../app/static/state.mjs";

const cases = {
  labels: {...MISSION_STATUS_LABELS},
  order: Object.keys(MISSION_STATUS_LABELS),
  empty: missionStatusBadgeStrip(null),
  missing: missionStatusBadgeStrip({}),
  blank: missionStatusBadgeStrip({id: "m1", status: "  "}),
  idle: missionStatusBadgeStrip({id: "m1", status: "idle"}),
  unknown: missionStatusBadgeStrip({id: "m1", status: "thinking"}),
  invented: missionStatusBadgeStrip({id: "m1", status: "resume_requested"}),
  cased: missionStatusBadgeStrip({id: "m1", status: "RUNNING"}),
  previewFlag: missionStatusBadgeStrip({id: "m1", status: "running"}, {preview: true}),
  previewId: missionStatusBadgeStrip({id: "preview", status: "running"}),
  nonString: missionStatusBadgeStrip({id: "m1", status: {value: "running"}}),
  known: {},
};

for (const status of Object.keys(MISSION_STATUS_LABELS)) {
  cases.known[status] = missionStatusBadgeStrip({id: "m1", status, goal: "Ship the badge"});
}

console.log(JSON.stringify(cases));
