import {missionAgentCount, AGENT_COUNT_UNAVAILABLE} from "../app/static/state.mjs";

const cases = {
  missing: missionAgentCount(undefined),
  null: missionAgentCount(null),
  missionWithoutAgents: missionAgentCount({id: "m1", goal: "ship", status: "running"}),
  nullAgents: missionAgentCount({agents: null}),
  stringZero: missionAgentCount({agent_count: "0"}),
  bareNumber: missionAgentCount(0),
  negative: missionAgentCount({agent_count: -1}),
  fraction: missionAgentCount({agents_count: 1.5}),
  emptyList: missionAgentCount([]),
  emptyAgentsField: missionAgentCount({agents: []}),
  explicitZero: missionAgentCount({agent_count: 0}),
  explicitZeroAlias: missionAgentCount({agents_count: 0}),
  oneAgent: missionAgentCount([{id: "a1"}]),
  twoAgents: missionAgentCount({agents: [{id: "a1"}, {id: "a2"}]}),
  listBeatsConflictingCount: missionAgentCount({agents: [{id: "a1"}, {id: "a2"}], agent_count: 9}),
  unavailable: AGENT_COUNT_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
