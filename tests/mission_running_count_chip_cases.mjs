import {
  recordedMissionRunningCountFeed, missionRunningCountView, MISSION_RUNNING_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const running = (id, extra = {}) => event(id, "mission.running", {
  reason: "In-flight work finished; controller will continue", ...extra,
});
const log = [
  event("started", "mission.started", {mode: "runtime"}),
  event("waiting", "mission.waiting", {reason: "Waiting for in-flight work"}),
  running("r1"),
  event("resumed", "mission.resumed", {mode: "runtime"}),
  event("resume-req", "mission.resume_requested"),
  event("paused", "mission.paused"),
  event("task", "task.started", {id: "t1"}),
  event("llm", "llm.started", {model: "x"}),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  event("verify", "verification.started"),
  running("r2"),
  event("mission-done", "mission.completed", {status: "completed"}),
  event("task-done", "task.completed", {id: "t1"}),
  event("failed", "mission.failed", {failure_class: "TOOL_MISSING"}),
  running("r3", {token_spent: 4}),
];

const cases = {};
cases.unavailable = MISSION_RUNNING_COUNT_UNAVAILABLE;
cases.hidden = missionRunningCountView(log, {visible: false});
cases.hiddenDefault = missionRunningCountView(log);
cases.preview = missionRunningCountView(log, {visible: false});
cases.missingNull = missionRunningCountView(null, {visible: true});
cases.missingUndefined = missionRunningCountView(undefined, {visible: true});
cases.missingObject = missionRunningCountView({running: 4, events: []}, {visible: true});
cases.empty = missionRunningCountView([], {visible: true});
cases.counted = missionRunningCountView(log, {visible: true});
cases.ignoresStarted = missionRunningCountView([
  event("started", "mission.started", {running: 3, status: "running"}),
], {visible: true});
cases.ignoresResumed = missionRunningCountView([
  event("resumed", "mission.resumed", {running: 3}),
], {visible: true});
cases.ignoresResumeRequested = missionRunningCountView([
  event("resume-req", "mission.resume_requested", {running: 1}),
], {visible: true});
cases.ignoresWaiting = missionRunningCountView([
  event("waiting", "mission.waiting", {running: 2}),
], {visible: true});
cases.ignoresPaused = missionRunningCountView([
  event("paused", "mission.paused", {running: 1}),
], {visible: true});
cases.ignoresTaskStarted = missionRunningCountView([
  event("task", "task.started", {running: 4, status: "running"}),
], {visible: true});
cases.ignoresLlmStarted = missionRunningCountView([
  event("llm", "llm.started", {running: 4}),
], {visible: true});
cases.ignoresToolStarted = missionRunningCountView([
  event("tool", "tool.started", {running: 6}),
], {visible: true});
cases.ignoresVerificationStarted = missionRunningCountView([
  event("verify", "verification.started", {running: 1}),
], {visible: true});
cases.ignoresCompleted = missionRunningCountView([
  event("mission-done", "mission.completed", {running: 1}),
], {visible: true});
cases.ignoresFailed = missionRunningCountView([
  event("mission-fail", "mission.failed", {running: 1, failure_class: "TOOL_MISSING"}),
], {visible: true});
cases.ignoresToolCompleted = missionRunningCountView([
  event("tool-done", "tool.completed", {running: 6}),
], {visible: true});
cases.ignoresBudget = missionRunningCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, running: 1}),
], {visible: true});
cases.oneRunningNotPayload = missionRunningCountView([
  running("big", {running: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = missionRunningCountView([null, {payload: {running: 10}}, running("one")], {visible: true});
cases.unreadableType = missionRunningCountView([
  running("ok"),
  {id: "bad", event_type: 4, payload: {running: 1}},
], {visible: true});
cases.missingType = missionRunningCountView([
  {id: "blank", payload: {running: 7}},
  running("one"),
], {visible: true});
cases.prefix = missionRunningCountView(recordedMissionRunningCountFeed(log, 2, true), {visible: true});
cases.prefixFirst = missionRunningCountView(recordedMissionRunningCountFeed(log, 0, true), {visible: true});
cases.prefixTwo = missionRunningCountView(recordedMissionRunningCountFeed(log, 10, true), {visible: true});
cases.prefixAll = missionRunningCountView(recordedMissionRunningCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = missionRunningCountView(recordedMissionRunningCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedMissionRunningCountFeed(log, log.length - 1, false);
cases.unloadedView = missionRunningCountView(recordedMissionRunningCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedMissionRunningCountFeed([], -1, true);
cases.notArrayLog = recordedMissionRunningCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
