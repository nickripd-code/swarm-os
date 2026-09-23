import {workspaceChipView, WORKSPACE_UNAVAILABLE} from "../app/static/state.mjs";

const mission = {id: "mission-1", goal: "Ship the notes", status: "running"};
const root = "/tmp/swarm-workspaces";

function view(health, options) {
  return workspaceChipView(mission, health, options);
}

const cases = {
  unavailable: WORKSPACE_UNAVAILABLE,
  noMission: workspaceChipView(null, {provider: "local", status: "healthy", root}),
  preview: workspaceChipView(mission, {provider: "local", status: "healthy", root}, {preview: true}),
  missingHealth: view(null),
  emptyHealth: view({}),
  localHealthy: view({provider: "local", status: "healthy", root, backend: "filesystem", docker: false}),
  remoteHealthy: view({provider: "remote", status: "healthy", root: "sandbox://box-1"}),
  localUnwritable: view({provider: "local", status: "unavailable", root, detail: "Workspace root is not writable"}),
  unconfiguredWithRoot: view({provider: "local", status: "unconfigured", root}),
  blankRoot: view({provider: "local", status: "healthy", root: "   "}),
  missingRoot: view({provider: "local", status: "healthy"}),
  unknownProvider: view({provider: "docker", status: "healthy", root, backend: "filesystem"}),
  backendOnly: view({status: "healthy", root, backend: "filesystem", docker: false}),
  dockerDoesNotFlipKind: view({provider: "local", status: "healthy", root, docker: true}),
  numericRoot: view({provider: "local", status: "healthy", root: 12}),
  weirdStatus: view({provider: "local", status: "Healthy", root}),
  missionRecordWins: workspaceChipView(
    {...mission, workspace: {provider: "remote", status: "healthy", root: "sandbox://mission"}},
    {provider: "local", status: "healthy", root},
  ),
  emptyMissionRecord: workspaceChipView(
    {...mission, workspace: {}},
    {provider: "local", status: "healthy", root},
  ),
  providerCase: view({provider: " LOCAL ", status: "healthy", root}),
};

console.log(JSON.stringify(cases));
