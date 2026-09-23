import {
  recordedJudgeDecisionFeed, judgeDecisionCountView, JUDGE_DECISION_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const judged = (id, extra = {}) => event(id, "judge.decision", {action: "spawn", decisions: 9, ...extra});
const log = [
  event("p1", "planner.proposal", {action: "spawn", decisions: 4}),
  judged("j1"),
  event("c1", "controller.decision", {action: "finish", decisions: 2}),
  event("o1", "org.changed", {op: "spawn", decisions: 3}),
  judged("j2", {action: "replace", token_spent: 1}),
  event("l1", "llm.completed", {kind: "decision", decisions: 8, token_spent: 1}),
  event("m1", "agent.message", {kind: "assignment", text: "go", decisions: 1}),
  event("done", "mission.completed", {summary: "done", decisions: 6}),
  judged("j3", {action: "retire", ok: false, decisions: 5000, token_spent: 4}),
];

const cases = {};
cases.unavailable = JUDGE_DECISION_UNAVAILABLE;
cases.hidden = judgeDecisionCountView(log, {visible: false});
cases.hiddenDefault = judgeDecisionCountView(log);
cases.preview = judgeDecisionCountView(log, {visible: false});
cases.missingNull = judgeDecisionCountView(null, {visible: true});
cases.missingUndefined = judgeDecisionCountView(undefined, {visible: true});
cases.missingObject = judgeDecisionCountView({decisions: 4, events: []}, {visible: true});
cases.empty = judgeDecisionCountView([], {visible: true});
cases.counted = judgeDecisionCountView(log, {visible: true});
cases.ignoresController = judgeDecisionCountView([
  event("only", "controller.decision", {action: "wait", decisions: 2}),
], {visible: true});
cases.ignoresProposal = judgeDecisionCountView([
  event("proposal", "planner.proposal", {action: "spawn", decisions: 3}),
], {visible: true});
cases.ignoresOrg = judgeDecisionCountView([
  event("org", "org.changed", {op: "reparent", decisions: 1}),
], {visible: true});
cases.ignoresMessage = judgeDecisionCountView([
  event("msg", "agent.message", {kind: "idea", decisions: 2}),
], {visible: true});
cases.ignoresLlmCompleted = judgeDecisionCountView([
  event("llm", "llm.completed", {kind: "decision", decisions: 2, token_spent: 1}),
], {visible: true});
cases.ignoresMissionCompleted = judgeDecisionCountView([
  event("done", "mission.completed", {summary: "ok", decisions: 6}),
], {visible: true});
cases.ignoresFallback = judgeDecisionCountView([
  event("fb", "controller.fallback", {action: "finish", decisions: 1}),
], {visible: true});
cases.countsJudgeWithoutAction = judgeDecisionCountView([
  event("bare", "judge.decision"),
], {visible: true});
cases.oneJudgeNotPayload = judgeDecisionCountView([
  judged("big", {decisions: 5000, token_spent: 12, action: "spawn"}),
], {visible: true});
cases.skipsHoles = judgeDecisionCountView([
  null, {payload: {action: "spawn", decisions: 10}}, judged("one"),
], {visible: true});
cases.unreadableType = judgeDecisionCountView([
  judged("ok"),
  {id: "bad", event_type: 4, payload: {decisions: 1}},
], {visible: true});
cases.missingType = judgeDecisionCountView([
  {id: "blank", payload: {decisions: 7}},
  judged("one"),
], {visible: true});
cases.prefix = judgeDecisionCountView(recordedJudgeDecisionFeed(log, 1, true), {visible: true});
cases.prefixFirst = judgeDecisionCountView(recordedJudgeDecisionFeed(log, 0, true), {visible: true});
cases.prefixOne = judgeDecisionCountView(recordedJudgeDecisionFeed(log, 4, true), {visible: true});
cases.prefixAll = judgeDecisionCountView(recordedJudgeDecisionFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = judgeDecisionCountView(recordedJudgeDecisionFeed(log, -1, true), {visible: true});
cases.unloaded = recordedJudgeDecisionFeed(log, log.length - 1, false);
cases.unloadedView = judgeDecisionCountView(recordedJudgeDecisionFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedJudgeDecisionFeed([], -1, true);
cases.notArrayLog = recordedJudgeDecisionFeed({length: 0, decisions: 1}, 0, true);

console.log(JSON.stringify(cases));
