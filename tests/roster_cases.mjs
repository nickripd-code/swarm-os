import {
  newState, applyEvent, agentRosterView,
  ROSTER_NO_MISSION, ROSTER_EMPTY, ROSTER_PREVIEW, ROSTER_REPLAY_EMPTY,
  ROSTER_NOTE_LIVE, ROSTER_NOTE_PREVIEW, ROSTER_NOTE_REPLAY,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: payload.id || "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

const mission = {missionLoaded: true};
const cases = {};

cases.standby = agentRosterView([{id: "a", role: "researcher", status: "running", parent_id: null}], {});
cases.preview = agentRosterView(
  [{id: "root", role: "mission_controller", status: "running", parent_id: null}],
  {preview: true, missionLoaded: true},
);
cases.emptyMission = agentRosterView([], mission);
cases.replayEmpty = agentRosterView(new Map(), {missionLoaded: true, replay: true});

const linked = newState({id: "m", goal: "g", status: "running"});
applyEvent(linked, event("s1", "agent.spawned", {
  id: "root", parent_id: null, role: "mission_controller", status: "running", depth: 4,
}));
applyEvent(linked, event("s2", "agent.spawned", {
  id: "child", parent_id: "root", role: "researcher", status: "running", depth: 9,
}));
applyEvent(linked, event("s3", "agent.spawned", {
  id: "leaf", parent_id: "child", role: "reviewer", status: "created",
}));
cases.linked = agentRosterView(linked.agents, mission);

const reparent = newState({id: "m", goal: "g", status: "running"});
applyEvent(reparent, event("s1", "agent.spawned", {
  id: "root", parent_id: null, role: "mission_controller", status: "running",
}));
applyEvent(reparent, event("s2", "agent.spawned", {
  id: "other", parent_id: null, role: "strategist", status: "running",
}));
applyEvent(reparent, event("s3", "agent.spawned", {
  id: "child", parent_id: "root", role: "researcher", status: "running",
}));
applyEvent(reparent, event("r1", "agent.reparented", {
  id: "child", agent_id: "child", parent_id: "other", role: "researcher",
}));
applyEvent(reparent, event("ghost", "agent.reparented", {
  id: "ghost", parent_id: "root", role: "invented",
}));
applyEvent(reparent, event("retire-ghost", "agent.retired", {
  id: "nobody", role: "invented", status: "stopped",
}));
applyEvent(reparent, event("ret1", "agent.retired", {id: "child", status: "stopped"}));
cases.reparent = {
  ids: [...reparent.agents.keys()],
  view: agentRosterView(reparent.agents, mission),
};

cases.missing = agentRosterView([
  {id: "child", role: "researcher", status: "blocked", parent_id: "not-loaded", depth: 3},
], mission);

cases.island = agentRosterView([
  {id: "mid", role: "researcher", status: "running", parent_id: "absent"},
  {id: "leaf", role: "reviewer", status: "created", parent_id: "mid"},
], mission);

cases.cycle = agentRosterView([
  {id: "a", role: "alpha", status: "running", parent_id: "b"},
  {id: "b", role: "beta", status: "running", parent_id: "a"},
], mission);

cases.self = agentRosterView([
  {id: "loop", role: "reviewer", status: "running", parent_id: "loop"},
], mission);

cases.blankRole = agentRosterView([
  {id: "x", role: "", status: "", parent_id: "   "},
  {id: "", role: "skipped", status: "running"},
  {id: "y", role: "writer", status: "running", parent_id: {id: "x"}},
], mission);

cases.duplicate = agentRosterView([
  {id: "a", role: "first", status: "created", parent_id: null},
  {id: "a", role: "second", status: "running", parent_id: null},
], mission);

cases.updated = (() => {
  const state = newState({id: "m", goal: "g", status: "running"});
  applyEvent(state, event("s1", "agent.spawned", {
    id: "root", parent_id: null, role: "mission_controller", status: "running",
  }));
  applyEvent(state, event("s2", "agent.spawned", {
    id: "child", parent_id: "root", role: "researcher", status: "running",
  }));
  applyEvent(state, event("u1", "agent.updated", {
    id: "child", parent_id: null, role: "researcher", status: "completed",
  }));
  return agentRosterView(state.agents, mission);
})();

cases.labels = {
  noMission: ROSTER_NO_MISSION,
  empty: ROSTER_EMPTY,
  preview: ROSTER_PREVIEW,
  replayEmpty: ROSTER_REPLAY_EMPTY,
  live: ROSTER_NOTE_LIVE,
  previewNote: ROSTER_NOTE_PREVIEW,
  replay: ROSTER_NOTE_REPLAY,
};

process.stdout.write(JSON.stringify(cases));
