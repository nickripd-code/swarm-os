import {applyEvent, missionPauseState, newState, PAUSE_STATE_UNAVAILABLE} from "../app/static/state.mjs";

function after(mission, events) {
  const state = newState(mission);
  events.forEach((event, index) => {
    applyEvent(state, {id: index + 1, payload: {}, ...event});
  });
  return missionPauseState(state.mission);
}

const cases = {
  missing: missionPauseState(undefined),
  null: missionPauseState(null),
  bareString: missionPauseState("paused"),
  list: missionPauseState([{status: "paused"}]),
  noStatus: missionPauseState({id: "m1", goal: "ship"}),
  nullStatus: missionPauseState({status: null}),
  blankStatus: missionPauseState({status: ""}),
  wrongCase: missionPauseState({status: "PAUSED"}),
  spaced: missionPauseState({status: " running"}),
  flagOnly: missionPauseState({paused: true}),
  flagFalse: missionPauseState({paused: false}),
  pausedAtOnly: missionPauseState({paused_at: "2026-09-23T00:00:00Z"}),
  pausedSecondsOnly: missionPauseState({paused_seconds: 30}),
  waiting: missionPauseState({status: "waiting"}),
  pending: missionPauseState({status: "pending"}),
  completed: missionPauseState({status: "completed"}),
  failed: missionPauseState({status: "failed"}),
  stopped: missionPauseState({status: "stopped"}),
  blocked: missionPauseState({status: "blocked"}),
  paused: missionPauseState({status: "paused"}),
  pausedWithoutTimestamp: missionPauseState({status: "paused", paused_at: null, paused_seconds: 0}),
  running: missionPauseState({status: "running"}),
  runningAfterPauseTime: missionPauseState({status: "running", paused_at: null, paused_seconds: 12}),
  flagDoesNotOverrideRunning: missionPauseState({status: "running", paused: true, paused_at: "2026-09-23T00:00:00Z"}),
  flagDoesNotOverridePaused: missionPauseState({status: "paused", paused: false}),
  pausedEvent: after({id: "m1", goal: "ship", status: "running"}, [
    {event_type: "mission.paused"},
  ]),
  resumeRequestedStaysPaused: after({id: "m1", goal: "ship", status: "paused"}, [
    {event_type: "mission.resume_requested"},
  ]),
  resumedEvent: after({id: "m1", goal: "ship", status: "paused"}, [
    {event_type: "mission.resumed"},
  ]),
  waitingIsNotRunning: after({id: "m1", goal: "ship", status: "running"}, [
    {event_type: "mission.waiting"},
  ]),
  startedSetsRunning: after({id: "m1", goal: "ship"}, [
    {event_type: "mission.started", payload: {mode: "standard"}},
  ]),
  unavailable: PAUSE_STATE_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
