import {
  recordedTaskStoppedCountFeed, taskStoppedCountView, TASK_STOPPED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const stopped = (id, extra = {}) => event(id, "task.stopped", {id, status: "stopped", ...extra});
const log = [
  event("start", "mission.started", {mode: "runtime"}),
  event("spawn", "agent.spawned", {id: "a1", role: "researcher"}),
  stopped("t1"),
  event("done", "task.completed", {id: "t2", status: "completed"}),
  event("mission", "mission.stopped", {reason: "Execution stopped"}),
  event("started", "task.started", {id: "t5", status: "running"}),
  stopped("t3"),
  event("killed", "agent.killed", {id: "a1"}),
  event("budget", "budget.updated", {known: true, token_spent: 1}),
  event("updated", "agent.updated", {id: "a1", status: "stopped"}),
  event("failed", "task.failed", {id: "t6", status: "failed"}),
  stopped("t4", {stopped: 9, token_spent: 4}),
];

const cases = {};
cases.unavailable = TASK_STOPPED_COUNT_UNAVAILABLE;
cases.hidden = taskStoppedCountView(log, {visible: false});
cases.hiddenDefault = taskStoppedCountView(log);
cases.preview = taskStoppedCountView(log, {visible: false});
cases.missingNull = taskStoppedCountView(null, {visible: true});
cases.missingUndefined = taskStoppedCountView(undefined, {visible: true});
cases.missingObject = taskStoppedCountView({stopped: 4, events: []}, {visible: true});
cases.empty = taskStoppedCountView([], {visible: true});
cases.counted = taskStoppedCountView(log, {visible: true});
cases.ignoresMissionStopped = taskStoppedCountView([
  event("mission", "mission.stopped", {stopped: 3}),
], {visible: true});
cases.ignoresTaskStarted = taskStoppedCountView([
  event("started", "task.started", {status: "stopped", stopped: 1}),
], {visible: true});
cases.ignoresTaskCompleted = taskStoppedCountView([
  event("done", "task.completed", {status: "stopped", stopped: 2}),
], {visible: true});
cases.ignoresTaskFailed = taskStoppedCountView([
  event("failed", "task.failed", {status: "stopped", stopped: 2}),
], {visible: true});
cases.ignoresTaskPending = taskStoppedCountView([
  event("pending", "task.pending", {status: "stopped", stopped: 1}),
], {visible: true});
cases.ignoresAgentKilled = taskStoppedCountView([
  event("killed", "agent.killed", {stopped: 1}),
], {visible: true});
cases.ignoresAgentUpdated = taskStoppedCountView([
  event("updated", "agent.updated", {status: "stopped", stopped: 6}),
], {visible: true});
cases.ignoresPaused = taskStoppedCountView([
  event("paused", "mission.paused", {stopped: 1}),
], {visible: true});
cases.ignoresMissionFailed = taskStoppedCountView([
  event("failed-mission", "mission.failed", {stopped: 1}),
], {visible: true});
cases.ignoresBudget = taskStoppedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, stopped: 1}),
], {visible: true});
cases.oneStopNotPayload = taskStoppedCountView([
  stopped("big", {stopped: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = taskStoppedCountView([null, {payload: {stopped: 10}}, stopped("one")], {visible: true});
cases.unreadableType = taskStoppedCountView([
  stopped("ok"),
  {id: "bad", event_type: 4, payload: {stopped: 1}},
], {visible: true});
cases.missingType = taskStoppedCountView([
  {id: "blank", payload: {stopped: 7}},
  stopped("one"),
], {visible: true});
cases.prefix = taskStoppedCountView(recordedTaskStoppedCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = taskStoppedCountView(recordedTaskStoppedCountFeed(log, 0, true), {visible: true});
cases.prefixOne = taskStoppedCountView(recordedTaskStoppedCountFeed(log, 6, true), {visible: true});
cases.prefixAll = taskStoppedCountView(recordedTaskStoppedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = taskStoppedCountView(recordedTaskStoppedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedTaskStoppedCountFeed(log, log.length - 1, false);
cases.unloadedView = taskStoppedCountView(recordedTaskStoppedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedTaskStoppedCountFeed([], -1, true);
cases.notArrayLog = recordedTaskStoppedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
