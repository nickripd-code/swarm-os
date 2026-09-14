export const terminal = new Set(["completed", "failed", "stopped", "blocked"]);
export const ESTIMATE_UNAVAILABLE = "estimate unavailable";
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
