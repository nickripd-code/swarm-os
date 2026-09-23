import {serverHealthChip, formatUptimeSeconds, SERVER_HEALTH_UNAVAILABLE} from "../app/static/state.mjs";

const now = Date.parse("2026-09-23T12:00:00Z");
const cases = {};

cases.missing = serverHealthChip(null, now);
cases.empty = serverHealthChip({}, now);
cases.nullClock = serverHealthChip({started_at: null, uptime: null, version: "0.2.0"}, now);
cases.negativeUptime = serverHealthChip({
  started_at: "2026-09-23T11:00:00+00:00",
  uptime: -5,
  version: "0.2.0",
}, now);
cases.stringUptime = serverHealthChip({uptime: "90", started_at: "2026-09-23T11:00:00Z"}, now);
cases.nanUptime = serverHealthChip({uptime: Number.NaN, version: "0.2.0"}, now);
cases.zero = serverHealthChip({uptime: 0, version: "0.2.0"}, now);
cases.ninety = serverHealthChip({
  uptime: 90,
  started_at: "2020-01-01T00:00:00Z",
  version: "0.2.0",
}, now);
cases.versionPrefixed = serverHealthChip({uptime: 3661, version: "v0.2.0"}, now);
cases.noVersion = serverHealthChip({uptime: 45}, now);
cases.ageFromStart = serverHealthChip({started_at: "2026-09-23T11:58:30Z", version: "0.2.0"}, now);
cases.futureStart = serverHealthChip({started_at: "2026-09-23T13:00:00Z"}, now);
cases.badStart = serverHealthChip({started_at: "not-a-time"}, now);
cases.blankVersion = serverHealthChip({uptime: 12, version: "  "}, now);
cases.format = {
  negative: formatUptimeSeconds(-1),
  text: formatUptimeSeconds("3"),
  zero: formatUptimeSeconds(0),
  day: formatUptimeSeconds(90061),
};
cases.unavailable = SERVER_HEALTH_UNAVAILABLE;

console.log(JSON.stringify(cases));
