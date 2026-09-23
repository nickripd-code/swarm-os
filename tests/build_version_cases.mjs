import { buildVersionView, VERSION_UNAVAILABLE } from "../app/static/state.mjs";

const cases = {
  missingBody: buildVersionView(null),
  missingField: buildVersionView({ok: true}),
  nullVersion: buildVersionView({version: null}),
  blank: buildVersionView({version: "   "}),
  number: buildVersionView({version: 0.2}),
  declared: buildVersionView({version: "0.2.0"}),
  trim: buildVersionView({version: "  1.4.2-gabcdef  "}),
  unavailableLiteral: VERSION_UNAVAILABLE,
};

console.log(JSON.stringify(cases));
