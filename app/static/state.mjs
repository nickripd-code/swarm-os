export const terminal = new Set(["completed", "failed", "stopped", "blocked"]);
export function newState(mission = null) {
  return {mission, agents: new Map(), tasks: new Map(), seen: new Set(), events: [],
    usage: {input: 0, output: 0, reasoning: 0, cost: null, budget: null, known: false}, decisions: 0, preview: false};
}
export function applyEvent(state, e) {
  if (state.seen.has(e.id)) return false;
  state.seen.add(e.id);
  const p = e.payload || {};
  if (e.event_type === "agent.spawned" || e.event_type === "agent.updated") {
    state.agents.set(p.id, {...state.agents.get(p.id), ...p});
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
    state.usage.input += p.input_tokens || 0;
    state.usage.output += p.output_tokens || 0;
    state.usage.reasoning += p.reasoning_tokens || 0;
    const a = state.agents.get(e.actor_id);
    if (a) {a.tokens = (a.tokens || 0) + (p.input_tokens || 0) + (p.output_tokens || 0); a.model = p.model;}
  }
  if (e.event_type === "budget.updated") {
    if (typeof p.token_budget === "number") state.usage.budget = p.token_budget;
    if (p.known === true && typeof p.token_spent === "number") {
      state.usage.cost = p.token_spent;
      state.usage.known = true;
    }
  }
  if (e.event_type === "controller.decision") state.decisions++;
  if (e.event_type === "mission.started" && state.mission) {
    state.mission.status = "running"; state.mission.mode = p.mode;
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
        detail: p.token_budget != null
          ? "Estimated token spend " + (p.token_spent ?? "?") + " / " + p.token_budget + " USD"
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
