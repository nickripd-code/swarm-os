import {
  newState, applyEvent, recordEvent, projectEvents, replayView, stepReplay,
  clampReplayIndex, isReplayLive, missionSnapshot, replayElapsedMs, costHudView,
  ESTIMATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload, created_at = "2026-01-01T00:00:0" + id + "Z") {
  return {id, event_type: type, actor_id: "root", payload, created_at};
}

const mission = {
  id: "m1",
  goal: "Ship the landing page",
  created_at: "2026-01-01T00:00:00Z",
  status: "completed",
  result: {summary: "done", mode: "openai"},
  pending_question: {question_id: "q-stale", question: "stale"},
  token_spent: 9.99,
};

const log = [];
recordEvent(log, event(1, "mission.started", {mode: "openai"}));
recordEvent(log, event(2, "agent.spawned", {
  id: "root", role: "mission_controller", purpose: "run it", capabilities: ["spawn"], status: "running", depth: 0,
}));
recordEvent(log, event(3, "llm.completed", {input_tokens: 10, output_tokens: 4, model: "x"}));
recordEvent(log, event(4, "budget.updated", {known: true, token_spent: 1.25, token_budget: 3}));
recordEvent(log, event(5, "mission.completed", {summary: "verified result", mode: "openai"}));

const cases = {};
cases.duplicateIgnored = recordEvent(log, event(3, "llm.completed", {input_tokens: 99, output_tokens: 99}));
cases.logLength = log.length;

const empty = projectEvents(mission, [], -1);
cases.empty = {
  agents: empty.agents.size,
  status: empty.mission.status,
  result: empty.mission.result,
  tokens: empty.usage.input + empty.usage.output,
  replay: empty.replay,
  view: replayView([], -1, {mission}),
};

const atSpawn = projectEvents(mission, log, 1);
cases.atSpawn = {
  agents: [...atSpawn.agents.values()].map(a => ({id: a.id, role: a.role, status: a.status})),
  status: atSpawn.mission.status,
  result: atSpawn.mission.result,
  pending: atSpawn.mission.pending_question,
  tokens: atSpawn.usage.input + atSpawn.usage.output,
  known: atSpawn.usage.known,
  spend: costHudView(atSpawn.usage).spendLabel,
  replay: atSpawn.replay,
  view: replayView(log, 1, {mission}),
};

const atBudget = projectEvents(mission, log, 3);
cases.atBudget = {
  tokens: atBudget.usage.input + atBudget.usage.output,
  known: atBudget.usage.known,
  cost: atBudget.usage.cost,
  spend: costHudView(atBudget.usage).spendLabel,
  status: atBudget.mission.status,
  result: atBudget.mission.result,
  replay: atBudget.replay,
};

const atEnd = projectEvents(mission, log, 4);
cases.atEnd = {
  status: atEnd.mission.status,
  result: atEnd.mission.result,
  tokens: atEnd.usage.input + atEnd.usage.output,
  spend: costHudView(atEnd.usage).spendLabel,
  replay: atEnd.replay,
  view: replayView(log, 4, {mission}),
};

const invented = projectEvents(mission, log, 0);
cases.noInventedCrew = {
  agentIds: [...invented.agents.keys()],
  snapshot: missionSnapshot(mission),
};

const paused = projectEvents(mission, [
  event(1, "mission.started", {mode: "openai"}),
  event(2, "mission.paused", {reason: "user"}),
], 1);
cases.paused = {status: paused.mission.status, replay: paused.replay};

const asked = [
  event(1, "mission.started", {mode: "openai"}),
  event(2, "mission.question", {question_id: "q1", question: "Need a domain?"}),
  event(3, "user.answered", {question_id: "q1", answer: "example.com"}),
  event(4, "mission.running", {}),
];
cases.questionOpen = projectEvents(mission, asked, 1).mission.pending_question;
cases.questionClosed = projectEvents(mission, asked, 2).mission.pending_question;
cases.afterAnswer = projectEvents(mission, asked, 3).mission.status;

cases.step = {
  back: stepReplay(4, 5, -1),
  forward: stepReplay(0, 5, 1),
  clampLow: stepReplay(0, 5, -3),
  clampHigh: stepReplay(4, 5, 9),
  empty: stepReplay(0, 0, 1),
};
cases.live = {
  mid: isReplayLive(1, 5),
  end: isReplayLive(4, 5),
  empty: isReplayLive(-1, 0),
  clamp: clampReplayIndex(99, 5),
};
cases.previewView = replayView(log, 0, {preview: true, mission});
cases.elapsed = replayElapsedMs(mission, log[2]);
cases.unavailable = ESTIMATE_UNAVAILABLE;

const liveApply = newState(missionSnapshot(mission));
for (const e of log) applyEvent(liveApply, e);
cases.liveApplyMatches = liveApply.mission.status === atEnd.mission.status
  && liveApply.usage.cost === atEnd.usage.cost
  && liveApply.agents.size === atEnd.agents.size;

console.log(JSON.stringify(cases));
