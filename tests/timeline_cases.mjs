import {EMPTY, NO_MISSION, PENDING, UNAVAILABLE, timelinePanel} from "../app/static/timeline.mjs";

const id = "11111111-1111-4111-8111-111111111111";

const cases = {
  noMission: timelinePanel(null),
  preview: timelinePanel({
    preview: true,
    missionId: id,
    ok: true,
    body: {available: true, state: "ok", events: [{event_type: "agent.spawned", summary: "researcher"}]},
  }),
  pending: timelinePanel({missionId: id, pending: true}),
  failed: timelinePanel({missionId: id, ok: false}),
  serverMissing: timelinePanel({
    missionId: id,
    ok: true,
    body: {available: false, state: "no_mission", events: [{event_type: "mission.started"}]},
  }),
  empty: timelinePanel({missionId: id, ok: true, body: {available: true, state: "empty", events: []}}),
  dropsBlank: timelinePanel({
    missionId: id,
    ok: true,
    body: {available: true, state: "ok", events: [{event_type: "  "}, {payload: {role: "ghost"}}]},
  }),
  recorded: timelinePanel({
    missionId: id,
    ok: true,
    body: {
      available: true,
      state: "ok",
      events: [{
        event_type: "mission.failed",
        created_at: "2026-01-01T00:05:00+00:00",
        summary: "TIMEOUT",
        payload: {error: "secret"},
        actor_id: "agent-1",
      }],
    },
  }),
};

console.log(JSON.stringify({cases, NO_MISSION, UNAVAILABLE, EMPTY, PENDING}));
