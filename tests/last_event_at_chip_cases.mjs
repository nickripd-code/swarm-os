import {lastEventAtView} from "../app/static/state.mjs";

const mission = {id: "m1", goal: "Ship the note", status: "running"};
const cases = {};

function view(events, options = {}) {
  return lastEventAtView(events, {mission, ...options});
}

cases.noMission = lastEventAtView(
  [{id: 1, created_at: "2026-09-23T12:35:04Z"}],
  {mission: null},
);
cases.preview = view(
  [{id: 1, created_at: "2026-09-23T12:35:04Z"}],
  {preview: true},
);
cases.noEvents = view([]);
cases.notAnArray = view(null);
cases.missingTime = view([{id: 1, event_type: "mission.started"}]);
cases.blankTime = view([{id: 1, created_at: ""}]);
cases.whitespace = view([{id: 1, created_at: " 2026-09-23T12:35:04Z"}]);
cases.numericZero = view([{id: 1, created_at: 0}]);
cases.numericNow = view([{id: 1, created_at: 1758630904000}]);
cases.stringZero = view([{id: 1, created_at: "0"}]);
cases.epoch = view([{id: 1, created_at: "1970-01-01T00:00:00Z"}]);
cases.epochFraction = view([{id: 1, created_at: "1970-01-01T00:00:00.000000Z"}]);
cases.epochOffset = view([{id: 1, created_at: "1970-01-01T01:00:00+01:00"}]);
cases.naive = view([{id: 1, created_at: "2026-09-23T12:35:04"}]);
cases.garbage = view([{id: 1, created_at: "just now"}]);
cases.impossibleDay = view([{id: 1, created_at: "2026-02-31T12:35:04Z"}]);
cases.newestInvalid = view([
  {id: 1, created_at: "2026-09-23T12:00:00Z"},
  {id: 2, created_at: ""},
]);
cases.clock = view([
  {id: 1, created_at: "2026-09-23T08:00:00Z"},
  {id: 2, created_at: "2026-09-23T12:35:04.123456Z"},
]);
cases.offset = view([{id: 1, created_at: "2026-09-23T08:35:04-04:00"}]);
cases.nonObject = view(["2026-09-23T12:35:04Z"]);

console.log(JSON.stringify(cases));
