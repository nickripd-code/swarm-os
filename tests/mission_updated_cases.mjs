import {missionUpdatedView, missionSnapshot, projectEvents} from "../app/static/state.mjs";

const NOW = Date.parse("2026-09-23T12:00:00Z");
const cases = {};

function view(mission, options = {}) {
  return missionUpdatedView(mission, {now: NOW, ...options});
}

cases.noMission = view(null);
cases.preview = view({updated_at: "2026-09-23T11:56:00Z"}, {preview: true});
cases.createdOnly = view({created_at: "2026-09-23T11:00:00Z", goal: "Ship it"});
cases.blank = view({updated_at: "   "});
cases.number = view({updated_at: NOW});
cases.object = view({updated_at: {iso: "2026-09-23T11:56:00Z"}});
cases.nullStamp = view({updated_at: null});
cases.garbage = view({updated_at: "yesterday"});
cases.dateOnly = view({updated_at: "2026-09-23"});
cases.yearOnly = view({updated_at: "2026"});
cases.impossibleDay = view({updated_at: "2026-02-31T00:00:00Z"});
cases.naive = view({updated_at: "2026-09-23T11:56:00"});
cases.missingNow = missionUpdatedView({updated_at: "2026-09-23T11:56:00Z"}, {});
cases.badNow = view({updated_at: "2026-09-23T11:56:00Z"}, {now: Number.NaN});

cases.minutes = view({
  created_at: "2026-09-23T08:00:00Z",
  updated_at: "2026-09-23T11:56:00Z",
});
cases.trimmed = view({updated_at: "  2026-09-23T11:56:00Z  "});
cases.micros = view({updated_at: "2026-09-23T11:59:00.123456Z"});
cases.offset = view({updated_at: "2026-09-23T07:56:00-04:00"});
cases.seconds = view({updated_at: "2026-09-23T11:59:01Z"});
cases.oneMinute = view({updated_at: "2026-09-23T11:59:00Z"});
cases.hours = view({updated_at: "2026-09-23T10:00:00Z"});
cases.oneDay = view({updated_at: "2026-09-22T12:00:00Z"});
cases.justNow = view({updated_at: "2026-09-23T12:00:00Z"});
cases.skewOk = view({updated_at: "2026-09-23T12:02:00Z"});
cases.skewHide = view({updated_at: "2026-09-23T12:02:01Z"});

const loaded = {
  id: "m1",
  goal: "Ship it",
  created_at: "2026-09-23T08:00:00Z",
  updated_at: "2026-09-23T11:56:00Z",
  status: "completed",
};
cases.snapshotKeepsStamp = missionSnapshot(loaded).updated_at;
cases.snapshotDoesNotInvent = missionSnapshot({
  id: "m2", goal: "No stamp", created_at: "2026-09-23T08:00:00Z", status: "running",
}).updated_at ?? null;
const projected = projectEvents(loaded, [{
  id: "e1",
  event_type: "mission.completed",
  created_at: "2026-09-23T11:59:30Z",
  payload: {summary: "done"},
}], 0);
cases.replayKeepsLoadedStamp = projected.mission.updated_at;
cases.replayView = view(projected.mission);

console.log(JSON.stringify(cases));
