import {spendSummaryView} from "./spend-summary.mjs";

const $ = id => document.getElementById(id);
let generation = 0;
let lastKey = "";

function paint(view) {
  const root = $("spendSummary");
  if (!root) return;
  root.dataset.state = view.state;
  if ($("spendSummaryNote")) $("spendSummaryNote").textContent = view.note;
  if ($("spendSummaryTokens")) $("spendSummaryTokens").textContent = view.tokenLabel;
  if ($("spendSummaryRate")) $("spendSummaryRate").textContent = view.rateLabel;
  if ($("spendSummaryLedger")) $("spendSummaryLedger").textContent = view.ledgerLabel;
  if ($("spendSummaryLive")) $("spendSummaryLive").textContent = view.liveLabel;
  if ($("spendSummaryProviders")) $("spendSummaryProviders").textContent = view.providersLabel;
}

async function load(missionId, preview, stamp) {
  const key = (preview ? "preview" : "live") + ":" + (missionId || "") + ":" + stamp;
  if (key === lastKey) return;
  const gen = ++generation;
  const path = !preview && missionId
    ? "/api/missions/" + encodeURIComponent(missionId) + "/spend-summary"
    : "/api/spend-summary";
  let summary = null;
  try {
    const response = await fetch(path);
    if (!response.ok) throw new Error("unavailable");
    summary = await response.json();
  } catch {
    summary = null;
  }
  if (gen !== generation) return;
  if (summary == null) lastKey = "";
  else lastKey = key;
  paint(spendSummaryView(summary, {preview: preview === true}));
}

document.addEventListener("swarm-spend-context", event => {
  const detail = event.detail || {};
  load(detail.missionId || null, detail.preview === true, detail.stamp || 0);
});

load(null, false, 0);
