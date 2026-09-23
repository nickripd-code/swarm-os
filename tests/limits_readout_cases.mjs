import { limitsReadoutView } from "../app/static/state.mjs";

const healthDefaults = {
  available: true,
  phase: "create_defaults",
  max_agents: 20,
  max_depth: 4,
  max_tool_calls: 200,
  max_runtime_seconds: 300,
  max_token_cost: null,
  token_cost_cap: 3,
  token_cost_known: true,
  token_cost_source: "server_default",
  token_cost_hard_cap: 10,
};

const cases = {};

cases.missing = limitsReadoutView({});

cases.healthDefaults = limitsReadoutView({health: healthDefaults});

cases.unknownToken = limitsReadoutView({
  health: {
    available: true,
    max_agents: 20,
    max_depth: 4,
    max_tool_calls: 200,
    max_runtime_seconds: 90,
    max_token_cost: null,
    token_cost_cap: null,
    token_cost_known: false,
  },
});

cases.missionListed = limitsReadoutView({
  health: healthDefaults,
  mission: {limits: {max_agents: 3, max_depth: 2, max_tool_calls: 8, max_runtime_seconds: 120, max_token_cost: 1.5}},
});

cases.hardCap = limitsReadoutView({
  health: healthDefaults,
  mission: {limits: {max_agents: 3, max_depth: 1, max_tool_calls: 8, max_runtime_seconds: 3600, max_token_cost: 50}},
});

cases.missionUnsetToken = limitsReadoutView({
  health: healthDefaults,
  mission: {limits: {max_agents: 20, max_depth: 4, max_tool_calls: 200, max_runtime_seconds: 300, max_token_cost: null}},
});

cases.previewIgnoresFakeLimits = limitsReadoutView({
  health: healthDefaults,
  preview: true,
  mission: {limits: {max_agents: 999, max_depth: 9, max_tool_calls: 9, max_runtime_seconds: 9, max_token_cost: 99}},
});

cases.corruptCounts = limitsReadoutView({
  health: {available: true, max_agents: "20", max_depth: -1, max_tool_calls: null, token_cost_known: false},
});

cases.zeroListed = limitsReadoutView({
  health: {available: true, token_cost_known: false, token_cost_hard_cap: 10},
  mission: {limits: {max_agents: 1, max_depth: 0, max_tool_calls: 1, max_runtime_seconds: 60, max_token_cost: 0}},
});

process.stdout.write(JSON.stringify(cases));
