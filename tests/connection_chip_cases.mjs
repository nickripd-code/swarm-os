import {connectionChipView, LINK_UNAVAILABLE} from "../app/static/state.mjs";

const cases = {};

function view(link) {
  return connectionChipView(link);
}

cases.unavailable = LINK_UNAVAILABLE;
cases.missing = [null, undefined, 0, "", "connected", true, false].map(view);
cases.health = view({configured: true, openai: {configured: true}, connected: true});
cases.claimed = view({connected: true, readyState: 1});
cases.stringOpen = view({transport: "websocket", readyState: "1"});
cases.open = view({transport: "websocket", readyState: 1});
cases.openWhileRetry = view({transport: "websocket", readyState: 1, reconnecting: true});
cases.connecting = view({transport: "websocket", readyState: 0});
cases.closing = view({transport: "websocket", readyState: 2});
cases.closed = view({transport: "websocket", readyState: 3});
cases.retry = view({transport: "websocket", readyState: 3, reconnecting: true});
cases.sseOpen = view({transport: "sse", readyState: 1});
cases.sseClosed = view({transport: "sse", readyState: 2});
cases.sseConnecting = view({transport: "sse", readyState: 0, reconnecting: true});
cases.otherTransport = view({transport: "poll", readyState: 1});
cases.boolReady = view({transport: "websocket", readyState: true});
cases.floatReady = view({transport: "websocket", readyState: 1.5});
cases.flagString = view({transport: "websocket", readyState: 3, reconnecting: "true"});

console.log(JSON.stringify(cases));
