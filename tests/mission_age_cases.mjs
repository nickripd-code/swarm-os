import {missionAgeChip, newState} from "../app/static/state.mjs";

const STAMP = "2026-09-23T08:00:00Z";
const NOW = Date.parse("2026-09-23T08:04:00Z");
const EARLIER = "2026-09-22T08:00:00Z";

function mission(extra = {}) {
  return {id: "m1", goal: "Ship the landing page", status: "running", ...extra};
}

function view(extra, now = NOW, preview = false) {
  return missionAgeChip({preview, mission: mission(extra)}, {now});
}

const cases = {
  idle: missionAgeChip(newState(), {now: NOW}),
  noMission: missionAgeChip({preview: false, mission: null}, {now: NOW}),
  preview: view({created_at: STAMP}, NOW, true),
  known: view({created_at: STAMP}),
  startedAt: view({started_at: STAMP, created_at: EARLIER}),
  nullStarted: view({started_at: null, created_at: STAMP}),
  runtimeStarted: view({runtime: {started_at: STAMP}, created_at: EARLIER}),
  runtimeCreated: view({runtime: {created_at: STAMP}}),
  offset: view({created_at: "2026-09-23T03:00:00-05:00"}),
  seconds: view({created_at: STAMP}, Date.parse("2026-09-23T08:00:59Z")),
  justNow: view({created_at: STAMP}, Date.parse(STAMP)),
  hours: view({created_at: STAMP}, Date.parse("2026-09-23T10:00:00Z")),
  oneDay: view({created_at: STAMP}, Date.parse("2026-09-24T08:00:00Z")),
  micros: view({created_at: "2026-09-23T08:00:00.250000Z"}, Date.parse("2026-09-23T08:00:59.900Z")),
  skewOk: view({created_at: STAMP}, Date.parse(STAMP) - 120000),
  noClock: view({created_at: STAMP}, undefined),
  badNow: missionAgeChip({preview: false, mission: mission({created_at: STAMP})}, {now: Number.NaN}),
  zeroNow: missionAgeChip({preview: false, mission: mission({created_at: STAMP})}, {now: 0}),
  bad: {
    blank: view({created_at: ""}),
    whitespace: view({created_at: "   "}),
    blankStarted: view({started_at: "  ", created_at: STAMP}),
    invalid: view({created_at: "yesterday"}),
    missingZone: view({created_at: "2026-09-23T08:00:00"}),
    epoch: view({created_at: "1970-01-01T00:00:00Z"}),
    epochOffset: view({created_at: "1970-01-01T00:00:00+00:00"}),
    epochMillis: view({created_at: 0}),
    numeric: view({created_at: 1758614400000}),
    missing: view({}),
    nullCreated: view({created_at: null}),
    impossible: view({created_at: "2026-02-31T08:00:00Z"}),
    skew: view({created_at: STAMP}, Date.parse(STAMP) - 121000),
    emptyRuntime: view({runtime: {}}),
  },
};

process.stdout.write(JSON.stringify(cases));
