import {
  recordedMissionStartedCountFeed, missionStartedCountView, MISSION_STARTED_COUNT_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, type, payload = {}) {
  return {id, event_type: type, payload, created_at: "2026-01-01T00:00:00Z"};
}

const started = (id, extra = {}) => event(id, "mission.started", {
  mode: "runtime", ...extra,
});
const log = [
  started("m1"),
  event("queued", "job.enqueued", {id: "j1", kind: "mission.agent_task", status: "pending", attempt: 0}),
  event("claimed", "lease.claimed", {lease_id: "c1", scope: "job"}),
  event("resumed", "mission.resumed", {mode: "runtime"}),
  event("running", "mission.running", {status: "running"}),
  event("resume-req", "mission.resume_requested"),
  event("paused", "mission.paused"),
  event("tool", "tool.started", {name: "echo", calls: 4}),
  event("tool-done", "tool.completed", {name: "echo"}),
  event("llm", "llm.started", {model: "x"}),
  event("verify", "verification.started"),
  event("task", "task.started", {id: "t1"}),
  started("m2"),
  event("mission-done", "mission.completed", {status: "completed"}),
  event("task-done", "task.completed", {id: "t1"}),
  event("failed", "mission.failed", {failure_class: "TOOL_MISSING"}),
  started("m3", {token_spent: 4}),
];

const cases = {};
cases.unavailable = MISSION_STARTED_COUNT_UNAVAILABLE;
cases.hidden = missionStartedCountView(log, {visible: false});
cases.hiddenDefault = missionStartedCountView(log);
cases.preview = missionStartedCountView(log, {visible: false});
cases.missingNull = missionStartedCountView(null, {visible: true});
cases.missingUndefined = missionStartedCountView(undefined, {visible: true});
cases.missingObject = missionStartedCountView({started: 4, events: []}, {visible: true});
cases.empty = missionStartedCountView([], {visible: true});
cases.counted = missionStartedCountView(log, {visible: true});
cases.ignoresResumed = missionStartedCountView([
  event("resumed", "mission.resumed", {started: 3}),
], {visible: true});
cases.ignoresRunning = missionStartedCountView([
  event("running", "mission.running", {started: 2}),
], {visible: true});
cases.ignoresResumeRequested = missionStartedCountView([
  event("resume-req", "mission.resume_requested", {started: 1}),
], {visible: true});
cases.ignoresPaused = missionStartedCountView([
  event("paused", "mission.paused", {started: 1}),
], {visible: true});
cases.ignoresTaskStarted = missionStartedCountView([
  event("task", "task.started", {started: 4}),
], {visible: true});
cases.ignoresLlmStarted = missionStartedCountView([
  event("llm", "llm.started", {started: 4}),
], {visible: true});
cases.ignoresToolStarted = missionStartedCountView([
  event("tool", "tool.started", {started: 6}),
], {visible: true});
cases.ignoresVerificationStarted = missionStartedCountView([
  event("verify", "verification.started", {started: 1}),
], {visible: true});
cases.ignoresCompleted = missionStartedCountView([
  event("mission-done", "mission.completed", {started: 1}),
], {visible: true});
cases.ignoresFailed = missionStartedCountView([
  event("mission-fail", "mission.failed", {started: 1, failure_class: "TOOL_MISSING"}),
], {visible: true});
cases.ignoresToolCompleted = missionStartedCountView([
  event("tool-done", "tool.completed", {started: 6}),
], {visible: true});
cases.ignoresBudget = missionStartedCountView([
  event("budget", "budget.updated", {known: true, token_spent: 9, started: 1}),
], {visible: true});
cases.oneStartedNotPayload = missionStartedCountView([
  started("big", {started: 5000, token_spent: 12}),
], {visible: true});
cases.skipsHoles = missionStartedCountView([null, {payload: {started: 10}}, started("one")], {visible: true});
cases.unreadableType = missionStartedCountView([
  started("ok"),
  {id: "bad", event_type: 4, payload: {started: 1}},
], {visible: true});
cases.missingType = missionStartedCountView([
  {id: "blank", payload: {started: 7}},
  started("one"),
], {visible: true});
cases.prefix = missionStartedCountView(recordedMissionStartedCountFeed(log, 7, true), {visible: true});
cases.prefixFirst = missionStartedCountView(recordedMissionStartedCountFeed(log, 0, true), {visible: true});
cases.prefixTwo = missionStartedCountView(recordedMissionStartedCountFeed(log, 12, true), {visible: true});
cases.prefixAll = missionStartedCountView(recordedMissionStartedCountFeed(log, log.length - 1, true), {visible: true});
cases.beforeAny = missionStartedCountView(recordedMissionStartedCountFeed(log, -1, true), {visible: true});
cases.unloaded = recordedMissionStartedCountFeed(log, log.length - 1, false);
cases.unloadedView = missionStartedCountView(recordedMissionStartedCountFeed([], 0, false), {visible: true});
cases.explicitEmptyFeed = recordedMissionStartedCountFeed([], -1, true);
cases.notArrayLog = recordedMissionStartedCountFeed({length: 0}, 0, true);

console.log(JSON.stringify(cases));
