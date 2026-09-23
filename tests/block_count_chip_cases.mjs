import {
  recordedBlockCountFeed, blockCountView, BLOCK_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const block = (id, extra = {}) => event(id, "mission.blocked", {reason: "Required capability is unavailable", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  block("b1"),
  event("ask", "mission.question", {question_id: "q1", question: "Need a domain?"}),
  event("running", "mission.running", {reason: "continuing"}),
  block("b2"),
  event("paused", "mission.paused", {reason: "user"}),
  event("waiting", "mission.waiting", {reason: "Waiting for in-flight work"}),
  event("task", "task.blocked", {reason: "missing tool"}),
  event("agent", "agent.updated", {status: "blocked"}),
  event("budget", "budget.updated", {known: true, token_spent: 1.25}),
  block("b3", {blocks: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = BLOCK_COUNT_UNAVAILABLE;
cases.hidden = blockCountView(log, {visible: false});
cases.hiddenDefault = blockCountView(log);
cases.preview = blockCountView(log, {visible: false});
cases.missingNull = blockCountView(null, {visible: true});
cases.missingUndefined = blockCountView(undefined, {visible: true});
cases.missingObject = blockCountView({blocks: 4, events: []}, {visible: true});
cases.empty = blockCountView([], {visible: true});
cases.counted = blockCountView(log, {visible: true});
cases.ignoresRunning = blockCountView([
  event("running", "mission.running", {blocks: 2}),
], {visible: true});
cases.ignoresQuestion = blockCountView([
  event("ask", "mission.question", {blocks: 3}),
], {visible: true});
cases.ignoresPaused = blockCountView([
  event("paused", "mission.paused", {blocks: 1}),
], {visible: true});
cases.ignoresWaiting = blockCountView([
  event("waiting", "mission.waiting", {blocks: 2}),
], {visible: true});
cases.ignoresStopped = blockCountView([
  event("stopped", "mission.stopped", {blocks: 2}),
], {visible: true});
cases.ignoresFailed = blockCountView([
  event("failed", "mission.failed", {blocks: 2}),
], {visible: true});
cases.ignoresTaskBlocked = blockCountView([
  event("task", "task.blocked", {blocks: 4}),
], {visible: true});
cases.ignoresAgentBlocked = blockCountView([
  event("agent", "agent.updated", {status: "blocked", blocks: 5}),
], {visible: true});
cases.ignoresStarted = blockCountView([
  event("start", "mission.started", {blocks: 6}),
], {visible: true});
cases.ignoresBudget = blockCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, blocks: 1}),
], {visible: true});
cases.oneBlockNotPayload = blockCountView([
  block("big", {blocks: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = blockCountView([null, {payload: {blocks: 10}}, block("one")], {visible: true});
cases.unreadableType = blockCountView([
  block("ok"),
  {id: "bad", event_type: 4, payload: {blocks: 1}},
], {visible: true});
cases.missingType = blockCountView([
  {id: "blank", payload: {blocks: 7}},
  block("one"),
], {visible: true});
cases.prefix = blockCountView(recordedBlockCountFeed(log, 1, true), {visible: true});
cases.prefixFirst = blockCountView(recordedBlockCountFeed(log, 0, true), {visible: true});
cases.prefixOne = blockCountView(recordedBlockCountFeed(log, 4, true), {visible: true});
cases.prefixAll = blockCountView(recordedBlockCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = blockCountView(recordedBlockCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedBlockCountFeed(log, log.length - 1, false);
cases.unloadedView = blockCountView(recordedBlockCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedBlockCountFeed([], -1, true);
cases.notArrayLog = recordedBlockCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
