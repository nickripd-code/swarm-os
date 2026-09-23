import {providerStripView, CONFIGURATION_UNAVAILABLE} from "../app/static/state.mjs";

const cases = {};

cases.empty = providerStripView(null);
cases.missingField = providerStripView({openai: {configured: true}});
cases.emptyList = providerStripView({connectivity: {providers: []}});
cases.stringTrue = providerStripView({
  connectivity: {providers: [{id: "openai", label: "OpenAI", configured: "true"}]},
});
cases.boolTrue = providerStripView({
  connectivity: {
    providers: [
      {id: "openai", label: "OpenAI", kind: "model", configured: true, state: "configured"},
      {id: "openrouter", label: "OpenRouter", kind: "model", configured: false, state: "missing"},
      {id: "workspace", label: "Workspace", kind: "tool", configured: true, detail: "local"},
      {id: " ", label: "blank"},
      null,
      {label: "no-id", configured: true},
    ],
  },
});
cases.secretDetail = providerStripView({
  connectivity: {
    providers: [{
      id: "openai",
      label: "OpenAI",
      configured: true,
      detail: "sk-live-secret",
    }],
  },
});
cases.CONFIGURATION_UNAVAILABLE = CONFIGURATION_UNAVAILABLE;

console.log(JSON.stringify(cases));
