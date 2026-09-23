import {
  recordedEventRateFeed, eventRateView, EVENT_RATE_UNAVAILABLE,
} from "../app/static/state.mjs";

function event(id, at) {
  return {id, event_type: "agent.spawned", payload: {id}, created_at: at};
}

const t0 = "2026-01-01T00:00:00.000Z";
const t1 = "2026-01-01T00:01:00.000Z";
const t2 = "2026-01-01T00:02:00.000Z";
const log = [
  event("a", t0),
  null,
  event("b", t1),
  {id: "missing"},
  event("c", t2),
];
const stamped = [event("a", t0), event("b", t1), event("c", t2)];

const cases = {};
cases.unavailable = EVENT_RATE_UNAVAILABLE;
cases.hidden = eventRateView(stamped, {visible: false, windowMs: 60000});
cases.hiddenDefault = eventRateView(stamped, {windowMs: 60000});
cases.preview = eventRateView(stamped, {visible: false, windowMs: 0});
cases.missingNull = eventRateView(null, {visible: true, windowMs: 60000});
cases.missingUndefined = eventRateView(undefined, {visible: true, windowMs: 60000});
cases.missingObject = eventRateView({events: stamped, perMinute: 9}, {visible: true, windowMs: 60000});
cases.emptyNoWindow = eventRateView([], {visible: true});
cases.emptyNegativeWindow = eventRateView([], {visible: true, windowMs: -1});
cases.emptyBadWindow = eventRateView([], {visible: true, windowMs: Number.NaN});
cases.emptyZeroWindow = eventRateView([], {visible: true, windowMs: 0});
cases.emptyKnownWindow = eventRateView([], {visible: true, windowMs: 120000});
cases.oneStamp = eventRateView([event("only", t0)], {visible: true, windowMs: 60000});
cases.sameStamp = eventRateView([event("a", t0), event("b", t0)], {visible: true, windowMs: 60000});
cases.missingTimestamp = eventRateView([event("a", t0), {id: "bare", event_type: "mission.started"}], {visible: true, windowMs: 60000});
cases.badTimestamp = eventRateView([event("a", t0), event("b", "not-a-time")], {visible: true, windowMs: 60000});
cases.nonObject = eventRateView([event("a", t0), "nope"], {visible: true, windowMs: 60000});
cases.twoPerMinute = eventRateView([event("a", t0), event("b", t1)], {visible: true});
cases.onePointFive = eventRateView(stamped, {visible: true});
cases.skipsHoles = eventRateView([null, event("a", t0), null, event("b", t1)], {visible: true});
cases.holesOnlyNoWindow = eventRateView([null, undefined], {visible: true});
cases.holesOnlyKnownWindow = eventRateView([null], {visible: true, windowMs: 1000});
cases.prefix = eventRateView(recordedEventRateFeed(stamped, 1, true), {visible: true});
cases.prefixFirst = eventRateView(recordedEventRateFeed(stamped, 0, true), {visible: true, windowMs: 60000});
cases.prefixAll = eventRateView(recordedEventRateFeed(stamped, stamped.length - 1, true), {visible: true});
cases.beforeAny = eventRateView(recordedEventRateFeed(stamped, -1, true), {visible: true, windowMs: 0});
cases.beforeAnyNoWindow = eventRateView(recordedEventRateFeed(stamped, -1, true), {visible: true});
cases.unloaded = recordedEventRateFeed(stamped, stamped.length - 1, false);
cases.unloadedView = eventRateView(recordedEventRateFeed([], 0, false), {visible: true, windowMs: 60000});
cases.explicitEmptyFeed = recordedEventRateFeed([], -1, true);
cases.notArrayLog = recordedEventRateFeed({length: 0}, 0, true);
cases.withHoleInLog = eventRateView(recordedEventRateFeed(log, 2, true), {visible: true});
const tinySpan = 24_000_001;
cases.tinyRate = eventRateView([
  {id: "a", created_at: new Date(0).toISOString()},
  {id: "b", created_at: new Date(tinySpan).toISOString()},
], {visible: true});

console.log(JSON.stringify(cases));
