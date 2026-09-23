export const terminal = new Set(["completed", "failed", "stopped", "blocked"]);
export const ESTIMATE_UNAVAILABLE = "estimate unavailable";
export const KILL_ROUTE_PATTERN = /\/api\/missions\/\{[^}]+\}\/agents\/\{[^}]+\}\/kill$/;
export function killRoutePresent(spec) {
  if (!spec || typeof spec !== "object") return false;
  const paths = spec.paths || {};
  return Object.keys(paths).some((path) => {
    if (!KILL_ROUTE_PATTERN.test(path)) return false;
    const item = paths[path];
    return !!(item && (item.post || item.POST));
  });
}
export function parseCommand(raw) {
  const text = String(raw ?? "").trim();
  if (!text) return {ok: false, error: "Command is empty"};
  const stripped = text.replace(/^\/+/, "").trim();
  const tokens = stripped.split(/\s+/).filter(Boolean);
  if (!tokens.length) return {ok: false, error: "Command is empty"};
  const verb = tokens[0].toLowerCase();
  const rest = stripped.slice(tokens[0].length).trim();
  if (verb === "stop" && tokens.length === 1) return {ok: true, action: "stop"};
  if (
    (verb === "stop-all" || verb === "stopall") && tokens.length === 1
    || (verb === "stop" && tokens[1]?.toLowerCase() === "all" && tokens.length === 2)
  ) {
    return {ok: true, action: "stop-all"};
  }
  if (verb === "kill") {
    if (tokens.length > 2) return {ok: false, error: "kill takes at most one agent id"};
    return {ok: true, action: "kill", agentId: rest || null};
  }
  if (verb === "answer") {
    if (!rest) return {ok: false, error: "answer requires text"};
    return {ok: true, action: "answer", text: rest};
  }
  return {ok: false, error: "Unknown command: " + tokens[0]};
}
export function resolveCommand(parsed, context = {}) {
  if (!parsed?.ok) {
    return parsed?.error ? parsed : {ok: false, error: "Unknown command"};
  }
  const preview = context.preview === true;
  const missionId = preview ? null : (context.missionId || null);
  if (parsed.action === "stop") {
    if (!missionId) return {ok: false, error: "No live mission to stop"};
    return {ok: true, action: "stop", method: "POST", path: "/api/missions/" + missionId + "/stop"};
  }
  if (parsed.action === "stop-all") {
    return {ok: true, action: "stop-all", method: "POST", path: "/api/stop-all"};
  }
  if (parsed.action === "kill") {
    const agentId = parsed.agentId || context.selectedAgentId || null;
    if (!agentId) return {ok: false, error: "kill requires an agent id"};
    if (context.killAvailable !== true) return {ok: false, error: "Kill agent is not available"};
    if (!missionId) return {ok: false, error: "No live mission for kill"};
    return {
      ok: true,
      action: "kill",
      method: "POST",
      path: "/api/missions/" + missionId + "/agents/" + encodeURIComponent(agentId) + "/kill",
      agentId,
    };
  }
  if (parsed.action === "answer") {
    if (!missionId) return {ok: false, error: "No live mission to answer"};
    const questionId = context.pendingQuestionId || null;
    if (!questionId) return {ok: false, error: "No open question to answer"};
    return {
      ok: true,
      action: "answer",
      method: "POST",
      path: "/api/missions/" + missionId + "/answers/" + encodeURIComponent(questionId),
      body: {answer: parsed.text},
    };
  }
  return {ok: false, error: "Unknown command"};
}
export function newState(mission = null) {
  return {mission, agents: new Map(), tasks: new Map(), seen: new Set(), events: [],
    usage: {input: 0, output: 0, reasoning: 0, cost: null, budget: null, known: false}, decisions: 0, preview: false};
}
function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
function nonNegativeInt(value) {
  const n = finiteNumber(value);
  if (n === null || n < 0) return 0;
  return Math.trunc(n);
}
export function formatUsd(value) {
  const n = finiteNumber(value);
  if (n === null) return null;
  if (n === 0) return "$0";
  if (n < 0.01) return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}
