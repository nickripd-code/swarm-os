import {objectiveSnippet, OBJECTIVE_SNIPPET_PHONE_LIMIT} from "../app/static/state.mjs";

function graphemes(value) {
  return [...new Intl.Segmenter(undefined, {granularity: "grapheme"}).segment(value)].length;
}

const family = "👨‍👩‍👧‍👦";
const shortGoal = "Publish the weekly launch note";
const spaced = "Ship the weekly status note to the team before Friday standup and include the open risks";
const token = "A".repeat(120);
const emojiFit = "a".repeat(OBJECTIVE_SNIPPET_PHONE_LIMIT - 1) + family;
const emojiOverflow = "a".repeat(OBJECTIVE_SNIPPET_PHONE_LIMIT) + family;

const cases = {
  limit: OBJECTIVE_SNIPPET_PHONE_LIMIT,
  empty: {
    missing: objectiveSnippet(null),
    blank: objectiveSnippet({id: "m1", goal: "   \n\t"}),
    nonString: objectiveSnippet({id: "m1", goal: 12}),
    objectGoal: objectiveSnippet({id: "m1", goal: {text: "Invented goal"}}),
    objectiveOnly: objectiveSnippet({id: "m1", objective: "Invented from objective"}),
    previewId: objectiveSnippet({id: "preview", goal: "Design a launch plan for a small business"}),
    previewFlag: objectiveSnippet({id: "m1", goal: shortGoal}, {preview: true}),
  },
  short: objectiveSnippet({id: "m1", goal: `  ${shortGoal}\n`}),
  collapsed: objectiveSnippet({id: "m1", goal: "alpha\nbeta\tgamma"}),
  spaced: objectiveSnippet({id: "m1", goal: spaced}),
  token: objectiveSnippet({id: "m1", goal: token}),
  markup: objectiveSnippet({id: "m1", goal: "<script>alert(1)</script> " + shortGoal}),
  emojiFit: objectiveSnippet({id: "m1", goal: emojiFit}),
  emojiOverflow: objectiveSnippet({id: "m1", goal: emojiOverflow}),
  badLimit: objectiveSnippet({id: "m1", goal: token}, {limit: 3}),
};

for (const key of ["spaced", "token", "emojiFit", "emojiOverflow", "badLimit", "short", "markup"]) {
  cases[key].graphemes = graphemes(cases[key].text);
}

console.log(JSON.stringify(cases));
