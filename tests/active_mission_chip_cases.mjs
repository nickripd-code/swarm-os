import {activeMissionChipView, ACTIVE_MISSIONS_UNAVAILABLE} from "../app/static/state.mjs";

const cases = {};
const unavailable = (view) => view.known === false && view.count === null && view.label === ACTIVE_MISSIONS_UNAVAILABLE;

cases.nullHealth = activeMissionChipView(null);
cases.missingField = activeMissionChipView({ok: true});
cases.empty = activeMissionChipView({});
cases.nullCount = activeMissionChipView({active_missions: null});
cases.stringCount = activeMissionChipView({active_missions: "2"});
cases.stringZero = activeMissionChipView({active_missions: "0"});
cases.boolCount = activeMissionChipView({active_missions: true});
cases.floatCount = activeMissionChipView({active_missions: 1.5});
cases.negative = activeMissionChipView({active_missions: -1});
cases.nan = activeMissionChipView({active_missions: Number.NaN});
cases.infinity = activeMissionChipView({active_missions: Number.POSITIVE_INFINITY});
cases.arrayHealth = activeMissionChipView([{active_missions: 3}]);
cases.unsafe = activeMissionChipView({active_missions: Number.MAX_SAFE_INTEGER + 1});
cases.zero = activeMissionChipView({active_missions: 0, ok: true});
cases.one = activeMissionChipView({active_missions: 1});
cases.many = activeMissionChipView({active_missions: 4});

const flags = {
  nullHealth: unavailable(cases.nullHealth),
  missingField: unavailable(cases.missingField),
  empty: unavailable(cases.empty),
  nullCount: unavailable(cases.nullCount),
  stringCount: unavailable(cases.stringCount),
  stringZero: unavailable(cases.stringZero),
  boolCount: unavailable(cases.boolCount),
  floatCount: unavailable(cases.floatCount),
  negative: unavailable(cases.negative),
  nan: unavailable(cases.nan),
  infinity: unavailable(cases.infinity),
  arrayHealth: unavailable(cases.arrayHealth),
  unsafe: unavailable(cases.unsafe),
};

console.log(JSON.stringify({cases, flags, unavailable: ACTIVE_MISSIONS_UNAVAILABLE}));
