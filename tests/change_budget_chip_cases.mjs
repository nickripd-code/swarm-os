import {
  applyEvent, changeBudgetView, CHANGE_BUDGET_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "a1", payload, created_at: "2026-01-01T00:00:00Z"};
}

const cases = {};
cases.CHANGE_BUDGET_UNAVAILABLE = CHANGE_BUDGET_UNAVAILABLE;
cases.standby = changeBudgetView(null);
cases.emptyMission = changeBudgetView({id: "m1", goal: "Ship the note", status: "running"});
cases.otherBudgets = changeBudgetView({
  id: "m2",
  goal: "Stay inside the other caps",
  budget: 10,
  spent: 4,
  token_spent: 1.5,
  limits: {max_tool_calls: 200, max_token_cost: 3, max_payment_amount: 1},
});
cases.preview = changeBudgetView({
  id: "preview",
  goal: "Design a launch plan for a small business",
  status: "running",
});
cases.recorded = changeBudgetView({
  id: "m3",
  goal: "Recorded change budget",
  change_budget: {used: 2, remaining: 3, cap: 5},
});
cases.zeroRecorded = changeBudgetView({
  id: "m4",
  change_budget: {used: 0, remaining: 0, cap: 0, known: true},
});
cases.inconsistent = changeBudgetView({
  id: "m5",
  change_budget: {used: 2, remaining: 2, cap: 5},
});
cases.strings = changeBudgetView({
  id: "m6",
  change_budget: {used: "2", remaining: "3", cap: "5"},
});
cases.fraction = changeBudgetView({
  id: "m7",
  change_budget: {used: 1.5, remaining: 1.5, cap: 3},
});
cases.negative = changeBudgetView({
  id: "m8",
  change_budget: {used: -1, remaining: 2, cap: 1},
});
cases.missingRemaining = changeBudgetView({
  id: "m9",
  change_budget: {used: 1, cap: 4},
});
cases.knownFalse = changeBudgetView({
  id: "m10",
  change_budget: {used: 1, remaining: 1, cap: 2, known: false},
});
cases.array = changeBudgetView({id: "m11", change_budget: [1, 1, 2]});
cases.topLevelCounts = changeBudgetView({id: "m12", used: 1, remaining: 1, cap: 2});

const afterTokenBudget = {
  id: "m13",
  goal: "Token events are not a change budget",
  agents: new Map(),
  tasks: new Map(),
  seen: new Set(),
  events: [],
  usage: {input: 0, output: 0, reasoning: 0, cost: null, budget: null, known: false},
  decisions: 0,
  preview: false,
};
applyEvent(afterTokenBudget, event("e1", "budget.updated", {
  known: true, token_spent: 1.25, token_budget: 3,
}));
applyEvent(afterTokenBudget, event("e2", "tool.completed", {name: "selfmod.propose", changes: 4}));
cases.afterEvents = changeBudgetView(afterTokenBudget);

console.log(JSON.stringify(cases));
