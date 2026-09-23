import {
  recordedBudgetWarningCountFeed, budgetWarningCountView, BUDGET_WARNING_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}, created_at = "2026-09-23T12:00:00Z") {
  return {id, event_type: type, payload, created_at};
}

const warning = (id, spent, budget, extra = {}) => event(id, "budget.warning", {
  token_spent: spent, token_budget: budget, currency: "USD", estimate: true, ...extra,
});

const log = [
  event("u1", "budget.updated", {known: true, token_spent: 1.25, token_budget: 3}),
  warning("w1", 9.5, 10),
  event("p1", "payment.spent", {spent: 0.8, budget: 100}),
  warning("bad-string", "9.5", "10"),
  warning("w2", 0, 0),
  event("v1", "verification.started", {token_spent: 9.5, token_budget: 10}),
  warning("neg", -1, 10),
  warning("w3", 2.5, 10, {remaining: 7.5}),
  null,
  {payload: {token_spent: 9.5, token_budget: 10}},
];

const cases = {};
cases.unavailable = BUDGET_WARNING_COUNT_UNAVAILABLE;
cases.hidden = budgetWarningCountView(log, {visible: false});
cases.hiddenDefault = budgetWarningCountView(log);
cases.preview = budgetWarningCountView(log, {visible: false});
cases.missingNull = budgetWarningCountView(null, {visible: true});
cases.missingUndefined = budgetWarningCountView(undefined, {visible: true});
cases.missingObject = budgetWarningCountView({warnings: 4, events: []}, {visible: true});
cases.empty = budgetWarningCountView([], {visible: true});
cases.counted = budgetWarningCountView(log, {visible: true});
cases.ignoresUpdated = budgetWarningCountView([
  event("only", "budget.updated", {known: true, token_spent: 9.5, token_budget: 10}),
], {visible: true});
cases.ignoresPayment = budgetWarningCountView([
  event("pay", "payment.completed", {spent: 1.25, budget: 100}),
], {visible: true});
cases.ignoresStringNumbers = budgetWarningCountView([warning("s", "1.25", "3")], {visible: true});
cases.ignoresMissingPayload = budgetWarningCountView([event("bare", "budget.warning")], {visible: true});
cases.ignoresArrayPayload = budgetWarningCountView([
  event("arr", "budget.warning", ["9.5", "10"]),
], {visible: true});
cases.ignoresNaN = budgetWarningCountView([warning("nan", Number.NaN, 10)], {visible: true});
cases.ignoresInfinity = budgetWarningCountView([warning("inf", Number.POSITIVE_INFINITY, 10)], {visible: true});
cases.ignoresNegative = budgetWarningCountView([warning("neg-only", -0.5, 10)], {visible: true});
cases.countsZeroSpend = budgetWarningCountView([warning("zero", 0, 3)], {visible: true});
cases.malformedDoesNotPoison = budgetWarningCountView([
  warning("bad", "9.5", 10),
  warning("good", 2.5, 10),
], {visible: true});
cases.skipsHoles = budgetWarningCountView([null, {payload: {token_spent: 9.5, token_budget: 10}}, warning("one", 1, 10)], {visible: true});
cases.prefix = budgetWarningCountView(recordedBudgetWarningCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = budgetWarningCountView(recordedBudgetWarningCountFeed(log, 0, true), {visible: true});
cases.prefixAll = budgetWarningCountView(recordedBudgetWarningCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = budgetWarningCountView(recordedBudgetWarningCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedBudgetWarningCountFeed(log, log.length - 1, false);
cases.unloadedView = budgetWarningCountView(recordedBudgetWarningCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedBudgetWarningCountFeed([], -1, true);
cases.notArrayLog = recordedBudgetWarningCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
