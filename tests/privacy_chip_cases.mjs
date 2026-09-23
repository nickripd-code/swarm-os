import {applyEvent, missionPrivacy, newState, PRIVACY_UNAVAILABLE, projectEvents} from "../app/static/state.mjs";

function after(mission, events) {
  const state = newState(mission);
  events.forEach((event, index) => {
    applyEvent(state, {id: index + 1, payload: {}, ...event});
  });
  return missionPrivacy(state.mission);
}

const cases = {
  missing: missionPrivacy(undefined),
  null: missionPrivacy(null),
  bareString: missionPrivacy("local_only"),
  list: missionPrivacy([{privacy: "local_only"}]),
  noPrivacy: missionPrivacy({id: "m1", goal: "ship"}),
  nullPrivacy: missionPrivacy({privacy: null}),
  blankPrivacy: missionPrivacy({privacy: ""}),
  wrongCase: missionPrivacy({privacy: "LOCAL_ONLY"}),
  spaced: missionPrivacy({privacy: " local_only"}),
  flagOnly: missionPrivacy({local_only: true}),
  flagFalse: missionPrivacy({local_only: false, cloud_allowed: true}),
  objectPrivacy: missionPrivacy({privacy: {mode: "local_only"}}),
  numberPrivacy: missionPrivacy({privacy: 1}),
  unknown: missionPrivacy({privacy: "private"}),
  cloudAllowed: missionPrivacy({privacy: "cloud_allowed"}),
  localOnly: missionPrivacy({privacy: "local_only"}),
  flagDoesNotOverrideCloud: missionPrivacy({privacy: "cloud_allowed", local_only: true}),
  flagDoesNotOverrideLocal: missionPrivacy({privacy: "local_only", cloud_allowed: true}),
  eventDoesNotInvent: after({id: "m1", goal: "ship"}, [
    {event_type: "mission.started", payload: {privacy: "local_only", mode: "openai"}},
  ]),
  eventDoesNotOverwrite: after({id: "m1", goal: "ship", privacy: "local_only"}, [
    {event_type: "mission.started", payload: {privacy: "cloud_allowed"}},
  ]),
  replayKeepsLoaded: missionPrivacy(projectEvents(
    {id: "m1", goal: "ship", privacy: "local_only", status: "completed"},
    [{id: 1, event_type: "mission.started", payload: {mode: "openai"}, created_at: "2026-01-01T00:00:01Z"}],
    0,
  ).mission),
  replayOmitsUnreadable: missionPrivacy(projectEvents(
    {id: "m1", goal: "ship", privacy: "secret", status: "completed"},
    [{id: 1, event_type: "mission.started", payload: {privacy: "cloud_allowed"}, created_at: "2026-01-01T00:00:01Z"}],
    0,
  ).mission),
  unavailable: PRIVACY_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
