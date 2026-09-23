import {connectionStateChipView, CONNECTION_STATE_UNAVAILABLE} from "../app/static/state.mjs";

const labels = [
  "Connecting",
  "Preview",
  "Replay",
  "Live connection",
  "Connection interrupted",
  "Reconnecting…",
  "All execution stopped",
  "Ready to think",
  "API key needed",
  "Server unavailable",
  "Mission completed",
  "Mission failed",
  "Mission stopped",
  "Mission blocked",
];

const cases = {
  unavailable: CONNECTION_STATE_UNAVAILABLE,
  known: Object.fromEntries(labels.map((label) => [label, connectionStateChipView(label)])),
  trimmed: connectionStateChipView("  Live connection  "),
  blank: ["", "   ", "\n"].map(connectionStateChipView),
  missing: [null, undefined, false].map(connectionStateChipView),
  bad: [0, 1, true, "connected", "disconnected", "Connected", "CONNECTED", "Mission running", "online"].map(connectionStateChipView),
  absent: connectionStateChipView({present: false, label: "Live connection"}),
  emptyObject: connectionStateChipView({}),
  previewHidden: connectionStateChipView({
    present: true,
    preview: true,
    connectionHidden: true,
    label: "Preview",
  }),
  previewShown: connectionStateChipView({
    present: true,
    preview: true,
    connectionHidden: false,
    label: "Preview",
  }),
  hiddenButLive: connectionStateChipView({
    present: true,
    preview: false,
    connectionHidden: true,
    label: "Live connection",
  }),
  presentBlank: connectionStateChipView({present: true, label: "   "}),
  textField: connectionStateChipView({present: true, text: "Replay"}),
};

console.log(JSON.stringify(cases));