export function tokenTotal(usage) {
  return (usage?.input || 0) + (usage?.output || 0) + (usage?.reasoning || 0);
}
export function costHudView(usage = {}) {
  const input = usage.input || 0;
  const output = usage.output || 0;
  const reasoning = usage.reasoning || 0;
  const tokens = input + output + reasoning;
  const known = usage.known === true && finiteNumber(usage.cost) !== null && usage.cost >= 0;
  const budget = finiteNumber(usage.budget);
  const budgetKnown = budget !== null && budget >= 0;
  const spendLabel = known ? formatUsd(usage.cost) : ESTIMATE_UNAVAILABLE;
  const budgetLabel = budgetKnown ? formatUsd(budget) : ESTIMATE_UNAVAILABLE;
  const remainingLabel = known && budgetKnown ? formatUsd(budget - usage.cost) : null;
  let tokensLabel = tokens.toLocaleString();
  if (reasoning > 0) {
    tokensLabel += " · in " + input.toLocaleString() + " / out " + output.toLocaleString()
      + " / reason " + reasoning.toLocaleString();
  } else if (tokens > 0) {
    tokensLabel += " · in " + input.toLocaleString() + " / out " + output.toLocaleString();
  }
  return {
    known,
    tokens,
    input,
    output,
    reasoning,
    tokensLabel,
    spendLabel,
    budgetLabel,
    remainingLabel,
    note: known ? "Conservative estimate · not an invoice" : ESTIMATE_UNAVAILABLE,
  };
}
export function applyEvent(state, e) {
  if (state.seen.has(e.id)) return false;
  state.seen.add(e.id);
  const p = e.payload || {};
    if (e.event_type === "agent.spawned" || e.event_type === "agent.updated") {
    state.agents.set(p.id, {...state.agents.get(p.id), ...p});
  }
  if (e.event_type === "agent.killed") {
    const id = p.id || p.agent_id;
    if (id) {
      state.agents.set(id, {...state.agents.get(id), ...p, id, status: p.status || "stopped"});
    }
  }
  if (e.event_type.startsWith("task.")) {
    const id = p.id || p.task_id;
    if (id) {
      const status = e.event_type === "task.started" ? "running" : e.event_type.split(".")[1];
      const task = {...state.tasks.get(id), ...p, id, status};
      state.tasks.set(id, task);
      const agent = state.agents.get(task.agent_id || e.actor_id);
      if (agent) {agent.status = status; agent.output = task.output || agent.output;}
    }
  }
  if (e.event_type === "llm.started") {
    const a = state.agents.get(e.actor_id);
    if (a) a.activity = p.kind === "decision" ? "Deciding the next move" : p.kind === "verification" ? "Verifying the claimed result" : "Working on the task";
  }
  if (e.event_type === "llm.completed") {
    const input = nonNegativeInt(p.input_tokens);
    const output = nonNegativeInt(p.output_tokens);
    const reasoning = nonNegativeInt(p.reasoning_tokens);
    state.usage.input += input;
    state.usage.output += output;
    state.usage.reasoning += reasoning;
    const a = state.agents.get(e.actor_id);
    if (a) {a.tokens = (a.tokens || 0) + input + output + reasoning; a.model = p.model;}
  }
  if (e.event_type === "budget.updated") {
    const budget = finiteNumber(p.token_budget);
    if (budget !== null && budget >= 0) state.usage.budget = budget;
    const spent = finiteNumber(p.token_spent);
    // Dollars only when ResourceScheduler marks the estimate known. Never treat
    // missing/false known or a default 0 as spend.
    if (p.known === true && spent !== null && spent >= 0) {
      state.usage.cost = spent;
      state.usage.known = true;
    }
  }
  if (e.event_type === "controller.decision") state.decisions++;
  if (e.event_type === "mission.started" && state.mission) {
    state.mission.status = "running"; state.mission.mode = p.mode;
  }
  if (e.event_type === "mission.waiting" && state.mission) {
    state.mission.status = "waiting";
  }
  if (e.event_type === "mission.running" && state.mission) {
    state.mission.status = "running";
  }
  if (e.event_type === "mission.paused" && state.mission) {
    state.mission.status = "paused";
  }
  if (e.event_type === "mission.resumed" && state.mission) {
    state.mission.status = "running";
  }
  if (e.event_type === "mission.question" && state.mission) {
    state.mission.pending_question = p;
    state.mission.status = "waiting";
  }
  if (e.event_type === "user.answered" && state.mission) {
    const open = state.mission.pending_question;
    if (!open || !p.question_id || open.question_id === p.question_id) {
      state.mission.pending_question = null;
    }
  }
  if (e.event_type.startsWith("mission.") && terminal.has(e.event_type.split(".")[1]) && state.mission) {
    state.mission.status = e.event_type.split(".")[1];
    state.mission.result = p;
    for (const a of state.agents.values()) {
      if (["created","running"].includes(a.status)) {
        a.status = state.mission.status;
      }
    }
  }
  state.events.unshift(e);
  if (state.events.length > 120) state.events.length = 120;
  return true;
}
export function missionMode(state) {
  if (state.preview) return "preview";
  return state.mission?.mode || state.mission?.result?.mode || (state.mission ? "pending" : "standby");
}
export function resultMetaText(mission) {
  const result = mission?.result;
  if (!result) return "";
  const bits = [];
  if (mission.status) bits.push(String(mission.status).toUpperCase());
  if (result.mode) bits.push("mode " + result.mode);
  if (result.failure_class) bits.push(result.failure_class);
  return bits.join(" · ");
}
export function alertFromEvent(e) {
  const p = e.payload || {};
  switch (e.event_type) {
    case "mission.failed":
      return {
        level: "critical",
        title: "Mission failed",
        detail: p.error || p.failure_class || "",
        failure_class: p.failure_class || null,
        event_type: e.event_type,
      };
    case "mission.completed":
      return {
        level: "success",
        title: "Mission complete",
        detail: p.summary ? String(p.summary).slice(0, 180) : "Result ready",
        event_type: e.event_type,
      };
    case "mission.blocked":
      return {
        level: "warning",
        title: "Mission blocked",
        detail: p.reason || p.error || "Required capability or information is unavailable",
        event_type: e.event_type,
      };
    case "task.blocked":
      return {
        level: "warning",
        title: "Task blocked",
        detail: p.output?.finding || p.reason || p.description || "A task needs a missing capability",
        event_type: e.event_type,
      };
    case "mission.stopped":
      return {
        level: "warning",
        title: "Execution stopped",
        detail: p.reason || "All execution stopped",
        event_type: e.event_type,
      };
    case "verification.failed":
      return {
        level: "critical",
        title: "Verification failed",
        detail: p.rationale || p.failure_class || "Claimed result was not accepted",
        failure_class: p.failure_class || "VERIFICATION_FAILURE",
        event_type: e.event_type,
      };
    case "budget.warning":
      return {
        level: "warning",
        title: "Budget warning",
        detail: typeof p.token_spent === "number" && typeof p.token_budget === "number"
          ? "Estimated token spend " + p.token_spent + " / " + p.token_budget + " USD"
          : "Estimated token spend is approaching the mission budget",
        event_type: e.event_type,
      };
    default:
      return null;
  }
}
export function layoutTree(agents, minimumWidth = 700) {
  const list = [...agents.values()];
  const children = new Map();
  const roots = [];
  for (const a of list) {
    if (!a.parent_id || !agents.has(a.parent_id) || a.parent_id === a.id) roots.push(a);
    else {
      if (!children.has(a.parent_id)) children.set(a.parent_id, []);
      children.get(a.parent_id).push(a);
    }
  }
  const spans = new Map();
  const visited = new Set();
  function measure(a, trail = new Set()) {
    if (trail.has(a.id)) return 250;
    const next = new Set(trail); next.add(a.id);
    const span = Math.max(250, (children.get(a.id) || []).reduce((sum,c) => sum + measure(c,next), 0));
    spans.set(a.id,span); return span;
  }
  for (const root of roots) measure(root);
  const total = roots.reduce((sum,a) => sum + spans.get(a.id),0);
  const width = Math.max(minimumWidth,total+100);
  const positions = new Map();
  function place(a, left, depth) {
    if (visited.has(a.id)) return;
    visited.add(a.id);
    positions.set(a.id,{x:left+spans.get(a.id)/2-105,y:90+depth*230,depth});
    let childLeft=left;
    for(const c of children.get(a.id)||[]) {place(c,childLeft,depth+1);childLeft+=spans.get(c.id)||250;}
  }
  let left=(width-total)/2;
  for(const root of roots){place(root,left,0);left+=spans.get(root.id);}
  // Preserve inspectability if a malformed historic graph contains a cycle.
  for(const a of list) if(!visited.has(a.id)) {spans.set(a.id,250);place(a,50,0);}
  const depth=Math.max(0,...[...positions.values()].map(p=>p.depth));
  return {positions,width,height:Math.max(420,depth*230+320)};
}
export function recordEvent(log, e) {
  if (!Array.isArray(log) || !e || e.id == null || e.id === "") return false;
  for (const item of log) if (item.id === e.id) return false;
  log.push(e);
  return true;
}
export function clampReplayIndex(index, length) {
  if (!length || length < 1) return -1;
  if (index === -1) return -1;
  if (typeof index !== "number" || !Number.isFinite(index)) return length - 1;
  return Math.max(0, Math.min(length - 1, Math.trunc(index)));
}
export function stepReplay(index, length, delta) {
  const amount = typeof delta === "number" && Number.isFinite(delta) ? Math.trunc(delta) : 0;
  const cur = clampReplayIndex(index, length);
  if (cur < 0) return -1;
  return clampReplayIndex(cur + amount, length);
}
export function isReplayLive(index, length) {
  if (!length || length < 1) return true;
  return clampReplayIndex(index, length) === length - 1;
}
export function missionSnapshot(mission) {
  if (!mission) return null;
  return {
    id: mission.id,
    goal: mission.goal,
    created_at: mission.created_at,
    mode: mission.mode,
    budget: mission.budget,
    status: "pending",
    result: null,
    pending_question: null,
  };
}
export function projectEvents(mission, log, throughIndex) {
  const events = Array.isArray(log) ? log : [];
  const cursor = throughIndex == null
    ? (events.length ? events.length - 1 : -1)
    : clampReplayIndex(throughIndex, events.length);
  const state = newState(missionSnapshot(mission));
  state.replay = cursor >= 0 && cursor < events.length - 1;
  if (cursor < 0) return state;
  for (let i = 0; i <= cursor; i++) applyEvent(state, events[i]);
  state.replay = cursor < events.length - 1;
  return state;
}
export function replayElapsedMs(mission, event) {
  const start = mission?.created_at ? Date.parse(mission.created_at) : NaN;
  const at = event?.created_at ? Date.parse(event.created_at) : start;
  if (!Number.isFinite(start) || !Number.isFinite(at)) return null;
  return Math.max(0, at - start);
}
export function replayView(log, index, options = {}) {
  const events = Array.isArray(log) ? log : [];
  const preview = options.preview === true;
  const cursor = clampReplayIndex(index, events.length);
  const live = !preview && isReplayLive(cursor, events.length);
  const event = cursor >= 0 ? events[cursor] : null;
  const playing = options.playing === true && !live && !preview && events.length > 0;
  return {
    total: events.length,
    cursor,
    live,
    preview,
    playing,
    disabled: preview || events.length < 1,
    label: preview ? "PREVIEW" : (live ? "LIVE" : "REPLAY"),
    positionLabel: events.length < 1 ? "0 / 0" : (cursor + 1) + " / " + events.length,
    eventType: event?.event_type || "",
    createdAt: event?.created_at || null,
    elapsedMs: replayElapsedMs(options.mission, event),
    caption: preview
      ? "Preview is synthetic · not historical replay"
      : (events.length < 1
        ? "No recorded events yet"
        : "Recorded events only · not a simulation"),
  };
}

