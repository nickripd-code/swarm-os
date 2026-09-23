import {
  newState, applyEvent, missionModelChip, projectEvents, recordedModelId, truncateModelId,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

const mission = {id: "m1", goal: "Ship the launch plan", created_at: "2026-01-01T00:00:00Z"};
const cases = {};

cases.noMission = missionModelChip(newState());
cases.preview = (() => {
  const state = newState(mission);
  state.preview = true;
  state.lastModel = "gpt-6-astra";
  return missionModelChip(state);
})();
cases.missing = missionModelChip(newState(mission));

const blank = newState(mission);
applyEvent(blank, event("b1", "llm.started", {kind: "decision", model: "  "}));
applyEvent(blank, event("b2", "llm.completed", {kind: "decision", model: ""}));
applyEvent(blank, event("b3", "llm.failed", {kind: "decision"}));
applyEvent(blank, event("b4", "llm.completed", {kind: "decision", model: 12}));
applyEvent(blank, event("b5", "budget.updated", {model: "gpt-6-astra", known: false, token_spent: 0}));
cases.blank = {lastModel: blank.lastModel, chip: missionModelChip(blank)};

const current = newState(mission);
applyEvent(current, event("c1", "llm.started", {kind: "decision", model: "gpt-6-astra"}));
cases.started = {lastModel: current.lastModel, chip: missionModelChip(current)};
applyEvent(current, event("c2", "llm.completed", {
  kind: "decision", model: "gpt-6-astra-2026-09", input_tokens: 3, output_tokens: 1,
}));
cases.completed = {lastModel: current.lastModel, chip: missionModelChip(current)};
applyEvent(current, event("c3", "llm.failover", {kind: "work", model: "accounts/fireworks/models/llama-v3p1-8b-instruct"}));
cases.failover = {lastModel: current.lastModel, chip: missionModelChip(current)};
applyEvent(current, event("c4", "llm.completed", {kind: "work", model: "   "}));
cases.blankDoesNotErase = {lastModel: current.lastModel, chip: missionModelChip(current)};

const replayLog = [
  event("r1", "mission.started", {mode: "running"}),
  event("r2", "llm.started", {kind: "decision", model: "command-a-03-2025"}),
];
cases.beforeModel = missionModelChip(projectEvents(mission, replayLog, 0));
cases.atModel = missionModelChip(projectEvents(mission, replayLog, 1));

cases.recorded = {
  spaces: recordedModelId("  grok-3  "),
  empty: recordedModelId(""),
  nullish: recordedModelId(null),
  object: recordedModelId({model: "gpt-6-astra"}),
  newline: recordedModelId("gpt-6\nastra"),
};
const longId = "accounts/fireworks/models/llama-v3p1-8b-instruct";
const pair = "model-" + "🙂";
cases.truncate = {
  short: truncateModelId("gpt-6-astra"),
  long: truncateModelId(longId),
  longFullLength: Array.from(longId).length,
  pair: truncateModelId(pair, 6),
  pairChars: Array.from(truncateModelId(pair, 6)),
};

console.log(JSON.stringify(cases));
