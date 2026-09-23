import {lastEventTypeView, projectEvents, recordEvent} from "../app/static/state.mjs";

const mission = {id: "m1", goal: "Ship it", status: "running"};
const cases = {};

function view(log, options = {}) {
  return lastEventTypeView(log, {mission, ...options});
}

cases.noMission = lastEventTypeView([{id: 1, event_type: "agent.spawned"}], {});
cases.preview = view([{id: 1, event_type: "agent.spawned"}], {preview: true});
cases.previewMission = lastEventTypeView(
  [{id: 1, event_type: "agent.spawned"}],
  {mission: {id: "preview", goal: "Design a launch plan"}, preview: true},
);
cases.empty = view([]);
cases.missingLog = view(null);
cases.notArray = view({0: {id: 1, event_type: "agent.spawned"}, length: 1});

cases.latest = view([
  {id: 1, event_type: "agent.spawned", created_at: "2026-09-23T12:00:00Z", payload: {name: "root"}},
  {id: 2, event_type: "llm.completed", created_at: "2026-09-23T11:00:00Z", name: "done", type: "other"},
]);
cases.ignoresEarlier = cases.latest.eventType;

cases.tailNotTimestamp = view([
  {id: 2, event_type: "mission.completed", created_at: "2026-09-23T12:00:00Z"},
  {id: 1, event_type: "agent.spawned", created_at: "2026-09-23T11:00:00Z"},
]);

cases.blank = view([{id: 1, event_type: "   ", name: "agent.spawned"}]);
cases.emptyType = view([{id: 1, event_type: "", type: "agent.spawned"}]);
cases.padded = view([{id: 1, event_type: " agent.spawned"}]);
cases.number = view([{id: 1, event_type: 1, name: "agent.spawned"}]);
cases.objectType = view([{id: 1, event_type: {value: "agent.spawned"}}]);
cases.missingType = view([{id: 1, name: "agent.spawned", type: "agent.spawned", payload: {event_type: "agent.spawned"}}]);
cases.nullEvent = view([{id: 1, event_type: "agent.spawned"}, null]);
cases.newline = view([{id: 1, event_type: "agent.spawned\n"}]);
cases.historical = view([{id: 1, event_type: "custom.historical"}]);

const log = [];
recordEvent(log, {id: 1, event_type: "mission.started"});
recordEvent(log, {id: 1, event_type: "agent.spawned"});
recordEvent(log, {id: 2, event_type: "task.completed"});
cases.recorded = view(log);
cases.duplicateIgnored = log.map(event => event.event_type);

const projected = projectEvents(mission, [
  {id: 1, event_type: "agent.spawned", payload: {id: "root", role: "mission_controller"}},
  {id: 2, event_type: "mission.completed", payload: {summary: "done"}},
], 0);
cases.replayFrame = projected.events[0]?.event_type || "";
cases.replayChip = view([
  {id: 1, event_type: "agent.spawned", payload: {id: "root", role: "mission_controller"}},
  {id: 2, event_type: "mission.completed", payload: {summary: "done"}},
]);

console.log(JSON.stringify(cases));
