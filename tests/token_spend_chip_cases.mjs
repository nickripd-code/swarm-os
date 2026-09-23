import {
  newState, applyEvent, tokenSpendChip, ESTIMATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

const mission = {id: "11111111-1111-4111-8111-111111111111", goal: "Ship the note"};
const wallet = {
  ...mission,
  budget: 10,
  spent: 4,
  token_spent: 2.25,
  limits: {max_token_cost: 3},
};

function chip(state, options) {
  return tokenSpendChip(state.mission, state.usage, options);
}

const idle = newState();
const loaded = newState(mission);
const walletOnly = newState(wallet);

const tokensOnly = newState(mission);
applyEvent(tokensOnly, event("e1", "llm.completed", {
  input_tokens: 11, output_tokens: 7, reasoning_tokens: 3, model: "x",
}));

const known = newState(mission);
applyEvent(known, event("e1", "llm.completed", {input_tokens: 100, output_tokens: 20}));
applyEvent(known, event("e2", "budget.updated", {known: true, token_spent: 1.5, token_budget: 3, remaining: 1.5}));

const unknownZero = newState(mission);
applyEvent(unknownZero, event("e1", "llm.completed", {input_tokens: 40, output_tokens: 10}));
applyEvent(unknownZero, event("e2", "budget.updated", {
  known: false, token_spent: 0, token_budget: 3, remaining: 3, estimated_cost: null,
}));

const missingSpend = newState(mission);
applyEvent(missingSpend, event("e1", "budget.updated", {known: true, token_budget: 3, remaining: 3}));

const stringSpend = newState(mission);
applyEvent(stringSpend, event("e1", "budget.updated", {known: true, token_spent: "1.25", token_budget: 3}));

const stringKnown = newState(mission);
applyEvent(stringKnown, event("e1", "budget.updated", {known: "true", token_spent: 1.25, token_budget: 3}));

const zeroKnown = newState(mission);
applyEvent(zeroKnown, event("e1", "budget.updated", {known: true, token_spent: 0, token_budget: 3}));

const negative = newState(mission);
applyEvent(negative, event("e1", "budget.updated", {known: true, token_spent: -1, token_budget: 3}));

const over = newState(mission);
applyEvent(over, event("e1", "budget.updated", {known: true, token_spent: 4, token_budget: 3}));

const spendOnly = newState(mission);
applyEvent(spendOnly, event("e1", "budget.updated", {known: true, token_spent: 0.5}));

const laterUnknown = newState(mission);
applyEvent(laterUnknown, event("e1", "budget.updated", {known: true, token_spent: 0.5, token_budget: 3}));
applyEvent(laterUnknown, event("e2", "budget.updated", {known: false, token_spent: 0, token_budget: 3}));

const cases = {
  none: tokenSpendChip(null, {known: true, cost: 1, budget: 3}),
  missingMission: tokenSpendChip(undefined, {known: true, cost: 1, budget: 3}),
  preview: tokenSpendChip(mission, known.usage, {preview: true}),
  stringPreviewFlag: tokenSpendChip(mission, known.usage, {preview: "true"}),
  idle: chip(idle),
  loaded: chip(loaded),
  walletOnly: chip(walletOnly),
  tokensOnly: chip(tokensOnly),
  known: chip(known),
  unknownZero: chip(unknownZero),
  missingSpend: chip(missingSpend),
  stringSpend: chip(stringSpend),
  stringKnown: chip(stringKnown),
  zeroKnown: chip(zeroKnown),
  negative: chip(negative),
  over: chip(over),
  spendOnly: chip(spendOnly),
  laterUnknown: chip(laterUnknown),
  nullUsage: tokenSpendChip(mission, null),
  ESTIMATE_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
