export const NO_MISSION = "No mission is loaded.";
export const UNAVAILABLE = "Event timeline unavailable.";
export const EMPTY = "No mission events yet.";
export const PENDING = "Recent events are not loaded yet.";

function panel(state, events, message) {
  return {state, events, message};
}

export function timelinePanel(input) {
  if (!input || input.preview || !input.missionId) {
    return panel("no_mission", [], NO_MISSION);
  }
  if (input.pending) return panel("pending", [], PENDING);
  if (input.ok === false || !input.body || typeof input.body !== "object") {
    return panel("unavailable", [], UNAVAILABLE);
  }
  const body = input.body;
  if (body.available === false || body.state === "no_mission") {
    return panel("no_mission", [], NO_MISSION);
  }
  if (!Array.isArray(body.events)) return panel("unavailable", [], UNAVAILABLE);
  const events = [];
  for (const event of body.events) {
    if (!event || typeof event.event_type !== "string" || !event.event_type.trim()) continue;
    const summary = typeof event.summary === "string" && event.summary.trim() ? event.summary.trim() : null;
    const created = typeof event.created_at === "string" && event.created_at ? event.created_at : null;
    events.push({event_type: event.event_type, created_at: created, summary});
  }
  if (!events.length) return panel("empty", [], EMPTY);
  return panel("ok", events, null);
}
