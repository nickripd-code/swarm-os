import {
  recordedBudgetUpdateCountFeed, budgetUpdateCountView, BUDGET_UPDATE_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}, created_at = "2026-09-23T12:00:00Z") {
  return {id, event_type: type, payload, created_at};
}

const updated = (id, spent, extra = {}) => event(id, "budget.updated", {
  known: true, token_spent: spent, token_budget: 3, ...extra,
});

const log = [
  event("m1", "mission.started"),
  updated("u1", 1.25),
  event("w1", "budget.warning", {known: true, token_spent: 9.5, token_budget: 10}),
  event("p1", "payment.created", {amount: 1.25}),
  updated("bad-known", 0, {known: false}),
  updated("bad-string", "1.25"),
  updated("u2", 0),
  updated("string-known", 2, {known: "true"}),
  updated("neg", -1),
  updated("u3", 2.5),
  null,
  {payload: {known: true, token_spent: 9.5}},
];

const cases = {};
cases.unavailable = BUDGET_UPDATE_COUNT_UNAVAILABLE;
cases.hidden = budgetUpdateCountView(log, {visible: false});
cases.hiddenDefault = budgetUpdateCountView(log);
cases.preview = budgetUpdateCountView(log, {visible: false});
cases.missingNull = budgetUpdateCountView(null, {visible: true});
cases.missingUndefined = budgetUpdateCountView(undefined, {visible: true});
cases.missingObject = budgetUpdateCountView({updates: 4, events: []}, {visible: true});
cases.empty = budgetUpdateCountView([], {visible: true});
cases.counted = budgetUpdateCountView(log, {visible: true});
cases.ignoresWarning = budgetUpdateCountView([
  event("only-warn", "budget.warning", {known: true, token_spent: 9.5, token_budget: 10}),
], {visible: true});
cases.ignoresPayment = budgetUpdateCountView([
  event("pay", "payment.created", {amount: 1.25}),
], {visible: true});
cases.ignoresUnknown = budgetUpdateCountView([
  event("unk", "budget.updated", {known: false, token_spent: 0}),
], {visible: true});
cases.ignoresStringSpend = budgetUpdateCountView([updated("s", "1.25")], {visible: true});
cases.ignoresStringKnown = budgetUpdateCountView([updated("sk", 2, {known: "true"})], {visible: true});
cases.ignoresMissingPayload = budgetUpdateCountView([event("bare", "budget.updated")], {visible: true});
cases.ignoresArrayPayload = budgetUpdateCountView([
  event("arr", "budget.updated", ["1.25"]),
], {visible: true});
cases.ignoresNaN = budgetUpdateCountView([updated("nan", Number.NaN)], {visible: true});
cases.ignoresInfinity = budgetUpdateCountView([updated("inf", Number.POSITIVE_INFINITY)], {visible: true});
cases.ignoresNegative = budgetUpdateCountView([updated("neg-only", -0.5)], {visible: true});
cases.countsZeroSpend = budgetUpdateCountView([updated("zero", 0)], {visible: true});
cases.malformedDoesNotPoison = budgetUpdateCountView([
  updated("bad", "9.5"),
  updated("good", 2.5),
], {visible: true});
cases.skipsHoles = budgetUpdateCountView([
  null, {payload: {known: true, token_spent: 9.5}}, updated("one", 1),
], {visible: true});
cases.unreadableType = budgetUpdateCountView([
  updated("ok", 1),
  {event_type: 1, payload: {known: true, token_spent: 1}},
], {visible: true});
cases.prefix = budgetUpdateCountView(recordedBudgetUpdateCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = budgetUpdateCountView(recordedBudgetUpdateCountFeed(log, 0, true), {visible: true});
cases.prefixAll = budgetUpdateCountView(recordedBudgetUpdateCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = budgetUpdateCountView(recordedBudgetUpdateCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedBudgetUpdateCountFeed(log, log.length - 1, false);
cases.unloadedView = budgetUpdateCountView(recordedBudgetUpdateCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedBudgetUpdateCountFeed([], -1, true);
cases.notArrayLog = recordedBudgetUpdateCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
