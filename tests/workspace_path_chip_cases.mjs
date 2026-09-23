import {workspacePathChip, shortenWorkspacePath} from "../app/static/state.mjs";

const mission = {id: "mission-1", goal: "Ship the notes", status: "running"};
const root = "/var/lib/swarm/workspaces/sandbox-root";
const cases = {};

cases.noMission = workspacePathChip(null, {root}, {preview: false});
cases.preview = workspacePathChip(mission, {root, status: "healthy", provider: "local"}, {preview: true});
cases.previewMission = workspacePathChip({id: "preview", goal: "Design a launch plan"}, {root}, {});
cases.missingHealth = workspacePathChip(mission, null, {});
cases.emptyHealth = workspacePathChip(mission, {}, {});
cases.blankRoot = workspacePathChip(mission, {root: "   ", provider: "local", status: "healthy"}, {});
cases.numericRoot = workspacePathChip(mission, {root: 12, detail: root}, {});
cases.detailOnly = workspacePathChip(mission, {
  provider: "local", status: "healthy", backend: "filesystem", docker: false, detail: "Local filesystem sandbox",
}, {});
cases.shortRoot = workspacePathChip(mission, {root: "/tmp/swarm-workspaces", status: "healthy"}, {});
cases.longRoot = workspacePathChip(mission, {root, status: "unavailable", provider: "local"}, {});
cases.windowsRoot = workspacePathChip(mission, {root: "C:\\Users\\dev\\AppData\\Local\\Temp\\swarm-workspaces"}, {});
cases.controlChar = workspacePathChip(mission, {root: "/tmp/swarm\nworkspaces"}, {});
cases.whitespacePad = workspacePathChip(mission, {root: "  /opt/swarm  "}, {});
cases.shortenLimit = shortenWorkspacePath(root, 24);

console.log(JSON.stringify(cases));
