import {explicitOrgNodes, orgMapNodeView, ORG_MAP_UNAVAILABLE} from "../app/static/state.mjs";

const node = (id, parent_id = null) => ({id, parent_id, role: "specialist", status: "running", depth: parent_id ? 1 : 0});

const cases = {
  unavailableLabel: ORG_MAP_UNAVAILABLE,
  hidden: orgMapNodeView(undefined, {visible: false}),
  hiddenWithMap: orgMapNodeView([node("a")], {visible: false}),
  missing: orgMapNodeView(undefined, {visible: true}),
  nullMap: orgMapNodeView(null, {visible: true}),
  emptyObject: orgMapNodeView({}, {visible: true}),
  numericZero: orgMapNodeView(0, {visible: true}),
  stringZero: orgMapNodeView("0", {visible: true}),
  loneId: orgMapNodeView({id: "mission"}, {visible: true}),
  countField: orgMapNodeView({node_count: 0, agent_count: 4}, {visible: true}),
  emptyList: orgMapNodeView([], {visible: true}),
  emptyAgents: orgMapNodeView({agents: [], tasks: []}, {visible: true}),
  emptyTopology: orgMapNodeView({op: "retire", topology: [], agents: [node("a")]}, {visible: true}),
  agents: orgMapNodeView({agents: [node("root"), node("child", "root"), node("child", "root")]}, {visible: true}),
  topology: orgMapNodeView({topology: [node("root"), node("child", "root")]}, {visible: true}),
  list: orgMapNodeView([node("root"), node("a", "root"), node("b", "root")], {visible: true}),
  junk: orgMapNodeView([{role: "no-id"}, "x", null], {visible: true}),
  explicitNodes: explicitOrgNodes([node("root")]).length,
};

console.log(JSON.stringify(cases));
