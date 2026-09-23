export const ESTIMATE_UNAVAILABLE = "estimate unavailable";

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatUsd(value) {
  const n = finiteNumber(value);
  if (n === null || n < 0) return null;
  if (n === 0) return "$0";
  if (n < 0.01) return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}

function tokenSuffix(summary) {
  if (summary?.tokens_recorded !== true) return "";
  const total = summary.tokens && summary.tokens.total;
  if (typeof total !== "number" || !Number.isInteger(total) || total < 0) return "";
  return " · " + total.toLocaleString() + " tokens";
}

export function spendSummaryView(summary, options = {}) {
  const preview = options.preview === true;
  const known = !preview
    && summary?.token_estimate_known === true
    && finiteNumber(summary.token_estimate) !== null
    && summary.token_estimate >= 0;
  const spend = known ? formatUsd(summary.token_estimate) : null;
  const rateKnown = known
    && summary?.burn_known === true
    && finiteNumber(summary.burn_usd_per_hour) !== null
    && summary.burn_usd_per_hour >= 0;
  const rate = rateKnown ? formatUsd(summary.burn_usd_per_hour) : null;
  let ledgerLabel = "unavailable";
  if (preview || !summary || summary.mission_id == null) ledgerLabel = "no mission";
  else if (
    summary.payment_known === true
    && finiteNumber(summary.payment_spent) !== null
    && summary.payment_spent >= 0
    && finiteNumber(summary.payment_budget) !== null
    && summary.payment_budget >= 0
  ) {
    ledgerLabel = formatUsd(summary.payment_spent) + " of " + formatUsd(summary.payment_budget);
  }
  let liveLabel = "unavailable";
  if (summary && summary.live_spend_enabled === false) liveLabel = "off";
  else if (summary && summary.live_spend_enabled === true) liveLabel = "on";
  let providersLabel = "unavailable";
  if (summary && summary.providers_configured === false) providersLabel = "unset";
  else if (summary && summary.providers_configured === true) providersLabel = "configured";
  const tokenLabel = known && spend
    ? spend + tokenSuffix(summary)
    : ESTIMATE_UNAVAILABLE + (preview ? "" : tokenSuffix(summary));
  let note = summary && typeof summary.note === "string" && summary.note
    ? summary.note
    : "Spend summary unavailable.";
  if (preview) note = "Preview does not report spend. " + note;
  return {
    state: known ? "recorded" : "unavailable",
    tokenLabel,
    rateLabel: rate ? rate + "/h" : ESTIMATE_UNAVAILABLE,
    ledgerLabel,
    liveLabel,
    providersLabel,
    note,
  };
}
