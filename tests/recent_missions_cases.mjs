import {recentMissionRows, RECENT_MISSION_SNIPPET_LIMIT} from "../app/static/state.mjs";

const id = "11111111-1111-4111-8111-111111111111";
const started = "2026-09-23T09:00:00+00:00";
const created = "2026-09-23T08:00:00+00:00";
const goal = "Ship the read-only mission list";

const cases = {
  limit: RECENT_MISSION_SNIPPET_LIMIT,
  empty: recentMissionRows([]),
  missing: recentMissionRows(null),
  wrapped: recentMissionRows({missions: [{id, status: "completed", goal, created_at: created}]}),
  string: recentMissionRows("[]"),
  skipped: recentMissionRows([
    null,
    [],
    {status: "completed", goal, created_at: created},
    {id, goal, created_at: created},
    {id: "  ", status: "completed", goal},
    {id, status: "failed", goal: "  real failure  ", created_at: created},
  ]),
  recorded: recentMissionRows([{
    id,
    status: "completed",
    goal,
    created_at: created,
    spent: 0,
    result: {ok: true},
  }]),
  startedPrefersExplicit: recentMissionRows([{
    id,
    status: "running",
    goal,
    started_at: started,
    created_at: created,
  }]),
  unknownStart: recentMissionRows([{id, status: "pending", goal: ""}]),
  snippet: recentMissionRows([{
    id,
    status: "stopped",
    goal: "x".repeat(RECENT_MISSION_SNIPPET_LIMIT + 12),
    created_at: created,
  }]),
  order: recentMissionRows([
    {id: "a", status: "completed", goal: "first", created_at: created},
    {id: "b", status: "failed", goal: "second", started_at: started},
  ]),
};

console.log(JSON.stringify(cases));
