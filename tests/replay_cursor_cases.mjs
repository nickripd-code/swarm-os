import {replayView, replayCursorChip, REPLAY_CURSOR_UNAVAILABLE} from "../app/static/state.mjs";

function event(id, type) {
  return {id, event_type: type, actor_id: "root", payload: {}, created_at: "2026-01-01T00:00:0" + id + "Z"};
}

const mission = {id: "m1", goal: "Ship the landing page", created_at: "2026-01-01T00:00:00Z"};
const log = [1, 2, 3, 4, 5].map((id) => event(id, "mission.started"));

function chip(view, loaded = mission) {
  return replayCursorChip(view, loaded);
}

const mid = replayView(log, 1, {mission});
const first = replayView(log, 0, {mission});
const end = replayView(log, 4, {mission});
const empty = replayView([], -1, {mission});
const unset = replayView(log, -1, {mission});
const preview = replayView(log, 1, {preview: true, mission});

const cases = {
  unavailableText: REPLAY_CURSOR_UNAVAILABLE,
  mid: chip(mid),
  midPosition: mid.positionLabel,
  first: chip(first),
  end: chip(end),
  empty: chip(empty),
  noMission: chip(mid, null),
  preview: chip(preview),
  unset: chip(unset),
  unsetPosition: unset.positionLabel,
  mismatch: chip({live: false, preview: false, cursor: 1, total: 5, positionLabel: "9 / 5"}),
  missingLabel: chip({live: false, preview: false, cursor: 1, total: 5}),
  fractional: chip({live: false, preview: false, cursor: 1.5, total: 5, positionLabel: "2 / 5"}),
  pastEnd: chip({live: false, preview: false, cursor: 5, total: 5, positionLabel: "6 / 5"}),
  stringCursor: chip({live: false, preview: false, cursor: "1", total: 5, positionLabel: "2 / 5"}),
  notLiveFlag: chip({preview: false, cursor: 1, total: 5, positionLabel: "2 / 5"}),
};

console.log(JSON.stringify(cases));
