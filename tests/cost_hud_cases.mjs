import {
  newState, applyEvent, costHudView, formatUsd, tokenTotal, ESTIMATE_UNAVAILABLE,
  BURN_WINDOW_MS, BURN_UNAVAILABLE, burnSampleFromEvent, liveBurnAt, pushBurnSample,
  burnRateView,
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

const NOW = 1_700_000_000_000;
function burnEvent(id, type, payload, createdAt) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: createdAt};
}
function recordBurn(samples, event, now) {
  const at = liveBurnAt(event, now);
  const sample = at === null ? null : burnSampleFromEvent(event, at);
  if (sample) pushBurnSample(samples, sample, now);
  return sample;
}

cases.burnIdle = burnRateView([], {nowMs: NOW});

const tokenBurn = [];
recordBurn(tokenBurn, burnEvent("b1", "llm.completed", {
  input_tokens: 100, output_tokens: 20, reasoning_tokens: 5,
}, new Date(NOW - 20000).toISOString()), NOW);
cases.burnTokensOnly = burnRateView(tokenBurn, {nowMs: NOW});

const summed = [];
recordBurn(summed, burnEvent("b1", "llm.completed", {input_tokens: 40, output_tokens: 10}, new Date(NOW - 40000).toISOString()), NOW);
recordBurn(summed, burnEvent("b2", "llm.completed", {input_tokens: 15, output_tokens: 5}, new Date(NOW - 10000).toISOString()), NOW);
cases.burnSummed = burnRateView(summed, {nowMs: NOW});

const stale = [];
recordBurn(stale, burnEvent("old", "llm.completed", {input_tokens: 900, output_tokens: 100}, new Date(NOW - 90000).toISOString()), NOW);
recordBurn(stale, burnEvent("fresh", "llm.completed", {input_tokens: 30, output_tokens: 2}, new Date(NOW - 5000).toISOString()), NOW);
cases.burnStale = {samples: stale.length, view: burnRateView(stale, {nowMs: NOW})};

const usd = [];
recordBurn(usd, burnEvent("u1", "llm.completed", {input_tokens: 10, output_tokens: 0}, new Date(NOW - 25000).toISOString()), NOW);
recordBurn(usd, burnEvent("u2", "budget.updated", {
  known: true, token_spent: 0.25, token_budget: 3, estimated_cost: 0.25,
}, new Date(NOW - 24000).toISOString()), NOW);
recordBurn(usd, burnEvent("u3", "budget.updated", {
  known: true, token_spent: 0.4, token_budget: 3, estimated_cost: 0.15,
}, new Date(NOW - 8000).toISOString()), NOW);
cases.burnUsd = burnRateView(usd, {nowMs: NOW});

const unknownSpend = [];
recordBurn(unknownSpend, burnEvent("t1", "llm.completed", {input_tokens: 8, output_tokens: 2}, new Date(NOW - 5000).toISOString()), NOW);
recordBurn(unknownSpend, burnEvent("t2", "budget.updated", {
  known: false, token_spent: 0, token_budget: 3, estimated_cost: null,
}, new Date(NOW - 4000).toISOString()), NOW);
cases.burnUnknownSpend = {
  sample: burnSampleFromEvent(burnEvent("t2", "budget.updated", {
    known: false, token_spent: 9, estimated_cost: 9,
  }), NOW),
  view: burnRateView(unknownSpend, {nowMs: NOW}),
};

const stringSpendBurn = [];
const stringSample = recordBurn(stringSpendBurn, burnEvent("s1", "budget.updated", {
  known: true, token_spent: "1.25", estimated_cost: "0.2",
}, new Date(NOW - 1000).toISOString()), NOW);
cases.burnStringSpend = {sample: stringSample, view: burnRateView(stringSpendBurn, {nowMs: NOW})};

const stringKnownBurn = [];
recordBurn(stringKnownBurn, burnEvent("k1", "llm.completed", {input_tokens: 4, output_tokens: 1}, new Date(NOW - 1000).toISOString()), NOW);
recordBurn(stringKnownBurn, burnEvent("k2", "budget.updated", {
  known: "true", token_spent: 2, estimated_cost: 2,
}, new Date(NOW - 900).toISOString()), NOW);
cases.burnStringKnown = burnRateView(stringKnownBurn, {nowMs: NOW});

const negativeBurn = [];
recordBurn(negativeBurn, burnEvent("n1", "llm.completed", {
  input_tokens: -8, output_tokens: 6, reasoning_tokens: -1,
}, new Date(NOW - 3000).toISOString()), NOW);
recordBurn(negativeBurn, burnEvent("n2", "budget.updated", {
  known: true, token_spent: -1, estimated_cost: -1,
}, new Date(NOW - 2000).toISOString()), NOW);
cases.burnNegative = burnRateView(negativeBurn, {nowMs: NOW});

const loneCumulative = [];
recordBurn(loneCumulative, burnEvent("c1", "budget.updated", {
  known: true, token_spent: 4.5, token_budget: 10,
}, new Date(NOW - 2000).toISOString()), NOW);
cases.burnLoneCumulative = burnRateView(loneCumulative, {nowMs: NOW});

const cumulativePair = [];
recordBurn(cumulativePair, burnEvent("c1", "budget.updated", {
  known: true, token_spent: 1,
}, new Date(NOW - 30000).toISOString()), NOW);
recordBurn(cumulativePair, burnEvent("c2", "budget.updated", {
  known: true, token_spent: 1.2,
}, new Date(NOW - 10000).toISOString()), NOW);
cases.burnCumulativePair = burnRateView(cumulativePair, {nowMs: NOW});

const straddling = [];
recordBurn(straddling, burnEvent("c0", "budget.updated", {
  known: true, token_spent: 5,
}, new Date(NOW - 120000).toISOString()), NOW - 120000);
recordBurn(straddling, burnEvent("c1", "budget.updated", {
  known: true, token_spent: 5.8,
}, new Date(NOW - 15000).toISOString()), NOW);
cases.burnStraddle = burnRateView(straddling, {nowMs: NOW});

const zeroKnownBurn = [];
recordBurn(zeroKnownBurn, burnEvent("z1", "budget.updated", {
  known: true, token_spent: 0, estimated_cost: 0, token_budget: 3,
}, new Date(NOW - 1000).toISOString()), NOW);
cases.burnZeroKnown = burnRateView(zeroKnownBurn, {nowMs: NOW});

const fabricated = [];
recordBurn(fabricated, burnEvent("f1", "llm.completed", {input_tokens: 50, output_tokens: 50}, new Date(NOW - 1000).toISOString()), NOW);
recordBurn(fabricated, burnEvent("f2", "budget.updated", {
  known: true, token_spent: 2, estimated_cost: 0.5,
}, new Date(NOW - 900).toISOString()), NOW);
cases.burnPreview = burnRateView(fabricated, {nowMs: NOW, preview: true});
cases.burnReplay = burnRateView(fabricated, {nowMs: NOW, replay: true});

cases.burnLiveAt = {
  missing: liveBurnAt({event_type: "llm.completed"}, NOW),
  stale: liveBurnAt({created_at: new Date(NOW - 90000).toISOString()}, NOW),
  future: liveBurnAt({created_at: new Date(NOW + 20000).toISOString()}, NOW),
  fresh: liveBurnAt({created_at: new Date(NOW - 1000).toISOString()}, NOW),
};
cases.BURN_WINDOW_MS = BURN_WINDOW_MS;
cases.BURN_UNAVAILABLE = BURN_UNAVAILABLE;

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
