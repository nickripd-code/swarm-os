import {
  newState, applyEvent, pendingQuestionView, projectEvents, QUESTION_SUMMARY_CAP,
} from "../app/static/state.mjs";

const GOAL = "DO_NOT_USE_GOAL_AS_PROMPT";
const REASON = "DO_NOT_USE_REASON_AS_PROMPT";
const ANSWER = "DO_NOT_SHOW_THIS_ANSWER";
const MESSAGE = "DO_NOT_USE_AGENT_MESSAGE_AS_PROMPT";

function event(id, type, payload, actor = "root") {
  return {id, event_type: type, actor_id: actor, payload, created_at: "2026-01-01T00:00:0" + String(id).slice(-1) + "Z"};
}

function viewOf(state) {
  return pendingQuestionView(state);
}

const mission = {id: "m1", goal: GOAL, status: "running", created_at: "2026-01-01T00:00:00Z"};
const cases = {cap: QUESTION_SUMMARY_CAP};

cases.idle = viewOf(newState(null));
cases.loaded = viewOf(newState({
  id: "m1",
  goal: GOAL,
  status: "waiting",
  pending_question: {question_id: "q-loaded", question: "Which name?", reason: REASON, answer: ANSWER},
}));
cases.staleRunning = viewOf(newState({
  id: "m1",
  goal: GOAL,
  status: "running",
  pending_question: {question_id: "q-stale", question: "Still there?"},
}));
cases.waitingWithoutQuestion = viewOf(newState({id: "m1", goal: GOAL, status: "waiting", pending_question: null}));

const taskLog = [
  event(1, "mission.started", {mode: "openai"}),
  event(2, "mission.waiting", {reason: "Waiting for in-flight work", pending_tasks: ["t1"]}),
];
cases.taskWait = viewOf(projectEvents(mission, taskLog, 1));

const asked = [
  event(1, "mission.started", {mode: "openai"}),
  event(2, "mission.question", {
    question_id: "q1",
    question: "Need a domain?",
    reason: REASON,
    answer: ANSWER,
  }),
];
cases.question = viewOf(projectEvents(mission, asked, 1));
cases.questionThenHumanWait = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-both", question: "Need a domain?", reason: REASON}),
  event(2, "mission.waiting", {question_id: "q-both", question: "Need a domain?", reason: REASON}),
], 1));

const waitingOnly = [
  event(1, "mission.started", {mode: "openai"}),
  event(2, "mission.waiting", {
    question_id: "q-wait",
    question: "Approve this step?",
    reason: REASON,
    kind: "approval",
    approval_action: "finish",
  }),
];
cases.waitingOnly = viewOf(projectEvents(mission, waitingOnly, 1));

cases.idOnly = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-bare", reason: REASON}),
], 0));
cases.blankPrompt = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-blank", question: "   \n  "}),
], 0));
cases.badId = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "not an id", question: "Need a name?"}),
], 0));

const answered = [
  ...asked,
  event(3, "user.answered", {question_id: "q1", answer: ANSWER}),
  event(4, "mission.running", {}),
];
cases.answered = viewOf(projectEvents(mission, answered, 3));

const replaced = [
  event(1, "mission.question", {question_id: "q-old", question: "First prompt?"}),
  event(2, "user.answered", {question_id: "q-old", answer: ANSWER}),
  event(3, "mission.running", {}),
  event(4, "mission.question", {question_id: "q-new", question: "Second prompt?"}),
];
cases.replaced = viewOf(projectEvents(mission, replaced, 3));

const long = "A".repeat(200) + " " + REASON;
cases.longSummary = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-long", question: "Line one\n\n" + long}),
], 0));

const preview = newState({
  id: "preview",
  goal: GOAL,
  status: "waiting",
  pending_question: {question_id: "q-preview", question: "Fake preview question?"},
});
preview.preview = true;
cases.preview = viewOf(preview);

cases.paused = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-pause", question: "Hold this?"}),
  event(2, "mission.paused", {reason: "user"}),
], 1));

cases.stopped = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-stop", question: "Stop this?"}),
  event(2, "mission.stopped", {reason: "stop"}),
], 1));

const replayLog = [
  event(1, "mission.started", {mode: "openai"}),
  event(2, "mission.question", {question_id: "q-replay", question: "Before the answer?"}),
  event(3, "user.answered", {question_id: "q-replay", answer: ANSWER}),
];
cases.replayBefore = viewOf(projectEvents(mission, replayLog, 0));
cases.replayOpen = viewOf(projectEvents(mission, replayLog, 1));
cases.replayAfter = viewOf(projectEvents(mission, replayLog, 2));

cases.staleThenTaskWait = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-stale-wait", question: "Should not linger?"}),
  event(2, "user.answered", {question_id: "q-stale-wait", answer: ANSWER}),
  event(3, "mission.running", {}),
  event(4, "mission.waiting", {reason: "Waiting for in-flight work", pending_tasks: ["t9"]}),
], 3));

cases.clearedByTaskWait = viewOf(projectEvents(mission, [
  event(1, "mission.question", {question_id: "q-clear", question: "Should clear?"}),
  event(2, "mission.waiting", {reason: "Waiting for in-flight work", pending_tasks: ["t2"]}),
], 1));

const messageState = newState(mission);
applyEvent(messageState, event(1, "mission.started", {mode: "openai"}));
applyEvent(messageState, event(2, "agent.message", {kind: "question", text: MESSAGE, from_id: "a", to_id: "b"}));
cases.agentMessage = viewOf(messageState);

const duplicateState = newState(missionSnapshotSafe());
applyEvent(duplicateState, event(1, "mission.question", {question_id: "q-dup", question: "Kept?"}));
applyEvent(duplicateState, event(1, "mission.question", {question_id: "q-dup", question: "Replaced?"}));
cases.duplicate = viewOf(duplicateState);

function missionSnapshotSafe() {
  return {id: "m1", goal: GOAL, status: "pending", created_at: "2026-01-01T00:00:00Z"};
}

cases.markers = {goal: GOAL, reason: REASON, answer: ANSWER, message: MESSAGE};

console.log(JSON.stringify(cases));
