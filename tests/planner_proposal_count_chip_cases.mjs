import {
  recordedPlannerProposalFeed, plannerProposalCountView, PLANNER_PROPOSAL_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const proposal = (id, extra = {}) => event(id, "planner.proposal", {action: "spawn", proposals: 9, ...extra});
const log = [
  event("j1", "judge.decision", {action: "spawn", proposals: 4}),
  proposal("p1"),
  event("c1", "controller.decision", {action: "finish", proposals: 2}),
  event("o1", "org.changed", {op: "spawn", proposals: 3}),
  proposal("p2", {action: "use_tool", token_spent: 1}),
  event("l1", "llm.completed", {kind: "proposal", proposals: 8, token_spent: 1}),
  event("m1", "agent.message", {kind: "assignment", text: "go", proposals: 1}),
  event("done", "mission.completed", {summary: "done", proposals: 6}),
  proposal("p3", {action: "finish", ok: false, proposals: 5000, token_spent: 4}),
];

const cases = {};
cases.unavailable = PLANNER_PROPOSAL_UNAVAILABLE;
cases.hidden = plannerProposalCountView(log, {visible: false});
cases.hiddenDefault = plannerProposalCountView(log);
cases.preview = plannerProposalCountView(log, {visible: false});
cases.missingNull = plannerProposalCountView(null, {visible: true});
cases.missingUndefined = plannerProposalCountView(undefined, {visible: true});
cases.missingObject = plannerProposalCountView({proposals: 4, events: []}, {visible: true});
cases.empty = plannerProposalCountView([], {visible: true});
cases.counted = plannerProposalCountView(log, {visible: true});
cases.ignoresJudge = plannerProposalCountView([
  event("judge", "judge.decision", {action: "finish", proposals: 3}),
], {visible: true});
cases.ignoresController = plannerProposalCountView([
  event("ctrl", "controller.decision", {action: "wait", proposals: 2}),
], {visible: true});
cases.ignoresOrg = plannerProposalCountView([
  event("org", "org.changed", {op: "reparent", proposals: 1}),
], {visible: true});
cases.ignoresMessage = plannerProposalCountView([
  event("msg", "agent.message", {kind: "idea", proposals: 2}),
], {visible: true});
cases.ignoresLlmCompleted = plannerProposalCountView([
  event("llm", "llm.completed", {kind: "proposal", proposals: 2, token_spent: 1}),
], {visible: true});
cases.ignoresMissionCompleted = plannerProposalCountView([
  event("done", "mission.completed", {summary: "ok", proposals: 6}),
], {visible: true});
cases.ignoresSpawned = plannerProposalCountView([
  event("spawn", "agent.spawned", {role: "planner", proposals: 1}),
], {visible: true});
cases.countsProposalWithoutAction = plannerProposalCountView([
  event("bare", "planner.proposal"),
], {visible: true});
cases.oneProposalNotPayload = plannerProposalCountView([
  proposal("big", {proposals: 5000, token_spent: 12, action: "spawn"}),
], {visible: true});
cases.skipsHoles = plannerProposalCountView([
  null, {payload: {action: "spawn", proposals: 10}}, proposal("one"),
], {visible: true});
cases.unreadableType = plannerProposalCountView([
  proposal("ok"),
  {id: "bad", event_type: 4, payload: {proposals: 1}},
], {visible: true});
cases.missingType = plannerProposalCountView([
  {id: "blank", payload: {proposals: 7}},
  proposal("one"),
], {visible: true});
cases.prefix = plannerProposalCountView(recordedPlannerProposalFeed(log, 1, true), {visible: true});
cases.prefixFirst = plannerProposalCountView(recordedPlannerProposalFeed(log, 0, true), {visible: true});
cases.prefixOne = plannerProposalCountView(recordedPlannerProposalFeed(log, 4, true), {visible: true});
cases.prefixAll = plannerProposalCountView(recordedPlannerProposalFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = plannerProposalCountView(recordedPlannerProposalFeed(log, -1, true), {visible: true});
cases.unloaded = recordedPlannerProposalFeed(log, log.length - 1, false);
cases.unloadedView = plannerProposalCountView(recordedPlannerProposalFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedPlannerProposalFeed([], -1, true);
cases.notArrayLog = recordedPlannerProposalFeed({length: 0, proposals: 1}, 0, true);

console.log(JSON.stringify(cases));
