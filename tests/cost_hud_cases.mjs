import {
  newState, applyEvent, costHudView, formatUsd, tokenTotal, ESTIMATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

const cases = {};

cases.idle = costHudView(newState().usage);

const tokensOnly = newState();
applyEvent(tokensOnly, event("e1", "llm.completed", {
  input_tokens: 11, output_tokens: 7, reasoning_tokens: 3, model: "x",
}));
cases.tokensOnly = {usage: tokensOnly.usage, view: costHudView(tokensOnly.usage)};

const known = newState();
applyEvent(known, event("e1", "llm.completed", {input_tokens: 100, output_tokens: 20}));
applyEvent(known, event("e2", "budget.updated", {known: true, token_spent: 1.5, token_budget: 3}));
cases.known = {usage: known.usage, view: costHudView(known.usage)};

const unknownZero = newState();
applyEvent(unknownZero, event("e1", "llm.completed", {input_tokens: 40, output_tokens: 10}));
applyEvent(unknownZero, event("e2", "budget.updated", {
  known: false, token_spent: 0, token_budget: 3, estimated_cost: null,
}));
cases.unknownZero = {usage: unknownZero.usage, view: costHudView(unknownZero.usage)};

const missingSpend = newState();
applyEvent(missingSpend, event("e1", "budget.updated", {known: true, token_budget: 3}));
cases.missingSpend = {usage: missingSpend.usage, view: costHudView(missingSpend.usage)};

const stringSpend = newState();
applyEvent(stringSpend, event("e1", "budget.updated", {known: true, token_spent: "1.25"}));
cases.stringSpend = {usage: stringSpend.usage, view: costHudView(stringSpend.usage)};

const laterUnknown = newState();
applyEvent(laterUnknown, event("e1", "budget.updated", {known: true, token_spent: 0.5, token_budget: 3}));
applyEvent(laterUnknown, event("e2", "budget.updated", {known: false, token_spent: 0, estimated_cost: null}));
cases.laterUnknown = {usage: laterUnknown.usage, view: costHudView(laterUnknown.usage)};

const negative = newState();
applyEvent(negative, event("e1", "llm.completed", {input_tokens: -5, output_tokens: 4}));
applyEvent(negative, event("e2", "budget.updated", {known: true, token_spent: -1}));
cases.negative = {usage: negative.usage, view: costHudView(negative.usage)};

const fromMission = newState({token_spent: 9.99, limits: {max_token_cost: 3}});
cases.fromMission = {usage: fromMission.usage, view: costHudView(fromMission.usage)};

const stringKnown = newState();
applyEvent(stringKnown, event("e1", "budget.updated", {known: "true", token_spent: 2}));
cases.stringKnown = {usage: stringKnown.usage, view: costHudView(stringKnown.usage)};

const zeroKnown = newState();
applyEvent(zeroKnown, event("e1", "budget.updated", {known: true, token_spent: 0, token_budget: 3}));
cases.zeroKnown = {usage: zeroKnown.usage, view: costHudView(zeroKnown.usage)};

cases.formatUsd = {
  nan: formatUsd(Number.NaN),
  inf: formatUsd(Number.POSITIVE_INFINITY),
  none: formatUsd(null),
  zero: formatUsd(0),
  small: formatUsd(0.0012),
};
cases.tokenTotal = tokenTotal({input: 1, output: 2, reasoning: 3});
cases.ESTIMATE_UNAVAILABLE = ESTIMATE_UNAVAILABLE;

console.log(JSON.stringify(cases));
