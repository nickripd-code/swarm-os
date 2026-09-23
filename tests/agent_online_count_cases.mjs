import {agentOnlineCountView, AGENT_ONLINE_UNAVAILABLE} from "../app/static/state.mjs";

const mission = {id: "m1", goal: "ship", status: "running"};
const agent = (id, status) => ({id, status});

const cases = {
  noMission: agentOnlineCountView({roster: [agent("a", "running")]}),
  preview: agentOnlineCountView({
    mission, preview: true, roster: [agent("a", "running"), agent("b", "running")],
  }),
  rosterMissing: agentOnlineCountView({mission}),
  rosterNull: agentOnlineCountView({mission, roster: null}),
  rosterNotList: agentOnlineCountView({mission, roster: {id: "m1", agent_count: 2}}),
  explicitZeroIsNotOnline: agentOnlineCountView({mission, roster: {agent_count: 0}}),
  agentsCountAliasIsNotOnline: agentOnlineCountView({mission, roster: {agents_count: 0}}),
  emptyList: agentOnlineCountView({mission, roster: []}),
  emptyAgentsField: agentOnlineCountView({mission, roster: {agents: []}}),
  noneRunning: agentOnlineCountView({
    mission,
    roster: [
      agent("a", "created"),
      agent("b", "paused"),
      agent("c", "completed"),
      agent("d", "failed"),
      agent("e", "stopped"),
      agent("f", "blocked"),
    ],
  }),
  oneRunning: agentOnlineCountView({
    mission,
    roster: [agent("a", "running"), agent("b", "completed")],
  }),
  twoRunning: agentOnlineCountView({
    mission,
    roster: {agents: [agent("a", "running"), agent("b", "stopped"), agent("c", "running")]},
  }),
  listBeatsConflictingCount: agentOnlineCountView({
    mission,
    roster: {agents: [agent("a", "running")], agent_count: 9},
  }),
  missingStatus: agentOnlineCountView({
    mission,
    roster: [agent("a", "running"), {id: "b"}],
  }),
  unknownStatus: agentOnlineCountView({
    mission,
    roster: [agent("a", "online")],
  }),
  duplicateId: agentOnlineCountView({
    mission,
    roster: [agent("a", "running"), agent("a", "stopped")],
  }),
  missingId: agentOnlineCountView({
    mission,
    roster: [{status: "running"}],
  }),
  unavailable: AGENT_ONLINE_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
