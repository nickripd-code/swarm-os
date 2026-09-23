import {eventCountView, recordEvent, EVENT_COUNT_UNAVAILABLE} from "../app/static/state.mjs";

const mission = {id: "m1", goal: "Ship the landing page", status: "running"};

function event(id, type) {
  return {id, event_type: type, actor_id: "root", payload: {}, created_at: "2026-01-01T00:00:00Z"};
}

const log = [];
recordEvent(log, event(1, "mission.started"));
recordEvent(log, event(2, "agent.spawned"));
const duplicate = recordEvent(log, event(2, "agent.spawned"));

const cases = {
  standby: eventCountView([], {mission: null, preview: false}),
  standbyMissing: eventCountView(null, {}),
  missingNull: eventCountView(null, {mission}),
  missingUndefined: eventCountView(undefined, {mission}),
  missingObject: eventCountView({length: 4}, {mission}),
  missingString: eventCountView("3", {mission}),
  explicitEmpty: eventCountView([], {mission}),
  oneEvent: eventCountView([event(1, "mission.started")], {mission}),
  recorded: eventCountView(log, {mission}),
  duplicateIgnored: duplicate,
  recordedLength: log.length,
  previewMissing: eventCountView(null, {preview: true}),
  previewExplicitEmpty: eventCountView([], {mission: null, preview: true}),
  unavailable: EVENT_COUNT_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
