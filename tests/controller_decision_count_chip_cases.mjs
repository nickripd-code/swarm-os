import {
  recordedControllerDecisionFeed, controllerDecisionCountView, CONTROLLER_DECISION_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const decision = (id, extra = {}) => event(id, "controller.decision", {action: "wait", decisions: 9, ...extra});
const log = [
  event("p1", "planner.proposal", {action: "spawn", decisions: 4}),
  decision("d1"),
  event("j1", "judge.decision", {action: "finish", decisions: 2}),
  event("o1", "org.changed", {op: "spawn", decisions: 3}),
  decision("d2", {action: "use_tool", token_spent: 1}),
  event("l1", "llm.completed", {kind: "decision", decisions: 8, token_spent: 1}),
  event("m1", "agent.message", {kind: "assignment", text: "go", decisions: 1}),
  event("c1", "mission.completed", {summary: "done", decisions: 6}),
  decision("d3", {action: "finish", ok: false, decisions: 5000, token_spent: 4}),
];

const cases = {};
cases.unavailable = CONTROLLER_DECISION_UNAVAILABLE;
cases.hidden = controllerDecisionCountView(log, {visible: false});
cases.hiddenDefault = controllerDecisionCountView(log);
cases.preview = controllerDecisionCountView(log, {visible: false});
cases.missingNull = controllerDecisionCountView(null, {visible: true});
cases.missingUndefined = controllerDecisionCountView(undefined, {visible: true});
cases.missingObject = controllerDecisionCountView({decisions: 4, events: []}, {visible: true});
cases.empty = controllerDecisionCountView([], {visible: true});
cases.counted = controllerDecisionCountView(log, {visible: true});
cases.ignoresProposal = controllerDecisionCountView([
  event("only", "planner.proposal", {action: "spawn", decisions: 2}),
], {visible: true});
cases.ignoresJudge = controllerDecisionCountView([
  event("judge", "judge.decision", {action: "finish", decisions: 3}),
], {visible: true});
cases.ignoresOrg = controllerDecisionCountView([
  event("org", "org.changed", {op: "reparent", decisions: 1}),
], {visible: true});
cases.ignoresMessage = controllerDecisionCountView([
  event("msg", "agent.message", {kind: "idea", decisions: 2}),
], {visible: true});
cases.ignoresLlmCompleted = controllerDecisionCountView([
  event("llm", "llm.completed", {kind: "decision", decisions: 2, token_spent: 1}),
], {visible: true});
cases.ignoresMissionCompleted = controllerDecisionCountView([
  event("done", "mission.completed", {summary: "ok", decisions: 6}),
], {visible: true});
cases.ignoresFallback = controllerDecisionCountView([
  event("fb", "controller.fallback", {action: "finish", decisions: 1}),
], {visible: true});
cases.countsDecisionWithoutAction = controllerDecisionCountView([
  event("bare", "controller.decision"),
], {visible: true});
cases.oneDecisionNotPayload = controllerDecisionCountView([
  decision("big", {decisions: 5000, token_spent: 12, action: "spawn"}),
], {visible: true});
cases.skipsHoles = controllerDecisionCountView([
  null, {payload: {action: "wait", decisions: 10}}, decision("one"),
], {visible: true});
cases.unreadableType = controllerDecisionCountView([
  decision("ok"),
  {id: "bad", event_type: 4, payload: {decisions: 1}},
], {visible: true});
cases.missingType = controllerDecisionCountView([
  {id: "blank", payload: {decisions: 7}},
  decision("one"),
], {visible: true});
cases.prefix = controllerDecisionCountView(recordedControllerDecisionFeed(log, 1, true), {visible: true});
cases.prefixFirst = controllerDecisionCountView(recordedControllerDecisionFeed(log, 0, true), {visible: true});
cases.prefixOne = controllerDecisionCountView(recordedControllerDecisionFeed(log, 4, true), {visible: true});
cases.prefixAll = controllerDecisionCountView(recordedControllerDecisionFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = controllerDecisionCountView(recordedControllerDecisionFeed(log, -1, true), {visible: true});
cases.unloaded = recordedControllerDecisionFeed(log, log.length - 1, false);
cases.unloadedView = controllerDecisionCountView(recordedControllerDecisionFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedControllerDecisionFeed([], -1, true);
cases.notArrayLog = recordedControllerDecisionFeed({length: 0, decisions: 1}, 0, true);

console.log(JSON.stringify(cases));
