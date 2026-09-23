import {spendSummaryView, formatUsd, ESTIMATE_UNAVAILABLE} from "../app/static/spend-summary.mjs";

const recorded = {
  mission_id: "m1",
  state: "recorded",
  reason: "recorded",
  providers_configured: false,
  live_spend_enabled: false,
  live_payments: false,
  token_estimate_known: true,
  token_estimate: 1.5,
  token_budget: 3,
  tokens: {input: 11, output: 7, reasoning: 3, total: 21},
  tokens_recorded: true,
  burn_known: true,
  burn_usd_per_hour: 1.5,
  payment_known: true,
  payment_spent: 0,
  payment_budget: 0,
  note: "Recorded token estimate. Not an invoice. Model providers are unset. Live spend is off.",
};

const empty = {
  mission_id: null,
  state: "unavailable",
  reason: "no_mission",
  providers_configured: false,
  live_spend_enabled: false,
  token_estimate_known: false,
  token_estimate: null,
  tokens_recorded: false,
  burn_known: false,
  burn_usd_per_hour: null,
  payment_known: false,
  payment_spent: null,
  payment_budget: null,
  note: "No mission selected. No cost data. Model providers are unset. Live spend is off.",
};

const tokensOnly = {
  mission_id: "m1",
  providers_configured: true,
  live_spend_enabled: false,
  token_estimate_known: false,
  token_estimate: null,
  tokens_recorded: true,
  tokens: {total: 21},
  burn_known: false,
  payment_known: true,
  payment_spent: 0,
  payment_budget: 2,
  note: "No cost data. Live spend is off.",
};

const cases = {
  empty: spendSummaryView(empty),
  recorded: spendSummaryView(recorded),
  tokensOnly: spendSummaryView(tokensOnly),
  preview: spendSummaryView(recorded, {preview: true}),
  missing: spendSummaryView(null),
  stringKnown: spendSummaryView({
    ...recorded,
    token_estimate_known: "true",
    token_estimate: 1.5,
    burn_known: true,
  }),
  stringSpend: spendSummaryView({
    ...recorded,
    token_estimate_known: true,
    token_estimate: "1.50",
  }),
  liveOn: spendSummaryView({...empty, live_spend_enabled: true, providers_configured: true}),
  formatUsd: {
    nan: formatUsd(Number.NaN),
    none: formatUsd(null),
    negative: formatUsd(-1),
    zero: formatUsd(0),
    small: formatUsd(0.0012),
    plain: formatUsd(1.5),
  },
  ESTIMATE_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