export const LAST_PAUSE_UNAVAILABLE = "LAST PAUSE unavailable";
export const LAST_PAUSE_NONE = "LAST PAUSE none";
const PAUSE_AT_STAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/;

function hiddenLastPause() {
  return {hidden: true, label: "", known: false, at: null, title: ""};
}
function unavailableLastPause() {
  return {hidden: false, label: LAST_PAUSE_UNAVAILABLE, known: false, at: null, title: ""};
}
function noneLastPause() {
  return {hidden: false, label: LAST_PAUSE_NONE, known: true, at: null, title: ""};
}

/** UTC clock from a recorded event stamp. Epoch and naive times are rejected. */
function parsePauseAt(raw) {
  if (typeof raw !== "string" || raw === "" || raw !== raw.trim()) return null;
  const match = PAUSE_AT_STAMP.exec(raw);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const fraction = match[7] ? Number(match[7].padEnd(3, "0").slice(0, 3)) : 0;
  if (month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return null;
  let offsetMinutes = 0;
  if (match[8] !== "Z") {
    const sign = match[8][0] === "-" ? -1 : 1;
    const offsetHour = Number(match[8].slice(1, 3));
    const offsetMinute = Number(match[8].slice(4, 6));
    if (offsetHour > 23 || offsetMinute > 59) return null;
    offsetMinutes = sign * (offsetHour * 60 + offsetMinute);
  }
  const utc = Date.UTC(year, month - 1, day, hour, minute, second, fraction) - offsetMinutes * 60000;
  if (!Number.isFinite(utc) || utc <= 0) return null;
  const wall = new Date(utc + offsetMinutes * 60000);
  if (
    wall.getUTCFullYear() !== year ||
    wall.getUTCMonth() !== month - 1 ||
    wall.getUTCDate() !== day ||
    wall.getUTCHours() !== hour ||
    wall.getUTCMinutes() !== minute ||
    wall.getUTCSeconds() !== second
  ) return null;
  const shown = new Date(utc);
  const hh = String(shown.getUTCHours()).padStart(2, "0");
  const mm = String(shown.getUTCMinutes()).padStart(2, "0");
  const ss = String(shown.getUTCSeconds()).padStart(2, "0");
  return {label: hh + ":" + mm + ":" + ss + "Z", stamp: raw, at: utc};
}

/** Prefix of a loaded event log. A missing feed stays null — never an invented []. */
export function recordedPauseAtFeed(log, cursor, loaded) {
  if (loaded !== true || !Array.isArray(log)) return null;
  if (log.length === 0) return [];
  const index = typeof cursor === "number" && Number.isFinite(cursor) ? Math.trunc(cursor) : -1;
  if (index < 0) return [];
  return log.slice(0, Math.min(log.length, index + 1));
}

/**
 * Read-only UTC time of the newest recorded mission.paused event on the loaded
 * shell log. The shell pause-state path is exactly mission.paused (applyEvent).
 * Resume, suspend, waiting, and agent status updates are ignored unless the
 * type is exactly mission.paused. Hidden with no mission or in preview.
 * A missing feed is LAST PAUSE unavailable. A loaded feed with no pause event
 * yet (including a cursor before any event) is LAST PAUSE none. The newest valid
 * event time wins. The log-order last pause event must itself have a valid stamp.
 */
export function lastPauseAtView(feed, options = {}) {
  if (options.visible !== true) return hiddenLastPause();
  if (!Array.isArray(feed)) return unavailableLastPause();
  let lastParsed = null;
  let sawPause = false;
  let best = null;
  for (const event of feed) {
    if (!event || typeof event !== "object" || event.event_type !== "mission.paused") continue;
    sawPause = true;
    const parsed = parsePauseAt(event.created_at);
    lastParsed = parsed;
    if (parsed && (!best || parsed.at >= best.at)) best = parsed;
  }
  if (!sawPause) return noneLastPause();
  if (!lastParsed || !best) return unavailableLastPause();
  return {
    hidden: false,
    label: "LAST PAUSE " + best.label,
    known: true,
    at: best.stamp,
    title: best.stamp,
  };
}
