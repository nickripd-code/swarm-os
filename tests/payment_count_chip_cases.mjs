import {
  recordedPaymentFeed, paymentCountView, PAYMENT_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-09-23T12:35:04Z"};
}

const payment = (id, extra = {}) => event(id, "payment.created", {
  recipient: "vendor", amount: 3, reason: "fixture", ...extra,
});
const log = [
  event("b1", "budget.updated", {token_spent: 0.4, known: true}),
  event("w1", "budget.warning", {token_spent: 2.4, token_budget: 3}),
  payment("p1"),
  event("s1", "payment.settled", {amount: 9}),
  event("m1", "mission.failed", {error: "stopped", failure_class: "RESOURCE_EXHAUSTED"}),
  payment("p2", {amount: 12.5, spent: 40}),
  event("t1", "tool.completed", {name: "search"}),
  payment("p3", {amount: 1}),
];

const cases = {};
cases.unavailable = PAYMENT_COUNT_UNAVAILABLE;
cases.hidden = paymentCountView(log, {visible: false});
cases.hiddenDefault = paymentCountView(log);
cases.preview = paymentCountView(log, {visible: false});
cases.missingNull = paymentCountView(null, {visible: true});
cases.missingUndefined = paymentCountView(undefined, {visible: true});
cases.missingObject = paymentCountView({payments: 4, events: []}, {visible: true});
cases.empty = paymentCountView([], {visible: true});
cases.counted = paymentCountView(log, {visible: true});
cases.ignoresBudgetUpdated = paymentCountView([
  event("budget", "budget.updated", {token_spent: 1.25, known: true, payments: 4}),
], {visible: true});
cases.ignoresBudgetWarning = paymentCountView([
  event("warn", "budget.warning", {token_spent: 2.4, token_budget: 3, payments: 2}),
], {visible: true});
cases.ignoresSettled = paymentCountView([
  event("settled", "payment.settled", {amount: 8, payments: 3}),
], {visible: true});
cases.ignoresMissionFailed = paymentCountView([
  event("miss", "mission.failed", {failure_class: "RESOURCE_EXHAUSTED", payments: 1}),
], {visible: true});
cases.ignoresUnrelated = paymentCountView([
  event("tool", "tool.completed", {name: "search", amount: 5}),
], {visible: true});
cases.onePaymentNotAmount = paymentCountView([
  payment("big", {amount: 5000, spent: 900, token_spent: 12}),
], {visible: true});
cases.skipsHoles = paymentCountView([null, {payload: {amount: 10}}, payment("one")], {visible: true});
cases.unreadableType = paymentCountView([
  payment("ok"),
  {id: "bad", event_type: 4, payload: {amount: 1}},
], {visible: true});
cases.missingType = paymentCountView([
  {id: "blank", payload: {amount: 7}},
  payment("one"),
], {visible: true});
cases.prefix = paymentCountView(recordedPaymentFeed(log, 1, true), {visible: true});
cases.prefixFirst = paymentCountView(recordedPaymentFeed(log, 0, true), {visible: true});
cases.prefixOne = paymentCountView(recordedPaymentFeed(log, 2, true), {visible: true});
cases.prefixAll = paymentCountView(recordedPaymentFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = paymentCountView(recordedPaymentFeed(log, -1, true), {visible: true});
cases.unloaded = recordedPaymentFeed(log, log.length - 1, false);
cases.unloadedView = paymentCountView(recordedPaymentFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedPaymentFeed([], -1, true);
cases.notArrayLog = recordedPaymentFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
