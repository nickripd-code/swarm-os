import {shortcutHintView, SHORTCUT_UNAVAILABLE} from "../app/static/state.mjs";

const wired = (chord, action = "Focus command") => ({wired: true, chord, action});
const listenerSource = (chord) => [
  'document.addEventListener("keydown", (event) => {',
  "  if (event.ctrlKey && event.key) event.preventDefault();",
  "});",
  "const documented = \"" + chord + "\";",
].join("\n");

const cases = {};
cases.empty = shortcutHintView();
cases.noListener = shortcutHintView({
  bindings: [wired("Ctrl+K", "Focus command")],
  hasKeyListener: false,
  source: listenerSource("Ctrl+K"),
});
cases.listenerFlagWithoutSource = shortcutHintView({
  bindings: [wired("Ctrl+K", "Focus command")],
  hasKeyListener: true,
  source: "",
});
cases.unwired = shortcutHintView({
  bindings: [{wired: false, chord: "Ctrl+K", action: "Focus command"}],
  hasKeyListener: true,
  source: listenerSource("Ctrl+K"),
});
cases.missingAction = shortcutHintView({
  bindings: [{wired: true, chord: "Ctrl+K", action: "  "}],
  hasKeyListener: true,
  source: listenerSource("Ctrl+K"),
});
cases.chordNotLiteral = shortcutHintView({
  bindings: [wired("Ctrl+K", "Focus command")],
  hasKeyListener: true,
  source: 'document.addEventListener("keydown", (event) => { if (event.ctrlKey && event.key === "k") event.preventDefault(); });',
});
cases.commandVerbs = shortcutHintView({
  bindings: [
    wired("stop", "Stop mission"),
    wired("stop-all", "Stop all"),
    wired("kill", "Kill agent"),
    wired("answer", "Answer question"),
  ],
  hasKeyListener: true,
  source: [
    'document.addEventListener("keydown", () => {});',
    'const verbs = "stop" "stop-all" "kill" "answer";',
  ].join("\n"),
});
cases.documented = shortcutHintView({
  bindings: [
    wired("Ctrl+K", "Focus command"),
    wired("Ctrl+K", "Duplicate"),
    {wired: true, chord: "Escape", action: "Dismiss"},
  ],
  hasKeyListener: true,
  source: listenerSource("Ctrl+K") + '\nconst other = "Escape";',
});
cases.unavailable = SHORTCUT_UNAVAILABLE;

process.stdout.write(JSON.stringify(cases));
