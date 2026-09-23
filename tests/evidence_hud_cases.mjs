import {
  newState, applyEvent, evidenceFromEvent, evidenceActivity, evidenceHudView, projectEvents,
} from "../app/static/state.mjs";

function event(id, type, payload) {
  return {id, event_type: type, actor_id: "verifier", payload, created_at: "2026-01-01T00:00:00Z"};
}

const cases = {};

const idle = newState();
cases.idle = evidenceHudView(idle);

const unknownType = newState();
applyEvent(unknownType, event("u1", "verification.evidence.skipped", {kind: "pytest", ok: true}));
applyEvent(unknownType, event("u2", "verification.passed", {verdict: "pass", rationale: "model said pass"}));
cases.unknownType = {
  view: evidenceHudView(unknownType),
  skipped: evidenceFromEvent(event("u1", "verification.evidence.skipped", {kind: "pytest", ok: true})),
  activity: evidenceActivity(event("u1", "verification.evidence.skipped", {kind: "pytest", ok: true})),
  verdictActivity: evidenceActivity(event("u2", "verification.passed", {verdict: "pass"})),
};

const started = newState();
applyEvent(started, event("s1", "verification.evidence.started", {
  count: 2, kinds: ["pytest", "browser", "http"],
}));
cases.started = {
  view: evidenceHudView(started),
  activity: evidenceActivity(started.events[0]),
  usage: started.usage,
};

const passed = newState();
applyEvent(passed, event("p0", "verification.evidence.started", {count: 1, kinds: ["pytest"]}));
applyEvent(passed, event("p1", "verification.evidence.passed", {
  kind: "pytest", ok: true, detail: "12 passed",
}));
cases.passed = {
  view: evidenceHudView(passed),
  activity: evidenceActivity(passed.events[0]),
  usage: passed.usage,
};

const failed = newState();
applyEvent(failed, event("f1", "verification.evidence.failed", {
  kind: "http",
  ok: false,
  detail: "GET https://example.test/health returned 503\nupstream down",
  failure_class: "VERIFICATION_FAILURE",
}));
cases.failed = {
  view: evidenceHudView(failed),
  activity: evidenceActivity(failed.events[0]),
};

const longDetail = "x".repeat(400);
const truncated = newState();
applyEvent(truncated, event("t1", "verification.evidence.failed", {
  kind: "file", ok: false, detail: longDetail, failure_class: "TIMEOUT",
}));
cases.truncated = evidenceHudView(truncated);

const badKind = newState();
applyEvent(badKind, event("b1", "verification.evidence.passed", {kind: "browser", ok: true, detail: "looks done"}));
applyEvent(badKind, event("b2", "verification.evidence.failed", {kind: "", ok: false, detail: "missing kind"}));
cases.badKind = {
  view: evidenceHudView(badKind),
  passActivity: evidenceActivity(event("b1", "verification.evidence.passed", {kind: "browser", ok: true})),
};

const disagree = newState();
applyEvent(disagree, event("d1", "verification.evidence.passed", {kind: "pytest", ok: false, detail: "actually failed"}));
applyEvent(disagree, event("d2", "verification.evidence.failed", {kind: "file", ok: true, detail: "hash mismatch"}));
cases.disagree = evidenceHudView(disagree);

const runtimeUnknown = newState();
applyEvent(runtimeUnknown, event("n1", "verification.evidence.failed", {
  kind: "unknown", ok: false, detail: "Evidence step is missing a supported kind (pytest, http, file)",
  failure_class: "VERIFICATION_FAILURE",
}));
cases.runtimeUnknown = evidenceHudView(runtimeUnknown);

const preview = newState();
applyEvent(preview, event("v1", "verification.evidence.passed", {kind: "pytest", ok: true}));
preview.preview = true;
cases.preview = evidenceHudView(preview);

const mission = {id: "m1", goal: "Ship", created_at: "2026-01-01T00:00:00Z", mode: "live", status: "running"};
const log = [
  event("r0", "verification.evidence.started", {count: 1, kinds: ["http"]}),
  event("r1", "verification.evidence.failed", {kind: "http", ok: false, detail: "non-2xx", failure_class: "VERIFICATION_FAILURE"}),
];
cases.replayEarly = evidenceHudView(projectEvents(mission, log, 0));
cases.replayLate = evidenceHudView(projectEvents(mission, log, 1));

console.log(JSON.stringify(cases));
