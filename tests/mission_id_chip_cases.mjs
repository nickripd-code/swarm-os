import { missionIdChip } from "../app/static/state.mjs";

const uuid = "11111111-1111-4111-8111-111111111111";
const other = "22222222-2222-4222-8222-222222222222";

const cases = {
  none: missionIdChip(null),
  missing: missionIdChip({}),
  empty: missionIdChip({id: ""}),
  blank: missionIdChip({id: "   "}),
  padded: missionIdChip({id: " " + uuid}),
  number: missionIdChip({id: 12345}),
  objectId: missionIdChip({id: {id: uuid}}),
  previewFlag: missionIdChip({id: uuid}, {preview: true}),
  previewSentinel: missionIdChip({id: "preview"}, {preview: false}),
  stringPreviewFlag: missionIdChip({id: uuid}, {preview: "true"}),
  control: missionIdChip({id: "abc\ndef"}),
  uuid: missionIdChip({id: uuid}),
  other: missionIdChip({id: other}),
  short: missionIdChip({id: "abc123"}),
  exact8: missionIdChip({id: "abcd1234"}),
  nine: missionIdChip({id: "abcdefghi"}),
};

console.log(JSON.stringify(cases));
