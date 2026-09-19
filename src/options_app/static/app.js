const serviceStatus = document.querySelector("#service-status");
const dataStatus = document.querySelector("#data-status");
const assetList = document.querySelector("#asset-list");
const form = document.querySelector("#scan-form");
const resultState = document.querySelector("#result-state");
const resultsBody = document.querySelector("#results-body");
const resultsTableWrap = document.querySelector("#results-table-wrap");
const secondaryResults = document.querySelector("#secondary-results");
const resultsGuide = document.querySelector("#results-guide");
const valuationModeNotice = document.querySelector("#valuation-mode-notice");
const scanContext = document.querySelector("#scan-context");
const historicalContext = document.querySelector("#historical-context");
const opportunityExplanations = document.querySelector("#opportunity-explanations");
const detailPanel = document.querySelector("#opportunity-detail");
const detailSummary = document.querySelector("#detail-summary");
const closeDetailButton = document.querySelector("#close-detail");
const scenarioState = document.querySelector("#scenario-state");
const detailMetrics = document.querySelector("#detail-metrics");
const scenarioResultsBody = document.querySelector("#scenario-results-body");
const pnlChart = document.querySelector("#pnl-chart");
const pnlChartShell = document.querySelector("#pnl-chart-shell");
const pnlChartTooltip = document.querySelector("#pnl-chart-tooltip");
const pnlChartLegend = document.querySelector("#pnl-chart-legend");
const pnlChartAssumptions = document.querySelector("#pnl-chart-assumptions");
const pnlChartStatus = document.querySelector("#pnl-chart-status");
const scanTerminal = document.querySelector("#scan-terminal");
const clearTerminalButton = document.querySelector("#clear-terminal");
const backtestForm = document.querySelector("#backtest-form");
const backtestAsset = document.querySelector("#backtest-asset");
const backtestExitPolicy = document.querySelector("#backtest-exit-policy");
const backtestState = document.querySelector("#backtest-state");
const backtestQuality = document.querySelector("#backtest-quality");
const backtestMetrics = document.querySelector("#backtest-metrics");
const backtestTradesBody = document.querySelector("#backtest-trades-body");
const backtestProfitField = document.querySelector("#backtest-profit-field");
const backtestStopField = document.querySelector("#backtest-stop-field");
const backtestDteField = document.querySelector("#backtest-dte-field");
const monitoringForm = document.querySelector("#monitoring-form");
const monitoringBaseCoin = document.querySelector("#monitoring-base-coin");
const monitoringPositionType = document.querySelector("#monitoring-position-type");
const monitoringSymbol = document.querySelector("#monitoring-symbol");
const monitoringPolicyProfile = document.querySelector("#monitoring-policy-profile");
const monitoringState = document.querySelector("#monitoring-state");
const monitoringMetrics = document.querySelector("#monitoring-metrics");
const monitoringDecisionGuide = document.querySelector("#monitoring-decision-guide");
const monitoringDecisionsBody = document.querySelector("#monitoring-decisions-body");
const monitoringEmptyState = document.querySelector("#monitoring-empty-state");

// Strategy Builder DOM elements
const builderAssetSelect = document.querySelector("#builder-asset-select");
const builderExpirySelect = document.querySelector("#builder-expiry-select");
const builderSpotDisplay = document.querySelector("#builder-spot-display");
const builderPresetButtons = document.querySelector("#builder-preset-buttons");
const builderEvaluateBtn = document.querySelector("#builder-evaluate-btn");
const builderSaveNotebookBtn = document.querySelector("#builder-save-notebook-btn");
const builderAddLegBtn = document.querySelector("#builder-add-leg-btn");
const builderClearLegsBtn = document.querySelector("#builder-clear-legs-btn");
const builderLegsTbody = document.querySelector("#builder-legs-tbody");
const builderLegsEmpty = document.querySelector("#builder-legs-empty");
const builderStatusBadge = document.querySelector("#builder-status-badge");
const builderMetrics = document.querySelector("#builder-metrics");
const bmNetPremium = document.querySelector("#bm-net-premium");
const bmMaxProfit = document.querySelector("#bm-max-profit");
const bmMaxLoss = document.querySelector("#bm-max-loss");
const bmRrRatio = document.querySelector("#bm-rr-ratio");
const bmBreakeven = document.querySelector("#bm-breakeven");
const bgDelta = document.querySelector("#bg-delta");
const bgGamma = document.querySelector("#bg-gamma");
const bgTheta = document.querySelector("#bg-theta");
const bgVega = document.querySelector("#bg-vega");
const builderPayoffSvg = document.querySelector("#builder-payoff-svg");
const builderChartWrap = document.querySelector("#builder-chart-wrap");
const builderChartTooltip = document.querySelector("#builder-chart-tooltip");
const builderChainStatus = document.querySelector("#builder-chain-status");
const builderChainTbody = document.querySelector("#builder-chain-tbody");

// Trade Notebook & Smart Monitor DOM elements
const nbRefreshBtn = document.querySelector("#nb-refresh-btn");
const nbStatTotal = document.querySelector("#nb-stat-total");
const nbStatPnl = document.querySelector("#nb-stat-pnl");
const nbStatTp = document.querySelector("#nb-stat-tp");
const nbStatSl = document.querySelector("#nb-stat-sl");
const nbStatHold = document.querySelector("#nb-stat-hold");
const nbPositionsTbody = document.querySelector("#nb-positions-tbody");
const nbEmptyState = document.querySelector("#nb-empty-state");

let builderState = {
  asset: "BTC",
  expiry: "",
  spot: 0,
  legs: [],
  chainData: null,
  activePreset: "bull_call_vertical",
  evaluation: null,
  initialized: false,
};
const workspaceLinks = [...document.querySelectorAll("[data-workspace-link]")];
const workspaceViews = [...document.querySelectorAll("[data-workspace-view]")];
const moduleEyebrow = document.querySelector("#module-eyebrow");
const moduleTitle = document.querySelector("#module-title");
const moduleDescription = document.querySelector("#module-description");
const liveToggle = document.querySelector("#live-toggle");
const liveConnection = document.querySelector("#live-connection");
const liveConnectionLabel = document.querySelector("#live-connection-label");
const liveLastUpdate = document.querySelector("#live-last-update");
const liveUpdateCountLabel = document.querySelector("#live-update-count");
const liveSessionState = document.querySelector("#live-session-state");
const liveNextRefresh = document.querySelector("#live-next-refresh");
const liveStatSpot = document.querySelector("#live-stat-spot");
const liveStatSpotLabel = document.querySelector("#live-stat-spot-label");
const liveStatOpportunities = document.querySelector("#live-stat-opportunities");
const liveStatOpportunitiesLabel = document.querySelector("#live-stat-opportunities-label");
const liveStatEdge = document.querySelector("#live-stat-edge");
const liveStatDte = document.querySelector("#live-stat-dte");
const liveStatContracts = document.querySelector("#live-stat-contracts");
const liveStatContractsLabel = document.querySelector("#live-stat-contracts-label");
const liveStatRejections = document.querySelector("#live-stat-rejections");
const liveStatRejectionsLabel = document.querySelector("#live-stat-rejections-label");
const marketStrip = document.querySelector("#market-strip");
const signalChart = document.querySelector("#signal-chart");
const liveOptionChart = document.querySelector("#live-option-chart");
const liveOptionSelect = document.querySelector("#live-option-select");
const liveOptionTape = document.querySelector("#live-option-tape-body");
const liveSignalStatus = document.querySelector("#live-signal-status");
const liveFeed = document.querySelector("#live-feed");
const liveRejectionSummary = document.querySelector("#live-rejection-summary");

let selectedOpportunity = null;
let activeScanContext = null;
let activeScanValuationMode = "executable";
let monitoringSocket = null;
let monitoringRequestKey = null;

const liveDesk = window.FlowSurfaceLiveDesk.createController({
  elements: {
    serviceStatus,
    liveToggle,
    liveConnection,
    liveConnectionLabel,
    liveLastUpdate,
    liveUpdateCountLabel,
    liveSessionState,
    liveNextRefresh,
    liveStatSpot,
    liveStatSpotLabel,
    liveStatOpportunities,
    liveStatOpportunitiesLabel,
    liveStatEdge,
    liveStatDte,
    liveStatContracts,
    liveStatContractsLabel,
    liveStatRejections,
    liveStatRejectionsLabel,
    marketStrip,
    signalChart,
    liveOptionChart,
    liveOptionSelect,
    liveOptionTape,
    liveSignalStatus,
    liveFeed,
    liveRejectionSummary,
  },
  getSelectedAssets: () => [...form.querySelectorAll('input[name="assets"]:checked')].map((input) => input.value),
  onLog: appendTerminal,
});

const WORKSPACE_META = Object.freeze({
  scanner: {
    eyebrow: "Nghiên cứu quyền chọn / Scanner",
    title: "Crypto Options Scanner",
    description: "Tìm hợp đồng có chênh lệch giữa giá mô hình và giá có thể mua.",
  },
  builder: {
    eyebrow: "Nghiên cứu quyền chọn / Strategy Builder",
    title: "Options Strategy Builder & Payoff",
    description: "Lắp ráp chiến lược đa chân, tính toán Greeks, vẽ đồ thị Payoff và chuyển vào Sổ tay giám sát.",
  },
  backtest: {
    eyebrow: "Nghiên cứu quyền chọn / Backtest",
    title: "Historical Options Backtest",
    description: "Replay tín hiệu trên archive snapshot để kiểm tra chất lượng và rủi ro.",
  },
  monitoring: {
    eyebrow: "Theo dõi vị thế / Risk & exit review",
    title: "Position Monitoring",
    description: "Kiểm tra lệnh đã mở và nhận quyết định CLOSE, HOLD hoặc REVIEW trước khi đóng thủ công.",
  },
  "live-desk": {
    eyebrow: "Realtime market / Live Desk",
    title: "Live Options Market",
    description: "Theo dõi option quotes trực tiếp qua WebSocket, độc lập với Scanner.",
  },
});

function syncWorkspaceFromHash() {
  const requestedWorkspace = window.location.hash.slice(1).toLowerCase();
  const workspace = Object.prototype.hasOwnProperty.call(WORKSPACE_META, requestedWorkspace)
    ? requestedWorkspace
    : "scanner";
  if (!window.location.hash) window.history.replaceState(null, "", "#scanner");
  const meta = WORKSPACE_META[workspace];

  if (workspace !== "monitoring" && monitoringSocket) {
    monitoringSocket.close();
    monitoringSocket = null;
    monitoringRequestKey = null;
  }
  if (workspace !== "live-desk" && liveDesk.isWanted()) liveDesk.stop();

  workspaceLinks.forEach((link) => {
    const isActive = link.getAttribute("href") === `#${workspace}`;
    link.classList.toggle("is-active", isActive);
    if (isActive) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  workspaceViews.forEach((view) => {
    view.hidden = view.dataset.workspaceView !== workspace;
  });
  if (moduleEyebrow) moduleEyebrow.textContent = meta.eyebrow;
  if (moduleTitle) moduleTitle.textContent = meta.title;
  if (moduleDescription) moduleDescription.textContent = meta.description;
  if (document.body.dataset.activeWorkspace && document.body.dataset.activeWorkspace !== workspace) {
    appendTerminal(`[ĐIỀU HƯỚNG] Chuyển không gian làm việc: ${meta.title} (#${workspace})`, "info");
  }
  document.body.dataset.activeWorkspace = workspace;

  if (workspace === "builder" && !builderState.initialized) {
    initStrategyBuilder();
  }
  if (workspace === "monitoring") {
    loadTradeNotebook();
  }
}

const valuationModeInputs = [...form.querySelectorAll('input[name="valuation_mode"]')];
const modeSensitiveInputNames = [
  "quick_max_loss",
  "max_loss",
  "max_spread_pct",
  "min_edge_after_costs",
];

const SVG_NS = "http://www.w3.org/2000/svg";

const STRATEGY_LABELS = Object.freeze({
  long_call: "Mua call",
  long_put: "Mua put",
  call_vertical: "Call vertical",
  put_vertical: "Put vertical",
  bull_call_vertical: "Bull call vertical",
  bear_call_vertical: "Bear call vertical",
  bull_put_vertical: "Bull put vertical",
  bear_put_vertical: "Bear put vertical",
  bull_call_spread: "Bull call vertical",
  bear_call_spread: "Bear call vertical",
  bull_put_spread: "Bull put vertical",
  bear_put_spread: "Bear put vertical",
  iron_condor: "Iron condor",
  iron_butterfly: "Iron butterfly",
  long_straddle: "Long straddle",
  long_strangle: "Long strangle",
  protective_put: "Protective put",
  covered_call: "Covered call",
  calendar_spread: "Calendar spread",
  butterfly: "Butterfly",
  broken_wing_butterfly: "Broken-wing butterfly",
});

const STRATEGY_GROUPS = Object.freeze({
  call_vertical: ["bull_call_vertical", "bear_call_vertical"],
  put_vertical: ["bull_put_vertical", "bear_put_vertical"],
});

function normalizedStrategy(strategy) {
  return String(strategy || "").trim().toLowerCase().replace(/-/g, "_");
}

function strategyLabel(strategy) {
  const normalized = normalizedStrategy(strategy);
  if (Object.prototype.hasOwnProperty.call(STRATEGY_LABELS, normalized)) return STRATEGY_LABELS[normalized];
  if (!normalized) return "Chiến lược không xác định";
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function opportunityLegs(item) {
  if (Array.isArray(item?.legs) && item.legs.length) return item.legs;
  const namedLegs = [
    item?.long_put_leg,
    item?.short_put_leg,
    item?.short_call_leg,
    item?.long_call_leg,
    item?.long_leg,
    item?.short_leg,
  ].filter(Boolean);
  if (namedLegs.length) return namedLegs;
  if (item?.long_symbol || item?.short_symbol) {
    return [
      {
        symbol: item.long_symbol,
        option_type: item.option_type,
        strike: item.long_strike,
        expiry_at: item.expiry_at,
        spot_price: item.spot_price,
        fair_iv: item.fair_iv,
        quote_timestamp: item.quote_timestamp,
        bid_price: item.bid_price,
        ask_price: item.ask_price,
        position: 1,
      },
      {
        symbol: item.short_symbol,
        option_type: item.option_type,
        strike: item.short_strike,
        expiry_at: item.expiry_at,
        spot_price: item.spot_price,
        fair_iv: item.fair_iv,
        quote_timestamp: item.quote_timestamp,
        bid_price: item.bid_price,
        ask_price: item.ask_price,
        position: -1,
      },
    ].filter((leg) => leg.symbol);
  }
  return [item];
}

function firstDefined(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== "");
}

function metricValue(item, names) {
  const sources = [item, item?.metrics, item?.decision_metrics, item?.valuation_metrics];
  for (const source of sources) {
    if (!source || typeof source !== "object") continue;
    const value = firstDefined(...names.map((name) => source[name]));
    if (value !== undefined) return value;
  }
  return undefined;
}

function modelProbability(item) {
  // win_rate is a legacy alias for this app's model probability.  It is not
  // treated as historical evidence and is never used by historicalWinRate.
  return metricValue(item, [
    "model_probability",
    "model_win_probability",
    "win_probability",
    "probability_of_profit",
    "win_rate",
  ]);
}

function historicalWinRate(item) {
  return metricValue(item, [
    "historical_win_rate",
    "realized_win_rate",
    "validated_win_rate",
    "out_of_sample_win_rate",
    "backtest_win_rate",
  ]);
}

function conventionalRewardRisk(item) {
  return metricValue(item, [
    "reward_risk_ratio",
    "conventional_reward_risk_ratio",
    "conventional_risk_reward",
    "risk_reward_ratio",
  ]);
}

function payoffContributionRatio(item) {
  return metricValue(item, ["payoff_contribution_ratio", "risk_reward"]);
}

function breakEvenWinProbability(item) {
  return metricValue(item, [
    "break_even_win_probability",
    "break_even_probability",
    "breakeven_probability",
  ]);
}

function expectancyAfterCosts(item) {
  return metricValue(item, ["expectancy_after_costs", "expectancy_after_cost", "expectancy"]);
}

function fairValueEdge(item) {
  return metricValue(item, ["fair_value_edge", "edge_after_costs"]);
}

function evidenceStatus(item) {
  return metricValue(item, ["evidence_status"]);
}

function rejectionReason(item) {
  return metricValue(item, ["rejection_reason", "rejection_reasons", "reasons"]);
}

function legSymbol(leg) {
  return firstDefined(leg?.symbol, leg?.contract_symbol, "Mã chưa có");
}

function legStrike(leg) {
  return firstDefined(leg?.strike, leg?.strike_price);
}

function opportunitySymbol(item) {
  const legs = opportunityLegs(item);
  if (legs.length > 1) return legs.map((leg) => legSymbol(leg)).join(" / ");
  return firstDefined(item?.symbol, legSymbol(legs[0]), "Mã chưa có");
}

function opportunityExpiry(item) {
  const firstLeg = opportunityLegs(item)[0];
  return firstDefined(
    item?.expiry_at,
    item?.expiry,
    item?.expiry_date,
    item?.expiration_date,
    firstLeg?.expiry_at,
    firstLeg?.expiry,
    firstLeg?.expiry_date,
    firstLeg?.expiration_date,
  );
}

function expiryLabel(item) {
  const rawExpiry = opportunityExpiry(item);
  if (!rawExpiry) return "—";
  const parsedExpiry = new Date(rawExpiry);
  if (Number.isNaN(parsedExpiry.getTime())) return String(rawExpiry);
  const date = parsedExpiry.toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Asia/Ho_Chi_Minh",
  });
  const dte = Number(item?.dte);
  return Number.isFinite(dte) ? `${date}\nCòn ${Math.max(0, Math.round(dte))} ngày` : date;
}

function legExpiryLabel(leg, item) {
  const rawExpiry = firstDefined(
    leg?.expiry_at,
    leg?.expiry,
    leg?.expiry_date,
    leg?.expiration_date,
    item?.expiry_at,
    item?.expiry,
    item?.expiry_date,
    item?.expiration_date,
  );
  if (!rawExpiry) return "Hết hạn —";
  const parsedExpiry = new Date(rawExpiry);
  if (Number.isNaN(parsedExpiry.getTime())) return `Hết hạn ${String(rawExpiry)}`;
  const date = parsedExpiry.toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Asia/Ho_Chi_Minh",
  });
  const time = parsedExpiry.toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Ho_Chi_Minh",
  });
  const dte = Number(firstDefined(leg?.dte, item?.dte));
  const dteText = Number.isFinite(dte) ? ` · Còn ${Math.max(0, Math.round(dte))} ngày` : "";
  return `Hết hạn ${date} ${time}${dteText}`;
}

function renderInstrumentCell(row, item) {
  const element = document.createElement("td");
  element.className = "symbol instrument-cell";
  const legs = opportunityLegs(item);
  const title = document.createElement("div");
  title.className = "instrument-title";
  title.textContent = `${firstDefined(item?.asset, "—")} · ${opportunitySymbol(item)}`;
  element.appendChild(title);
  if (legs.length > 1) {
    const summary = document.createElement("div");
    summary.className = "leg-summary";
    legs.forEach((leg, index) => {
      const line = document.createElement("span");
      const strike = legStrike(leg);
      const strikeText = strike === undefined ? "K—" : `K${number(strike, 2)}`;
      line.textContent = `Chân ${index + 1}: ${legSymbol(leg)} · ${strikeText}`;
      summary.appendChild(line);
    });
    element.appendChild(summary);
  }
  row.appendChild(element);
}

function normalizedOptionType(leg) {
  return String(firstDefined(leg?.option_type, leg?.type, "")).trim().toLowerCase();
}

function inferredMultiLegPosition(strategy, leg, legs) {
  const normalized = normalizedStrategy(strategy);
  const strike = Number(legStrike(leg));
  if (!Number.isFinite(strike)) return 1;

  const strikes = legs.map(legStrike).map(Number).filter(Number.isFinite).sort((left, right) => left - right);
  if (normalized === "iron_condor" && strikes.length >= 4) {
    const optionType = normalizedOptionType(leg);
    if (optionType.includes("put")) return strike === strikes[0] ? 1 : -1;
    if (optionType.includes("call")) return strike === strikes[strikes.length - 1] ? 1 : -1;
  }
  if (normalized === "iron_butterfly" && strikes.length >= 4) {
    const uniqueStrikes = [...new Set(strikes)];
    const centerStrike = uniqueStrikes[Math.floor(uniqueStrikes.length / 2)];
    return strike === centerStrike ? -1 : 1;
  }
  return 1;
}

function inferredLegPosition(strategy, leg, legs) {
  const explicitPosition = firstDefined(leg?.position, leg?.side_position);
  if (explicitPosition !== undefined) return Number(explicitPosition);
  const role = String(firstDefined(leg?.role, leg?.side, leg?.action, "")).toLowerCase();
  if (role.includes("short") || role.includes("sell") || role === "-1") return -1;
  if (role.includes("long") || role.includes("buy") || role === "+1" || role === "1") return 1;
  if (legs.length !== 2) return inferredMultiLegPosition(strategy, leg, legs);
  const normalized = normalizedStrategy(strategy);
  const strike = Number(legStrike(leg));
  const other = legs.find((candidate) => candidate !== leg);
  const otherStrike = Number(legStrike(other));
  const isLowerStrike = Number.isFinite(strike) && Number.isFinite(otherStrike) && strike < otherStrike;
  if (["bull_call_vertical", "bull_call_spread"].includes(normalized)) return isLowerStrike ? 1 : -1;
  if (["bear_call_vertical", "bear_call_spread"].includes(normalized)) return isLowerStrike ? -1 : 1;
  if (["bull_put_vertical", "bull_put_spread"].includes(normalized)) return isLowerStrike ? 1 : -1;
  if (["bear_put_vertical", "bear_put_spread"].includes(normalized)) return isLowerStrike ? -1 : 1;
  return 1;
}


function setState(message, className = "") {
  resultState.textContent = message;
  resultState.className = `state-message ${className}`.trim();
}

function appendTerminal(message, className = "") {
  const line = document.createElement("div");
  line.className = `terminal-line ${className}`.trim();
  line.textContent = `[${new Date().toLocaleTimeString("vi-VN")}] ${message}`;
  scanTerminal.appendChild(line);
  scanTerminal.scrollTop = scanTerminal.scrollHeight;
  const parentDetails = scanTerminal.closest("details");
  if (parentDetails && !parentDetails.open) {
    parentDetails.open = true;
  }
}

function clearTerminal() {
  scanTerminal.replaceChildren();
  appendTerminal("Nhật ký hệ thống đã được xóa.");
}

function cell(row, value, className = "") {
  const element = document.createElement("td");
  element.textContent = value;
  if (className) element.className = className;
  row.appendChild(element);
}

function number(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  if (!Number.isFinite(Number(value))) return Number(value) > 0 ? "Không giới hạn" : "—";
  return Number(value).toFixed(digits);
}

function percent(value) {
  return value === null || value === undefined ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
}

function optionTypeLabel(leg) {
  const optionType = normalizedOptionType(leg);
  if (optionType.includes("put")) return "Put";
  if (optionType.includes("call")) return "Call";
  const symbol = legSymbol(leg).toUpperCase();
  if (/(^|-)P(-|$)/.test(symbol)) return "Put";
  if (/(^|-)C(-|$)/.test(symbol)) return "Call";
  return "quyền chọn";
}

function signedPriceLabel(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "Chưa có dữ liệu giá gói";
  if (amount < 0) return `Nhận credit khoảng ${number(Math.abs(amount), 2)}`;
  return `Trả premium khoảng ${number(amount, 2)}`;
}

function isTheoreticalMode(value) {
  return String(value || "").toLowerCase() === "theoretical";
}

function isSyntheticMode(value) {
  return String(value || "").toLowerCase() === "synthetic";
}

function isModelValuationMode(value) {
  return isTheoreticalMode(value) || isSyntheticMode(value);
}

function valuationModeLabel(value) {
  if (isSyntheticMode(value)) return "Synthetic bid/ask";
  if (isTheoreticalMode(value)) return "Theoretical";
  return "Executable";
}

function selectedValuationMode() {
  return form.querySelector('input[name="valuation_mode"]:checked')?.value || "executable";
}

function syncValuationModeInputs() {
  const theoretical = isTheoreticalMode(selectedValuationMode());
  const synthetic = isSyntheticMode(selectedValuationMode());
  modeSensitiveInputNames.forEach((name) => {
    const input = form.elements[name];
    if (!input) return;
    input.disabled = theoretical;
    input.closest("label")?.classList.toggle("mode-disabled", theoretical);
  });
  const spreadInput = form.elements.assumed_spread_bps;
  if (spreadInput) {
    spreadInput.disabled = !synthetic;
    spreadInput.closest("label")?.classList.toggle("mode-disabled", !synthetic);
  }
}

function strategyTakeaway(item, legs) {
  const asset = firstDefined(item?.asset, "tài sản");
  if (isSyntheticMode(item?.valuation_mode || activeScanValuationMode)) {
    return `Đây là định giá với bid/ask tổng hợp cho ${asset}; edge, payoff, EV, xác suất và reward/risk được tính theo spread giả định, không khẳng định giá khớp thực tế.`;
  }
  if (isTheoreticalMode(item?.valuation_mode || activeScanValuationMode)) {
    return `Đây là định giá mô hình của ${asset}; payoff, EV, xác suất và reward/risk được tính từ fair value nhưng không khẳng định giá khớp hay lợi nhuận thực tế.`;
  }
  const strategy = normalizedStrategy(item?.strategy);
  const strikes = legs
    .map(legStrike)
    .map(Number)
    .filter(Number.isFinite)
    .sort((left, right) => left - right);

  if (strategy === "iron_butterfly") {
    const shortStrikes = legs
      .filter((leg) => inferredLegPosition(strategy, leg, legs) < 0)
      .map(legStrike)
      .map(Number)
      .filter(Number.isFinite);
    const center = shortStrikes.length ? shortStrikes[0] : strikes[Math.floor(strikes.length / 2)];
    return center === undefined
      ? `Có lợi nhất khi ${asset} đi ngang gần vùng strike trung tâm.`
      : `Có lợi nhất khi ${asset} đóng cửa gần K${number(center, 2)} vào ngày đáo hạn; rủi ro được giới hạn ở hai cánh.`;
  }
  if (strategy === "iron_condor") {
    const shortStrikes = legs
      .filter((leg) => inferredLegPosition(strategy, leg, legs) < 0)
      .map(legStrike)
      .map(Number)
      .filter(Number.isFinite)
      .sort((left, right) => left - right);
    return shortStrikes.length >= 2
      ? `Có lợi nhất khi ${asset} nằm giữa K${number(shortStrikes[0], 2)} và K${number(shortStrikes[1], 2)}.`
      : `Có lợi nhất khi ${asset} đi ngang trong vùng giữa hai chân bán.`;
  }
  if (strategy === "long_call") return `Kỳ vọng ${asset} tăng giá; lãi tăng khi giá vượt strike và rủi ro tối đa là premium đã trả.`;
  if (strategy === "long_put") return `Kỳ vọng ${asset} giảm giá; lãi tăng khi giá xuống dưới strike và rủi ro tối đa là premium đã trả.`;
  if (strategy === "long_straddle") return `Kỳ vọng ${asset} biến động mạnh theo một trong hai hướng; cần vượt qua tổng premium đã trả để có lợi nhuận.`;
  if (strategy === "long_strangle") return `Kỳ vọng ${asset} biến động rất mạnh; chi phí thường thấp hơn straddle nhưng cần vượt qua hai strike ngoài.`;
  if (strategy === "protective_put") return `Dùng để bảo hiểm vị thế ${asset} đang nắm giữ trước một nhịp giảm; premium là chi phí bảo hiểm.`;
  if (strategy === "covered_call") return `Phù hợp khi đang nắm ${asset} và kỳ vọng tăng nhẹ hoặc đi ngang; đổi lại phần tăng giá phía trên strike bị giới hạn.`;
  if (strategy === "calendar_spread") return `Phù hợp khi kỳ vọng giá quanh strike và muốn khai thác chênh lệch theta hoặc IV giữa kỳ hạn gần và xa.`;
  if (strategy === "butterfly") return strikes.length >= 3
    ? `Có lợi nhất khi ${asset} đóng cửa gần K${number(strikes[Math.floor(strikes.length / 2)], 2)}; chi phí và lỗ tối đa được giới hạn.`
    : `Phù hợp khi kỳ vọng ${asset} hội tụ về một vùng strike trung tâm với rủi ro giới hạn.`;
  if (strategy === "broken_wing_butterfly") return `Phù hợp khi có thiên kiến nhẹ về một hướng và muốn vùng lợi nhuận lệch theo hướng đó, với rủi ro vẫn được giới hạn theo cấu trúc.`;
  if (strategy.startsWith("bull_")) return `Kỳ vọng ${asset} tăng giá; lãi và lỗ đều được giới hạn bởi hai strike.`;
  if (strategy.startsWith("bear_")) return `Kỳ vọng ${asset} giảm giá; lãi và lỗ đều được giới hạn bởi hai strike.`;
  return `Đây là chiến lược ${strategyLabel(item?.strategy)}; hãy kiểm tra payoff và điều kiện vị thế trước khi sử dụng.`;
}

function explanationFact(label, value, className = "") {
  const fact = document.createElement("div");
  fact.className = "explanation-fact";
  const factLabel = document.createElement("span");
  factLabel.className = "muted";
  factLabel.textContent = label;
  const factValue = document.createElement("strong");
  factValue.className = className;
  factValue.textContent = value;
  fact.append(factLabel, factValue);
  return fact;
}

function renderOpportunityExplanation(item, index) {
  const legs = opportunityLegs(item);
  const theoretical = isTheoreticalMode(item?.valuation_mode || activeScanValuationMode);
  const synthetic = isSyntheticMode(item?.valuation_mode || activeScanValuationMode);
  const modelMode = theoretical || synthetic;
  const card = document.createElement("article");
  card.className = "explanation-card";

  const heading = document.createElement("div");
  heading.className = "explanation-heading";
  const title = document.createElement("h3");
  title.textContent = `${index + 1}. ${firstDefined(item?.asset, "—")} · ${strategyLabel(item?.strategy)}`;
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = synthetic
    ? `${legs.length} chân · Synthetic`
    : theoretical
    ? `${legs.length} chân · Theoretical`
    : `${legs.length} chân`;
  const popVal = firstDefined(item?.win_probability, item?.win_rate, item?.probability_of_profit);
  if (popVal !== undefined && popVal !== null && Number.isFinite(Number(popVal))) {
    const popBadge = document.createElement("span");
    popBadge.className = `badge ${popVal >= 0.60 ? "positive" : popVal < 0.40 ? "negative" : ""}`.trim();
    popBadge.textContent = `PoP: ${(Number(popVal) * 100).toFixed(0)}%`;
    heading.append(title, badge, popBadge);
  } else {
    heading.append(title, badge);
  }
  card.appendChild(heading);

  const symbolText = opportunitySymbol(item);
  if (symbolText && symbolText !== "—" && symbolText !== "Mã chưa có") {
    const symbolLine = document.createElement("div");
    symbolLine.className = "explanation-symbol muted";
    symbolLine.textContent = `${firstDefined(item?.asset, "—")} · ${symbolText}`;
    card.appendChild(symbolLine);
  }

  const takeaway = document.createElement("p");
  takeaway.className = "explanation-takeaway";
  takeaway.textContent = strategyTakeaway(item, legs);
  card.appendChild(takeaway);

  const legList = document.createElement("div");
  legList.className = "explanation-legs leg-summary";
  legs.forEach((leg, idx) => {
    const position = inferredLegPosition(item?.strategy, leg, legs);
    const legLine = document.createElement("span");
    legLine.className = position > 0 ? "buy-leg" : "sell-leg";
    const action = position > 0 ? "Mua" : "Bán";
    const strike = legStrike(leg);
    const strikeText = Number.isFinite(Number(strike)) ? `K${number(strike, 2)}` : "—";
    const legSym = legSymbol(leg);
    const symText = legSym && legSym !== "—" ? ` · ${legSym}` : "";
    const prefix = legs.length > 1 ? `Chân ${idx + 1}: ` : "";
    legLine.textContent = `${prefix}${action} ${optionTypeLabel(leg)} ${strikeText}${symText} · ${legExpiryLabel(leg, item)}`;
    legList.appendChild(legLine);
  });
  card.appendChild(legList);

  const executablePrice = firstDefined(item?.estimated_entry, item?.executable_entry, item?.market_mid);
  const fairPrice = firstDefined(item?.fair_price);
  const edge = Number(fairValueEdge(item));
  const facts = document.createElement("div");
  facts.className = "explanation-facts";

  let entryPriceText = signedPriceLabel(executablePrice);
  if (theoretical) {
    entryPriceText = Number.isFinite(Number(item?.market_mid))
      ? `Tham khảo ${number(item?.market_mid)}`
      : "Không có giá khớp";
  } else if (synthetic) {
    entryPriceText = Number.isFinite(Number(item?.market_mid))
      ? `Giả định ${number(item?.market_mid, 4)} (${signedPriceLabel(executablePrice)})`
      : signedPriceLabel(executablePrice);
  }

  facts.append(
    explanationFact(synthetic ? "Giá vào mô hình" : "Tiền vào/ra ước tính", entryPriceText, modelMode ? "theoretical-value" : ""),
    explanationFact("Mô hình định giá", signedPriceLabel(fairPrice), modelMode ? "theoretical-value" : ""),
    explanationFact("Edge fair value sau phí", theoretical ? "Không tính" : Number.isFinite(edge) ? `${edge >= 0 ? "+" : ""}${number(edge, 4)}` : "Không có dữ liệu", modelMode ? "theoretical-value" : edge >= 0 ? "positive" : "negative"),
    explanationFact(modelMode ? "EV mô hình" : "EV ước tính", estimatedNumber(firstDefined(item?.estimated_ev, item?.expected_value, item?.ev)), modelMode ? "theoretical-value" : ""),
    explanationFact("Expectancy sau chi phí", estimatedNumber(expectancyAfterCosts(item)), modelMode ? "theoretical-value" : ""),
    explanationFact("Xác suất mô hình", estimateProbability(modelProbability(item)), modelMode ? "theoretical-value" : ""),
    explanationFact("R:R thông thường", estimateRatio(conventionalRewardRisk(item)), modelMode ? "theoretical-value" : ""),
    explanationFact("Xác suất hòa vốn", estimateProbability(breakEvenWinProbability(item)), modelMode ? "theoretical-value" : ""),
    explanationFact(modelMode ? "Lỗ tối đa (mô hình)" : "Lỗ tối đa", estimatedNumber(item?.max_loss), modelMode ? "theoretical-value" : "negative"),
    explanationFact("Evidence", evidenceStatusLabel(evidenceStatus(item)), ""),
    explanationFact("Thanh khoản", `OI ${number(item?.open_interest, 0)} · Vol ${number(item?.volume_24h, 0)}`, ""),
  );
  const historicalRate = historicalWinRate(item);
  if (historicalRate !== undefined) {
    facts.append(explanationFact("Win rate lịch sử", estimateProbability(historicalRate), ""));
  }
  const contributionRatio = payoffContributionRatio(item);
  if (contributionRatio !== undefined) {
    facts.append(explanationFact("Tỷ lệ đóng góp payoff", estimateRatio(contributionRatio), ""));
  }
  card.appendChild(facts);

  const extra = document.createElement("p");
  extra.className = "explanation-extra muted";
  const maxProfit = item?.max_profit;
  const breakevens = Array.isArray(item?.breakevens) ? item.breakevens : [];
  const parts = [];
  if (maxProfit !== undefined && maxProfit !== null) parts.push(`${modelMode ? "Lãi tối đa (mô hình)" : "Lãi tối đa"}: ${number(maxProfit, 2)}`);
  if (breakevens.length) {
    parts.push(`Hòa vốn: ${breakevens.map((value) => `K${number(value, 2)}`).join(" và ")}`);
    const spot = item?.spot_price;
    if (spot && Number.isFinite(Number(spot)) && Number(spot) > 0) {
      const minMove = Math.min(...breakevens.map((b) => Math.abs(Number(b) - Number(spot)) / Number(spot) * 100));
      parts.push(`Cần biến động: ≥${minMove.toFixed(1)}%`);
    }
  }
  parts.push(`${modelMode ? "IV edge mô hình" : "IV edge"}: ${percent(item?.iv_edge)}`);
  extra.textContent = parts.join(" · ");
  card.appendChild(extra);

  const actions = document.createElement("div");
  actions.className = "explanation-card-actions";

  const openBuilderBtn = document.createElement("button");
  openBuilderBtn.type = "button";
  openBuilderBtn.className = "btn-scanner-action";
  openBuilderBtn.appendChild(createSvgIcon("wrench"));
  openBuilderBtn.appendChild(document.createTextNode(" Mở trong Strategy Builder"));
  openBuilderBtn.addEventListener("click", () => openOpportunityInBuilder(item));

  const saveNbBtn = document.createElement("button");
  saveNbBtn.type = "button";
  saveNbBtn.className = "btn-scanner-action";
  saveNbBtn.appendChild(createSvgIcon("bookmark"));
  saveNbBtn.appendChild(document.createTextNode(" Lưu Sổ tay"));
  saveNbBtn.addEventListener("click", () => saveOpportunityToNotebook(item));

  const viewPayoffBtn = document.createElement("button");
  viewPayoffBtn.type = "button";
  viewPayoffBtn.className = "btn-scanner-action";
  viewPayoffBtn.appendChild(createSvgIcon("line-chart"));
  const payoffText = document.createTextNode(
    synthetic ? " Xem payoff tổng hợp" : theoretical ? " Xem payoff mô hình" : " Xem payoff / P&L"
  );
  viewPayoffBtn.appendChild(payoffText);
  viewPayoffBtn.addEventListener("click", () => showOpportunityDetail(item));

  actions.append(openBuilderBtn, saveNbBtn, viewPayoffBtn);
  card.appendChild(actions);

  return card;
}

function svgNode(name, attributes = {}, text = undefined) {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([attribute, value]) => node.setAttribute(attribute, String(value)));
  if (text !== undefined) node.textContent = text;
  return node;
}

function createSvgIcon(name) {
  const svg = svgNode("svg", { class: "btn-icon", "aria-hidden": "true" });
  const use = svgNode("use", { href: `#icon-${name}` });
  svg.appendChild(use);
  return svg;
}

function compactChartNumber(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  if (Math.abs(amount) >= 1000) return `${(amount / 1000).toFixed(1)}k`;
  return number(amount, 0);
}

function payoffPoints(item) {
  const curve = item?.payoff_curve;
  const rawPoints = Array.isArray(curve) ? curve : firstDefined(curve?.points, item?.payoff_points, []);
  if (!Array.isArray(rawPoints)) return [];
  return rawPoints
    .map((point) => ({
      underlyingPrice: Number(firstDefined(point?.underlying_price, point?.underlying, point?.price, point?.x)),
      pnl: Number(firstDefined(point?.pnl, point?.profit_loss, point?.payoff, point?.y)),
    }))
    .filter((point) => Number.isFinite(point.underlyingPrice) && Number.isFinite(point.pnl))
    .sort((left, right) => left.underlyingPrice - right.underlyingPrice);
}

function estimateProbability(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "Không có dữ liệu";
  return `${(amount <= 1 ? amount * 100 : amount).toFixed(2)}%`;
}

function estimateRatio(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? `${number(amount, 2)} : 1` : "Không có dữ liệu";
}

function evidenceStatusLabel(value) {
  if (value === null || value === undefined || value === "") return "Không có dữ liệu";
  const labels = {
    insufficient_evidence: "Chưa đủ bằng chứng lịch sử",
    not_validated: "Chưa kiểm định lịch sử",
    historically_validated: "Đã kiểm định lịch sử",
    validated: "Đã kiểm định",
    model_estimate: "Ước tính mô hình",
  };
  return labels[String(value)] || String(value);
}

function reasonLabel(value) {
  if (Array.isArray(value)) return value.join(" · ") || "Không có dữ liệu";
  return value === null || value === undefined || value === "" ? "Không có dữ liệu" : String(value);
}

function estimatedNumber(value, digits = 2) {
  return Number.isFinite(Number(value)) ? number(value, digits) : "Không có dữ liệu";
}

function methodologyNote(item) {
  const note = firstDefined(item?.methodology_note, item?.methodology, item?.assumption_note, item?.assumptions);
  if (typeof note === "string" && note.trim()) return note;
  if (note && typeof note === "object") return "API trả về các giả định có cấu trúc cho cơ hội này.";
  return "API không cung cấp ghi chú phương pháp.";
}

function showPayoffTooltip(point, event) {
  if (!pnlChartTooltip || !pnlChartShell) return;
  const shellBounds = pnlChartShell.getBoundingClientRect();
  const left = Math.min(Math.max(event.clientX - shellBounds.left + 12, 8), Math.max(8, shellBounds.width - 180));
  const top = Math.min(Math.max(event.clientY - shellBounds.top - 62, 8), Math.max(8, shellBounds.height - 70));
  pnlChartTooltip.textContent = `Giá cơ sở: ${number(point.underlyingPrice, 2)}\nP&L tại đáo hạn: ${number(point.pnl, 2)}`;
  pnlChartTooltip.style.left = `${left}px`;
  pnlChartTooltip.style.top = `${top}px`;
  pnlChartTooltip.hidden = false;
}

function addPayoffLegend() {
  pnlChartLegend.replaceChildren();
  const item = document.createElement("span");
  item.className = "chart-legend-item";
  const swatch = document.createElement("span");
  swatch.className = "chart-legend-swatch";
  swatch.style.backgroundColor = "#62d4a4";
  const label = document.createElement("span");
  label.textContent = "P&L tại đáo hạn (ước tính)";
  item.append(swatch, label);
  pnlChartLegend.appendChild(item);
}

function renderPayoffChart(item, points) {
  pnlChart.replaceChildren();
  pnlChartLegend.replaceChildren();
  pnlChartTooltip.hidden = true;
  if (!points.length) {
    pnlChartStatus.textContent = "Chưa có dữ liệu";
    return;
  }
  addPayoffLegend();

  const width = 960;
  const height = 430;
  const margin = { top: 24, right: 24, bottom: 58, left: 72 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const values = [0, ...points.map((point) => point.pnl)];
  let minPnl = Math.min(...values);
  let maxPnl = Math.max(...values);
  const pnlSpan = Math.max(maxPnl - minPnl, 1);
  minPnl -= pnlSpan * 0.12;
  maxPnl += pnlSpan * 0.12;
  let minPrice = Math.min(...points.map((point) => point.underlyingPrice));
  let maxPrice = Math.max(...points.map((point) => point.underlyingPrice));
  const priceSpan = Math.max(maxPrice - minPrice, 1);
  minPrice -= priceSpan * 0.04;
  maxPrice += priceSpan * 0.04;
  const x = (price) => margin.left + ((Number(price) - minPrice) / (maxPrice - minPrice)) * innerWidth;
  const y = (pnl) => margin.top + ((maxPnl - Number(pnl)) / (maxPnl - minPnl)) * innerHeight;

  pnlChart.setAttribute("aria-label", `Biểu đồ payoff P&L ước tính tại đáo hạn theo giá cơ sở, từ ${number(minPrice, 2)} đến ${number(maxPrice, 2)}`);
  pnlChart.appendChild(svgNode("rect", {
    x: margin.left,
    y: margin.top,
    width: innerWidth,
    height: innerHeight,
    fill: "#0f151c",
    rx: 8,
  }));

  for (let index = 0; index <= 4; index += 1) {
    const value = maxPnl - ((maxPnl - minPnl) * index / 4);
    const yPosition = y(value);
    pnlChart.appendChild(svgNode("line", {
      x1: margin.left,
      x2: width - margin.right,
      y1: yPosition,
      y2: yPosition,
      stroke: "#2c3a49",
      "stroke-dasharray": "3 5",
    }));
    pnlChart.appendChild(svgNode("text", {
      x: margin.left - 10,
      y: yPosition + 4,
      fill: "#9aabb8",
      "font-size": 12,
      "text-anchor": "end",
    }, compactChartNumber(value)));
  }

  if (minPnl <= 0 && maxPnl >= 0) {
    const zeroY = y(0);
    pnlChart.appendChild(svgNode("line", {
      x1: margin.left,
      x2: width - margin.right,
      y1: zeroY,
      y2: zeroY,
      stroke: "#ef8f8f",
      "stroke-dasharray": "5 4",
      "stroke-width": 1.5,
    }));
  }

  for (let index = 0; index <= 4; index += 1) {
    const price = minPrice + ((maxPrice - minPrice) * index / 4);
    const xPosition = x(price);
    pnlChart.appendChild(svgNode("line", {
      x1: xPosition,
      x2: xPosition,
      y1: margin.top,
      y2: height - margin.bottom,
      stroke: "#263544",
      "stroke-dasharray": "2 6",
    }));
    pnlChart.appendChild(svgNode("text", {
      x: xPosition,
      y: height - margin.bottom + 22,
      fill: "#9aabb8",
      "font-size": 12,
      "text-anchor": "middle",
    }, compactChartNumber(price)));
  }

  pnlChart.append(
    svgNode("line", { x1: margin.left, x2: margin.left, y1: margin.top, y2: height - margin.bottom, stroke: "#526273" }),
    svgNode("line", { x1: margin.left, x2: width - margin.right, y1: height - margin.bottom, y2: height - margin.bottom, stroke: "#526273" }),
    svgNode("text", { x: 18, y: margin.top + innerHeight / 2, fill: "#9aabb8", "font-size": 12, transform: `rotate(-90 18 ${margin.top + innerHeight / 2})`, "text-anchor": "middle" }, "P&L"),
    svgNode("text", { x: margin.left + innerWidth / 2, y: height - 10, fill: "#9aabb8", "font-size": 12, "text-anchor": "middle" }, "Giá cơ sở tại đáo hạn"),
  );
  const breakevens = Array.isArray(item?.breakevens) ? item.breakevens : [];
  breakevens.filter((value) => Number.isFinite(Number(value))).forEach((breakeven) => {
    const value = Number(breakeven);
    if (value < minPrice || value > maxPrice) return;
    pnlChart.appendChild(svgNode("line", {
      x1: x(value), x2: x(value), y1: margin.top, y2: height - margin.bottom,
      stroke: "#f0bb87", "stroke-dasharray": "4 5", "stroke-width": 1.5,
    }));
  });
  const pathData = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.underlyingPrice).toFixed(2)} ${y(point.pnl).toFixed(2)}`).join(" ");
  pnlChart.appendChild(svgNode("path", { d: pathData, fill: "none", stroke: "#62d4a4", "stroke-width": 2.5, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  points.forEach((point) => {
    const node = svgNode("circle", { cx: x(point.underlyingPrice), cy: y(point.pnl), r: 4, fill: "#62d4a4", stroke: "#0f151c", "stroke-width": 1.5, tabindex: 0 });
    node.setAttribute("aria-label", `Giá cơ sở ${number(point.underlyingPrice, 2)}; P&L tại đáo hạn ${number(point.pnl, 2)}`);
    node.addEventListener("pointerenter", (event) => showPayoffTooltip(point, event));
    node.addEventListener("pointerleave", () => { pnlChartTooltip.hidden = true; });
    node.addEventListener("focus", () => { pnlChartTooltip.textContent = `Giá cơ sở: ${number(point.underlyingPrice, 2)}\nP&L tại đáo hạn: ${number(point.pnl, 2)}`; pnlChartTooltip.hidden = false; });
    node.addEventListener("blur", () => { pnlChartTooltip.hidden = true; });
    pnlChart.appendChild(node);
  });
  pnlChartStatus.textContent = "Payoff từ API";
}

function setScenarioState(message, className = "") {
  scenarioState.textContent = message;
  scenarioState.className = `state-message ${className}`.trim();
}

function metric(label, value, className = "") {
  const item = document.createElement("div");
  item.className = "metric";
  const title = document.createElement("span");
  title.className = "muted";
  title.textContent = label;
  const amount = document.createElement("strong");
  amount.className = className;
  amount.textContent = value;
  item.append(title, amount);
  return item;
}

function renderPayoffDetail(item) {
  const points = payoffPoints(item);
  const theoretical = isTheoreticalMode(item?.valuation_mode || activeScanValuationMode);
  const synthetic = isSyntheticMode(item?.valuation_mode || activeScanValuationMode);
  const modelMode = theoretical || synthetic;
  renderPayoffChart(item, points);
  scenarioResultsBody.replaceChildren();
  detailMetrics.replaceChildren();
  detailMetrics.append(
    metric("Ngày đáo hạn", opportunityExpiry(item) ? expiryLabel(item) : "Không có dữ liệu"),
    metric(modelMode ? "EV mô hình" : "EV ước tính", estimatedNumber(firstDefined(item?.estimated_ev, item?.expected_value, item?.ev)), modelMode ? "theoretical-value" : ""),
    metric("Expectancy sau chi phí", estimatedNumber(expectancyAfterCosts(item)), modelMode ? "theoretical-value" : ""),
    metric("Xác suất mô hình", estimateProbability(modelProbability(item)), modelMode ? "theoretical-value" : ""),
    metric("R:R thông thường", estimateRatio(conventionalRewardRisk(item)), modelMode ? "theoretical-value" : ""),
    metric("Xác suất hòa vốn", estimateProbability(breakEvenWinProbability(item)), modelMode ? "theoretical-value" : ""),
    metric("Edge fair value sau phí", estimatedNumber(fairValueEdge(item)), modelMode ? "theoretical-value" : ""),
    metric(modelMode ? "Lỗ tối đa (mô hình)" : "Lỗ tối đa", estimatedNumber(item?.max_loss), modelMode ? "theoretical-value" : "negative"),
    metric(modelMode ? "Lãi tối đa (mô hình)" : "Lãi tối đa", estimatedNumber(item?.max_profit), modelMode ? "theoretical-value" : "positive"),
    metric("Điểm hòa vốn", (Array.isArray(item?.breakevens) ? item.breakevens : []).map((value) => number(value, 2)).join(", ") || "Không có dữ liệu"),
    metric("Evidence", evidenceStatusLabel(evidenceStatus(item))),
  );
  const historicalRate = historicalWinRate(item);
  if (historicalRate !== undefined) {
    detailMetrics.append(metric("Win rate lịch sử", estimateProbability(historicalRate)));
  }
  const contributionRatio = payoffContributionRatio(item);
  if (contributionRatio !== undefined) {
    detailMetrics.append(metric("Tỷ lệ đóng góp payoff", estimateRatio(contributionRatio)));
  }
  points.forEach((point) => {
    const row = document.createElement("tr");
    cell(row, number(point.underlyingPrice, 2));
    cell(row, number(point.pnl, 2), point.pnl >= 0 ? "positive" : "negative");
    scenarioResultsBody.appendChild(row);
  });
  const quoteAssumption = theoretical
    ? "Theoretical: premium vào lệnh dùng fair value. "
    : synthetic
    ? `Synthetic: spread giả định ${number(firstDefined(activeScanContext?.assumptions?.assumed_spread_bps, activeScanContext?.applied_filters?.assumed_spread_bps), 0)} bps. `
    : "";
  pnlChartAssumptions.textContent = `${quoteAssumption}Phương pháp / giả định API: ${methodologyNote(item)} Payoff, EV, xác suất mô hình và reward/risk đều là ước tính, không phải dự đoán hay lợi nhuận đảm bảo.`;
  if (points.length) {
    setScenarioState(`Hiển thị ${points.length} điểm payoff tại đáo hạn do API trả về.`);
  } else {
    setScenarioState("API chưa trả về payoff_curve cho cơ hội này; các giá trị không có được ghi rõ là không có dữ liệu.", "error");
  }
}

function showOpportunityDetail(item) {
  selectedOpportunity = item;
  detailPanel.hidden = false;
  appendTerminal(`[PAYOFF] Mở chi tiết cơ hội: ${item.symbol} (${strategyLabel(item.strategy)}) - Lỗ tối đa: ${number(item.max_loss)} | EV: ${number(item.expected_value)}`, "info");
  const legs = opportunityLegs(item);
  const strikes = legs.length > 1
    ? ` · K${legs.map((leg) => number(legStrike(leg), 2)).join(" / K")}`
    : "";
  detailSummary.textContent = `${item.asset || "—"} · ${opportunitySymbol(item)}${strikes} · ${strategyLabel(item.strategy)}`;
  scenarioResultsBody.replaceChildren();
  detailMetrics.replaceChildren();
  pnlChart.replaceChildren();
  pnlChartLegend.replaceChildren();
  pnlChartTooltip.hidden = true;
  pnlChartStatus.textContent = "Đang dựng biểu đồ";
  setScenarioState("Đang đọc payoff tại đáo hạn từ kết quả quét…");
  detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  renderPayoffDetail(item);
}

function renderAssets(payload) {
  assetList.replaceChildren();
  backtestAsset.replaceChildren();
  monitoringBaseCoin.replaceChildren();
  const assets = payload.assets || [];
  if (!assets.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "Không tìm thấy tài sản đang giao dịch.";
    assetList.appendChild(empty);
    backtestAsset.disabled = true;
    const allAssetsOption = document.createElement("option");
    allAssetsOption.value = "ALL";
    allAssetsOption.textContent = "Tất cả tài sản";
    monitoringBaseCoin.appendChild(allAssetsOption);
    return;
  }
  const preferredAsset = assets.find((asset) => asset.base_coin === "BTC") || assets[0];
  const allAssetsOption = document.createElement("option");
  allAssetsOption.value = "ALL";
  allAssetsOption.textContent = "Tất cả tài sản";
  monitoringBaseCoin.appendChild(allAssetsOption);
  assets.forEach((asset) => {
    const label = document.createElement("label");
    label.className = "asset-choice";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "assets";
    input.value = asset.base_coin;
    input.checked = asset === preferredAsset;
    label.append(input, document.createTextNode(`${asset.base_coin} (${asset.contract_count})`));
    assetList.appendChild(label);
    const option = document.createElement("option");
    option.value = asset.base_coin;
    option.textContent = `${asset.base_coin} (${asset.contract_count})`;
    option.selected = asset === preferredAsset;
    backtestAsset.appendChild(option);
    const monitoringOption = document.createElement("option");
    monitoringOption.value = asset.base_coin;
    monitoringOption.textContent = asset.base_coin;
    monitoringOption.selected = asset === preferredAsset;
    monitoringBaseCoin.appendChild(monitoringOption);
  });
  backtestAsset.disabled = false;
  return (payload.issues || []).length;
}

function updateBacktestExitFields() {
  const policy = backtestExitPolicy.value;
  backtestProfitField.hidden = policy !== "profit_target";
  backtestStopField.hidden = policy !== "stop_loss";
  backtestDteField.hidden = policy !== "min_dte";
}

function setBacktestState(message, className = "") {
  backtestState.textContent = message;
  backtestState.className = `state-message ${className}`.trim();
}

function renderBacktestResult(payload) {
  const report = payload.report || {};
  const holdout = report.holdout || {};
  const train = report.train || {};
  backtestTradesBody.replaceChildren();
  backtestMetrics.replaceChildren();
  const metrics = [
    ["Trades", holdout.trade_count ?? train.trade_count ?? 0],
    ["Net P&L holdout", number(holdout.net_pnl, 2)],
    ["EV / trade", number(holdout.expected_value, 2)],
    ["Max drawdown", number(holdout.max_drawdown, 2)],
  ];
  metrics.forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "metric";
    const caption = document.createElement("span");
    caption.className = "muted";
    caption.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    item.append(caption, strong);
    backtestMetrics.appendChild(item);
  });
  (payload.trades || []).forEach((trade) => {
    const row = document.createElement("tr");
    cell(row, new Date(trade.entry_time).toLocaleString("vi-VN"));
    cell(row, new Date(trade.exit_time).toLocaleString("vi-VN"));
    cell(row, strategyLabel(trade.strategy));
    cell(row, trade.exit_reason || "—");
    cell(row, number(trade.gross_pnl, 2), Number(trade.gross_pnl) >= 0 ? "positive" : "negative");
    cell(row, number(trade.net_pnl, 2), Number(trade.net_pnl) >= 0 ? "positive" : "negative");
    cell(row, `${number(trade.return_pct, 2)}%`, Number(trade.return_pct) >= 0 ? "positive" : "negative");
    backtestTradesBody.appendChild(row);
  });
  const quality = payload.data_quality || {};
  backtestQuality.textContent = `Engine: ${payload.engine || "snapshot_replay"} · ${quality.snapshot_count || 0} snapshots · ${quality.signal_evaluations || 0} lần đánh giá tín hiệu · Fill: ${quality.fill_model || "—"} · Look-ahead: ${quality.lookahead_free ? "đã kiểm soát" : "chưa xác minh"}`;
  backtestQuality.hidden = false;
  const unresolved = (payload.unresolved || []).length;
  setBacktestState(`Đã hoàn tất: ${(payload.trades || []).length} trade · train ${train.trade_count || 0} · holdout ${holdout.trade_count || 0}${unresolved ? ` · ${unresolved} tín hiệu chưa thể đóng` : ""}.`);
}

function setMonitoringState(message, className = "") {
  monitoringState.textContent = message;
  monitoringState.className = `state-message ${className}`.trim();
}

function monitoringDecisionLabel(action) {
  return {
    close: "CLOSE · Cần đóng thủ công",
    hold: "HOLD · Tiếp tục theo dõi",
    review: "REVIEW · Cần kiểm tra",
  }[String(action || "review").toLowerCase()] || "REVIEW · Cần kiểm tra";
}

function renderMonitoringResult(payload) {
  if (payload?.success === false) throw new Error(payload.error || "Không thể theo dõi vị thế");

  const report = payload?.payload || payload?.data || {};
  const positions = report.positions || [];
  const decisions = report.decisions || [];
  const positionBySymbol = new Map(positions.map((position) => [position.symbol, position]));
  const summary = report.summary || {};

  const selectedSymbol = monitoringSymbol.value;
  monitoringSymbol.replaceChildren();
  const allPositionsOption = document.createElement("option");
  allPositionsOption.value = "";
  allPositionsOption.textContent = "Tất cả vị thế · REVIEW nếu chưa có policy";
  monitoringSymbol.appendChild(allPositionsOption);
  [...new Set(positions.map((position) => position.symbol).filter(Boolean))].sort().forEach((symbol) => {
    const option = document.createElement("option");
    option.value = symbol;
    option.textContent = symbol;
    monitoringSymbol.appendChild(option);
  });
  monitoringSymbol.value = [...monitoringSymbol.options].some((option) => option.value === selectedSymbol)
    ? selectedSymbol
    : "";

  monitoringMetrics.replaceChildren();
  [
    ["Vị thế đang mở", positions.length],
    ["CLOSE", summary.close || 0],
    ["HOLD", summary.hold || 0],
    ["REVIEW", summary.review || 0],
    ["Reconciliation", report.reconciliation_status || "—"],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "metric";
    const caption = document.createElement("span");
    caption.className = "muted";
    caption.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    item.append(caption, strong);
    monitoringMetrics.appendChild(item);
  });

  monitoringDecisionsBody.replaceChildren();
  decisions.forEach((decision) => {
    const position = positionBySymbol.get(decision.symbol) || {};
    const row = document.createElement("tr");
    cell(row, decision.symbol || "—", "symbol");
    cell(row, position.side || "—");
    cell(row, number(position.quantity, 4));
    cell(row, `${number(position.avg_entry_price, 4)} / ${number(position.mark_price, 4)}`);
    cell(row, number(position.unrealized_pnl, 4), Number(position.unrealized_pnl) >= 0 ? "positive" : "negative");
    const actionCell = document.createElement("td");
    actionCell.className = `decision-${String(decision.action || "review").toLowerCase()}`;
    actionCell.textContent = monitoringDecisionLabel(decision.action);
    row.appendChild(actionCell);
    cell(row, (decision.reasons || []).join(" · ") || "—");
    monitoringDecisionsBody.appendChild(row);
  });

  monitoringEmptyState.hidden = decisions.length > 0;
  monitoringDecisionGuide.hidden = false;
  const issueText = (report.issues || []).length ? ` · Issues: ${report.issues.join("; ")}` : "";
  const persistenceText = payload.persistence?.status === "saved" ? " · Snapshot đã lưu" : "";
  setMonitoringState(
    `Đã cập nhật ${new Date(report.captured_at || Date.now()).toLocaleString("vi-VN")} · ${decisions.length} quyết định${issueText}${persistenceText}.`,
  );
}

function renderScanContext(context) {
  scanContext.replaceChildren();
  if (!context) {
    scanContext.hidden = true;
    return;
  }
  const views = {
    up: "Kỳ vọng tăng",
    down: "Kỳ vọng giảm",
    sideways: "Kỳ vọng đi ngang",
    custom: "Nhiều chiến lược",
  };
  const horizons = { "0_7": "0–7 ngày", "7_30": "7–30 ngày", "30_90": "30–90 ngày" };
  const strategies = (context.strategies || []).map(strategyLabel).join(", ");
  const theoretical = isTheoreticalMode(context.valuation_mode || activeScanValuationMode);
  const synthetic = isSyntheticMode(context.valuation_mode || activeScanValuationMode);
  const assumptions = context.assumptions || {};
  const appliedFilters = context.applied_filters || {};
  const maxLoss = theoretical
    ? "không dùng để khẳng định lỗ"
    : context.max_loss === null || context.max_loss === undefined
    ? "không giới hạn"
    : number(context.max_loss, 2);
  const edgeText = Number(appliedFilters.min_iv_edge) > 0
    ? ` · Edge IV tối thiểu: ${percent(appliedFilters.min_iv_edge)}`
    : "";
  const expectedValueText = theoretical
    ? " · EV: không tính"
    : appliedFilters.min_expected_value === null
    ? " · EV: không lọc"
    : ` · EV tối thiểu: ${number(appliedFilters.min_expected_value, 2)}`;
  const ignoredText = theoretical && context.ignored_filters?.length
    ? " · Bỏ qua: spread, edge sau phí, lỗ tối đa, EV"
    : "";
  const assumedSpreadBps = firstDefined(
    assumptions.assumed_spread_bps,
    appliedFilters.assumed_spread_bps,
  );
  const syntheticText = synthetic
    ? ` · Spread giả định: ${number(assumedSpreadBps, 0)} bps`
    : "";
  scanContext.textContent = `${context.summary || `Đã dùng: ${views[context.market_view] || "Tùy chỉnh"} · ${horizons[context.time_horizon] || "Thời hạn tùy chỉnh"}`} · Mode: ${valuationModeLabel(context.valuation_mode || activeScanValuationMode)} · Chiến lược: ${strategies || "mặc định"} · Lỗ tối đa: ${maxLoss}${theoretical ? "" : edgeText}${expectedValueText}${ignoredText}${syntheticText} · Lãi suất: ${percent(assumptions.risk_free_rate ?? context.risk_free_rate)} · Phí: ${number(assumptions.fee_per_contract, 2)} mỗi chiều · Trượt giá: ${number(assumptions.slippage_bps, 0)} bps`;
  scanContext.hidden = false;
}

function renderValuationModeNotice(mode) {
  if (!valuationModeNotice) return;
  valuationModeNotice.replaceChildren();
  if (!isModelValuationMode(mode)) {
    valuationModeNotice.hidden = true;
    return;
  }
  const title = document.createElement("strong");
  title.textContent = isSyntheticMode(mode)
    ? "Synthetic mode"
    : "Theoretical mode";
  const explanation = document.createElement("span");
  explanation.textContent = isSyntheticMode(mode)
    ? `Bid/ask được dựng quanh mark/fair value theo spread giả định ${number(firstDefined(activeScanContext?.assumptions?.assumed_spread_bps, activeScanContext?.applied_filters?.assumed_spread_bps), 0)} bps nên hệ thống tính premium, edge fair value, EV, xác suất mô hình, reward/risk và lỗ tối đa; các con số vẫn là ước tính, không phải giá khớp thật.`
    : "Bid/ask có thể thiếu hoặc bằng 0 nên kết quả dùng fair value mô hình làm giá vào; payoff, EV, xác suất mô hình, reward/risk và lỗ tối đa vẫn được ước tính nhưng không phải giá khớp, edge giao dịch hay cam kết lợi nhuận.";
  valuationModeNotice.append(title, explanation);
  valuationModeNotice.hidden = false;
}

function historicalContextStatus(context) {
  if (context.status === "available") return "đã có dữ liệu";
  if (context.status === "stale") return "đã có dữ liệu nhưng đã cũ";
  if (context.status === "fetch_error") return "lỗi tải dữ liệu";
  if (context.status === "unavailable") return "không có dữ liệu hợp lệ";
  return "chưa tải";
}

function renderHistoricalContext(contexts) {
  historicalContext.replaceChildren();
  const items = Array.isArray(contexts) ? contexts : [];
  if (!items.length) {
    historicalContext.hidden = true;
    return;
  }
  const details = document.createElement("div");
  details.className = "historical-context-items";
  items.forEach((context) => {
    const item = document.createElement("span");
    item.textContent = `${context.asset || "—"}: ${historicalContextStatus(context)}${context.historical_volatility == null ? "" : ` · HV30 ${percent(context.historical_volatility)}`}`;
    details.appendChild(item);
  });
  historicalContext.appendChild(details);
  historicalContext.hidden = false;
}

function renderScanRejections(rejections) {
  // Filtered candidate rejection logs are suppressed from UI to eliminate clutter.
}

async function getJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Accept": "application/json", ...(options.headers || {}) },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { error: { message: await response.text() } };
  if (!response.ok) throw new Error(payload?.error?.message || "Yêu cầu thất bại");
  return payload;
}

async function streamJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Accept": "application/x-ndjson", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    throw new Error(payload?.error?.message || `Yêu cầu thất bại (${response.status})`);
  }
  if (!response.body) throw new Error("Trình duyệt không hỗ trợ stream log của scan");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;

  function handleLine(line) {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "log") {
      let className = "info";
      if (event.message?.includes("ERROR")) className = "error";
      else if (event.message?.includes("WARN")) className = "warn";
      else if (event.message?.includes("SUCCESS") || event.message?.includes("completed")) className = "success";
      appendTerminal(event.message, className);
    } else if (event.type === "result") {
      result = event.payload;
    } else if (event.type === "error") {
      throw new Error(event.message || "Opportunity scan failed");
    }
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    lines.forEach(handleLine);
    if (done) break;
  }
  handleLine(buffer);
  if (!result) throw new Error("Scan stream ended before returning a result");
  return result;
}

function optionalNumber(formData, name) {
  const value = formData.get(name);
  return value === "" || value === null ? null : Number(value);
}

function optionalDecimal(formData, name, divisor = 1) {
  const value = optionalNumber(formData, name);
  return value === null ? null : value / divisor;
}

function selectedTimeHorizon(value) {
  const ranges = {
    "0-7": { min_dte: 0, max_dte: 7 },
    "7-30": { min_dte: 7, max_dte: 30 },
    "30-90": { min_dte: 30, max_dte: 90 },
    "90-plus": { min_dte: 90, max_dte: null },
    all: { min_dte: null, max_dte: null },
  };
  return ranges[value] || ranges.all;
}

function selectedStrategies(formData) {
  return [...new Set(
    formData.getAll("strategies").flatMap((strategy) => (
      STRATEGY_GROUPS[strategy] || [strategy]
    )),
  )];
}

function simpleScanContext(strategy, horizon) {
  const strategies = {
    long_call: { market_view: "up", strategy_preference: "long_call" },
    long_put: { market_view: "down", strategy_preference: "long_put" },
    bull_call_vertical: { market_view: "up", strategy_preference: "bull_call_vertical" },
    bear_put_vertical: { market_view: "down", strategy_preference: "bear_put_vertical" },
    iron_condor: { market_view: "sideways", strategy_preference: "iron_condor" },
  };
  const horizons = { "0-7": "0_7", "7-30": "7_30", "30-90": "30_90" };
  return {
    ...(strategies[strategy] || strategies.long_call),
    time_horizon: horizons[horizon] || "7_30",
  };
}

function scanPayloadFromForm() {
  const data = new FormData(form);
  const advancedFilters = document.querySelector("#advanced-filters");
  const useAdvancedFilters = Boolean(advancedFilters?.open);
  const strategies = selectedStrategies(data);
  const assets = data.getAll("assets");
  const valuationMode = data.get("valuation_mode") || "executable";
  if (!assets.length) return { error: "Hãy chọn ít nhất một tài sản để quét." };
  if (!strategies.length) return { error: "Hãy chọn ít nhất một chiến lược để quét." };

  const horizon = selectedTimeHorizon(data.get("time_horizon"));
  const maxLoss = useAdvancedFilters
    ? optionalNumber(data, "max_loss")
    : optionalNumber(data, "quick_max_loss");
  if (maxLoss !== null && maxLoss < 0) {
    return { error: "Mức lỗ tối đa không được âm." };
  }

  const payload = {
    valuation_mode: valuationMode,
    risk_free_rate: useAdvancedFilters
      ? optionalDecimal(data, "risk_free_rate_pct", 100) ?? 0.05
      : 0.05,
    assets,
    strategies,
    min_dte: useAdvancedFilters ? optionalNumber(data, "min_dte") : horizon.min_dte,
    max_dte: useAdvancedFilters ? optionalNumber(data, "max_dte") : horizon.max_dte,
    min_iv_edge: useAdvancedFilters
      ? optionalDecimal(data, "min_iv_edge", 100) || 0
      : 0,
    max_loss: maxLoss,
    assumed_spread_bps: optionalNumber(data, "assumed_spread_bps") ?? 100,
    include_unvalidated: true,
  };
  if (!useAdvancedFilters) {
    Object.assign(payload, {
      market_view: "custom",
      time_horizon: { "0-7": "0_7", "7-30": "7_30", "30-90": "30_90" }[data.get("time_horizon")] || "7_30",
    });
  }
  if (useAdvancedFilters) {
    Object.assign(payload, {
      min_delta: optionalNumber(data, "min_delta"),
      max_delta: optionalNumber(data, "max_delta"),
      min_moneyness: optionalNumber(data, "min_moneyness"),
      max_moneyness: optionalNumber(data, "max_moneyness"),
      min_volume_24h: Number(data.get("min_volume_24h")),
      min_open_interest: Number(data.get("min_open_interest")),
      max_spread_pct: optionalDecimal(data, "max_spread_pct", 100),
      min_edge_after_costs: Number(data.get("min_edge_after_costs")),
      min_expected_value: optionalNumber(data, "min_expected_value"),
      max_results: optionalNumber(data, "max_results"),
      fee_per_contract: Number(data.get("fee_per_contract")),
      slippage_bps: Number(data.get("slippage_bps")),
      assumed_spread_bps: optionalNumber(data, "assumed_spread_bps") ?? 100,
      quantity: Number(data.get("quantity")),
      contract_multiplier: Number(data.get("contract_multiplier")),
    });
  }
  return { payload };
}

function liveCompactNumber(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  if (Math.abs(amount) >= 1_000_000) return `${(amount / 1_000_000).toFixed(1)}m`;
  if (Math.abs(amount) >= 1_000) return `${(amount / 1_000).toFixed(1)}k`;
  return amount.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function liveEdgePercent(item) {
  const edge = Number(firstDefined(item?.edge_pct, item?.iv_edge));
  return Number.isFinite(edge) ? edge : null;
}

function liveConnectionState(state, label) {
  if (!liveConnection) return;
  liveConnection.className = `live-connection live-connection-${state}`;
  liveConnectionLabel.textContent = label;
  liveSessionState.textContent = state === "live" ? "LIVE" : state === "connecting" ? "SYNC" : state === "stale" ? "STALE" : "WAITING";
  liveToggle.textContent = state === "live" || state === "connecting" ? "Dừng live feed" : state === "stale" ? "Kết nối lại" : "Bật live feed";
}

function renderMarketStrip(payload) {
  marketStrip.replaceChildren();
  const opportunities = Array.isArray(payload.opportunities) ? payload.opportunities : [];
  const selectedAssets = [...form.querySelectorAll('input[name="assets"]:checked')].map((input) => input.value);
  const assets = [...new Set([...selectedAssets, ...opportunities.map((item) => item.asset).filter(Boolean)])];
  const grouped = new Map();
  opportunities.forEach((item) => {
    const key = item.asset || "—";
    const current = grouped.get(key) || [];
    current.push(item);
    grouped.set(key, current);
  });
  if (!assets.length) {
    const empty = document.createElement("div");
    empty.className = "market-strip-empty";
    empty.textContent = "Chọn tài sản trong bộ lọc scanner để xem ticker live.";
    marketStrip.appendChild(empty);
    return;
  }
  assets.forEach((asset) => {
    const items = grouped.get(asset) || [];
    const first = items[0];
    const card = document.createElement("div");
    card.className = "market-card";
    const heading = document.createElement("div");
    heading.className = "market-card-heading";
    const name = document.createElement("strong");
    name.textContent = asset;
    const dot = document.createElement("span");
    dot.className = items.length ? "market-card-dot" : "market-card-dot market-card-dot-muted";
    dot.setAttribute("aria-hidden", "true");
    heading.append(name, dot);
    card.appendChild(heading);
    const spot = document.createElement("strong");
    spot.className = "market-card-price";
    spot.textContent = first ? liveCompactNumber(first.spot_price) : "—";
    card.appendChild(spot);
    const detail = document.createElement("span");
    detail.className = "market-card-detail";
    detail.textContent = items.length ? `${items.length} signal${items.length > 1 ? "s" : ""} · ${strategyLabel(first.strategy)}` : "Chưa có signal";
    card.appendChild(detail);
    marketStrip.appendChild(card);
  });
}

function renderSignalChart(opportunities) {
  signalChart.replaceChildren();
  if (!opportunities.length) {
    const empty = document.createElement("div");
    empty.className = "signal-chart-empty";
    empty.textContent = "Không có cơ hội đạt điều kiện hiện tại.";
    signalChart.appendChild(empty);
    liveSignalStatus.textContent = "Không có signal";
    return;
  }
  const ranked = opportunities
    .map((item) => ({ item, value: liveEdgePercent(item) }))
    .filter((entry) => entry.value !== null)
    .sort((left, right) => right.value - left.value)
    .slice(0, 8);
  const maxValue = Math.max(...ranked.map((entry) => Math.abs(entry.value)), 0.01);
  ranked.forEach(({ item, value }, index) => {
    const column = document.createElement("div");
    column.className = "signal-column";
    const valueLabel = document.createElement("span");
    valueLabel.className = "signal-value";
    valueLabel.textContent = `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
    const track = document.createElement("div");
    track.className = "signal-track";
    const bar = document.createElement("span");
    bar.className = value >= 0 ? "signal-bar" : "signal-bar signal-bar-negative";
    bar.style.height = `${Math.max(12, Math.abs(value) / maxValue * 100)}%`;
    track.appendChild(bar);
    const label = document.createElement("span");
    label.className = "signal-label";
    label.textContent = `${index + 1} · ${item.asset || "—"}`;
    column.append(valueLabel, track, label);
    signalChart.appendChild(column);
  });
  liveSignalStatus.textContent = `${opportunities.length} signal${opportunities.length > 1 ? "s" : ""} · top ${ranked.length}`;
}

function renderLiveOpportunityBoard(opportunities) {
  liveOpportunityBody.replaceChildren();
  const ranked = [...opportunities]
    .sort((left, right) => (liveEdgePercent(right) || 0) - (liveEdgePercent(left) || 0))
    .slice(0, 8);
  if (!ranked.length) {
    const row = document.createElement("tr");
    const empty = document.createElement("td");
    empty.className = "live-board-empty";
    empty.colSpan = 6;
    empty.textContent = "Snapshot đã nhận nhưng chưa có signal phù hợp.";
    row.appendChild(empty);
    liveOpportunityBody.appendChild(row);
    return;
  }
  ranked.forEach((item) => {
    const row = document.createElement("tr");
    const instrument = document.createElement("td");
    instrument.className = "live-board-instrument";
    const asset = document.createElement("strong");
    asset.textContent = item.asset || "—";
    const symbol = document.createElement("span");
    symbol.textContent = opportunitySymbol(item);
    instrument.append(asset, symbol);
    row.appendChild(instrument);
    cell(row, strategyLabel(item.strategy));
    const edge = liveEdgePercent(item);
    cell(row, edge === null ? "—" : `${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(2)}%`, edge === null || edge < 0 ? "negative" : "positive");
    cell(row, Number.isFinite(Number(item.dte)) ? `${Math.round(Number(item.dte))}d` : "—");
    cell(row, liveCompactNumber(firstDefined(item.estimated_entry, item.market_mid)));
    const action = document.createElement("td");
    const detailButton = document.createElement("button");
    detailButton.type = "button";
    detailButton.className = "live-board-detail";
    detailButton.textContent = "Payoff";
    detailButton.addEventListener("click", () => showOpportunityDetail(item));
    action.appendChild(detailButton);
    row.appendChild(action);
    liveOpportunityBody.appendChild(row);
  });
}

function renderLiveFeed(payload) {
  liveFeed.replaceChildren();
  const opportunities = [...(payload.opportunities || [])]
    .sort((left, right) => (liveEdgePercent(right) || 0) - (liveEdgePercent(left) || 0))
    .slice(0, 6);
  if (!opportunities.length) {
    const empty = document.createElement("div");
    empty.className = "live-feed-empty";
    empty.textContent = "Snapshot đã nhận nhưng chưa có signal phù hợp.";
    liveFeed.appendChild(empty);
    return;
  }
  opportunities.forEach((item, index) => {
    const event = document.createElement("div");
    event.className = "live-event";
    const indexLabel = document.createElement("span");
    indexLabel.className = "live-event-index";
    indexLabel.textContent = String(index + 1).padStart(2, "0");
    const copy = document.createElement("div");
    copy.className = "live-event-copy";
    const title = document.createElement("strong");
    title.textContent = `${item.asset || "—"} · ${strategyLabel(item.strategy)}`;
    const symbol = document.createElement("span");
    symbol.textContent = opportunitySymbol(item);
    copy.append(title, symbol);
    const edge = document.createElement("strong");
    edge.className = liveEdgePercent(item) >= 0 ? "live-event-edge positive" : "live-event-edge negative";
    const edgeValue = liveEdgePercent(item);
    edge.textContent = edgeValue === null ? "—" : `${edgeValue >= 0 ? "+" : ""}${(edgeValue * 100).toFixed(2)}%`;
    event.append(indexLabel, copy, edge);
    liveFeed.appendChild(event);
  });
}

function renderLiveSnapshot(payload) {
  const opportunities = Array.isArray(payload.opportunities) ? payload.opportunities : [];
  const first = opportunities[0];
  const edgeValues = opportunities.map(liveEdgePercent).filter((value) => value !== null);
  const dtes = opportunities.map((item) => Number(item.dte)).filter(Number.isFinite);
  liveUpdateCount += 1;
  liveUpdateCountLabel.textContent = `${liveUpdateCount} cập nhật`;
  liveLastUpdate.textContent = `Cập nhật ${new Date(payload.data_timestamp || payload.timestamp || Date.now()).toLocaleTimeString("vi-VN")}`;
  liveNextRefresh.textContent = "Snapshot mới mỗi 8 giây · quote server-side";
  liveStatSpot.textContent = first ? liveCompactNumber(first.spot_price) : "—";
  liveStatSpotLabel.textContent = first ? `${first.asset || "Underlying"} · ${first.quote_timestamp ? "quote nhận được" : "quote model"}` : "Chưa có quote phù hợp";
  liveStatOpportunities.textContent = String(opportunities.length);
  liveStatOpportunitiesLabel.textContent = opportunities.length ? "Đang đạt bộ lọc" : "Không có signal phù hợp";
  liveStatEdge.textContent = edgeValues.length ? `${(edgeValues.reduce((sum, value) => sum + value, 0) / edgeValues.length * 100).toFixed(2)}%` : "—";
  liveStatDte.textContent = dtes.length ? `${Math.round(Math.min(...dtes))}d` : "—";
  renderMarketStrip(payload);
  renderLiveOpportunityBoard(opportunities);
  renderSignalChart(opportunities);
  renderLiveFeed(payload);
  liveConnectionState("live", `Live feed · ${opportunities.length} signal`);
  serviceStatus.classList.remove("error");
  serviceStatus.textContent = "Live stream đang hoạt động";
}

function scheduleLiveReconnect() {
  if (!liveFeedWanted || liveReconnectTimer) return;
  liveReconnectTimer = window.setTimeout(() => {
    liveReconnectTimer = null;
    if (liveFeedWanted && liveScanRequest) connectLiveFeed(liveScanRequest, true);
  }, 1800);
  liveNextRefresh.textContent = "Đang thử kết nối lại…";
}

function connectLiveFeed(request, isReconnect = false) {
  if (liveReconnectTimer) {
    window.clearTimeout(liveReconnectTimer);
    liveReconnectTimer = null;
  }
  if (liveScanSocket) liveScanSocket.close();
  liveFeedWanted = true;
  liveScanRequest = request;
  liveUpdateCount = isReconnect ? liveUpdateCount : 0;
  liveConnectionState("connecting", isReconnect ? "Đang reconnect live feed…" : "Đang kết nối live feed…");
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/api/v1/opportunities/stream`);
  liveScanSocket = socket;
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify(request));
    liveNextRefresh.textContent = "Đã mở kênh · chờ snapshot đầu tiên";
    appendTerminal("[LIVE] Đã kết nối WebSocket /api/v1/opportunities/stream thành công.", "info");
  });
  socket.addEventListener("message", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (_error) {
      appendTerminal("[LIVE] Nhận event không hợp lệ.", "error");
      return;
    }
    if (payload.type === "snapshot") {
      renderLiveSnapshot(payload.payload || {});
      appendTerminal(`[LIVE] Đã nhận snapshot: ${payload.payload?.opportunities?.length || 0} cơ hội đạt chuẩn.`, "success");
      return;
    }
    if (payload.type === "log") {
      const rawMsg = payload.message || "Đang cập nhật…";
      let className = "info";
      if (rawMsg.includes("ERROR") || rawMsg.includes("LỖI")) className = "error";
      else if (rawMsg.includes("WARN")) className = "warn";
      else if (rawMsg.includes("SUCCESS") || rawMsg.includes("hoàn tất") || rawMsg.includes("completed")) className = "success";
      const formatted = rawMsg.startsWith("[LIVE]") ? rawMsg : `[LIVE] ${rawMsg}`;
      appendTerminal(formatted, className);
      return;
    }
    if (payload.type === "error") {
      liveConnectionState("error", payload.message || "Live feed gặp lỗi");
      serviceStatus.textContent = "Live stream gặp lỗi";
      serviceStatus.classList.add("error");
      appendTerminal(`[LIVE] LỖI: ${payload.message || "Live feed gặp lỗi"}`, "error");
      return;
    }
    if (payload.status === "starting") {
      liveConnectionState("connecting", "Đang dựng snapshot live…");
      appendTerminal("[LIVE] Trạng thái: starting (khởi tạo luồng quét)...", "info");
    }
    if (payload.status === "connected" && liveScanSocket === socket && liveUpdateCount === 0) {
      liveConnectionState("connecting", "Đã kết nối · đang chờ dữ liệu");
      appendTerminal("[LIVE] Trạng thái: connected (kênh sẵn sàng).", "info");
    }
  });
  socket.addEventListener("error", () => {
    if (liveScanSocket !== socket) return;
    liveConnectionState("stale", "Không kết nối được · đang thử lại");
    serviceStatus.textContent = "Live stream không sẵn sàng";
    serviceStatus.classList.add("error");
    appendTerminal("[LIVE] Lỗi kết nối WebSocket tới live desk stream.", "error");
  });
  socket.addEventListener("close", () => {
    if (liveScanSocket !== socket) return;
    liveScanSocket = null;
    if (liveFeedWanted) {
      liveConnectionState("stale", "Stream bị ngắt · đang thử lại");
      appendTerminal("[LIVE] WebSocket bị ngắt kết nối · chuẩn bị reconnect…", "warn");
      scheduleLiveReconnect();
    } else {
      liveConnectionState("idle", "Live feed đang tắt");
      appendTerminal("[LIVE] Đã đóng WebSocket live feed an toàn.");
    }
  });
}

function stopLiveFeed() {
  liveFeedWanted = false;
  liveScanRequest = null;
  if (liveReconnectTimer) {
    window.clearTimeout(liveReconnectTimer);
    liveReconnectTimer = null;
  }
  if (liveScanSocket) {
    liveScanSocket.close();
    liveScanSocket = null;
  }
  liveConnectionState("idle", "Live feed đang tắt");
  liveNextRefresh.textContent = "Chờ kết nối stream";
  serviceStatus.classList.remove("error");
  serviceStatus.textContent = "API đang hoạt động";
}

function renderResults(payload) {
  activeScanValuationMode = payload.valuation_mode || payload.scan_context?.valuation_mode || "executable";
  activeScanContext = payload.scan_context || null;
  if (resultsBody) resultsBody.replaceChildren();
  secondaryResults.replaceChildren();
  opportunityExplanations.replaceChildren();
  renderScanContext(payload.scan_context);
  renderValuationModeNotice(activeScanValuationMode);
  renderHistoricalContext(payload.historical_volatility_contexts);
  detailPanel.hidden = true;
  selectedOpportunity = null;
  const opportunities = payload.opportunities || [];
  if (resultsGuide) {
    resultsGuide.hidden = !opportunities.length;
    const guide = resultsGuide.querySelector("span");
    if (guide) {
      guide.textContent = isSyntheticMode(activeScanValuationMode)
        ? "Các dòng dưới đây dùng bid/ask tổng hợp từ mark/fair value và spread giả định. Edge fair value, EV, xác suất mô hình và reward/risk vẫn là ước tính, không phải khả năng khớp lệnh."
        : isTheoreticalMode(activeScanValuationMode)
        ? "Các dòng dưới đây là fair value/IV/Greeks và payoff từ mô hình. Bid/ask thiếu không được thay bằng giá giả; EV, xác suất mô hình và reward/risk chỉ là ước tính, còn edge giao dịch và khả năng khớp không được suy ra."
        : "Hãy bắt đầu từ phần diễn giải: hướng kỳ vọng, chân mua/bán, lỗ tối đa và vùng có lợi. Xác suất mô hình và edge fair value chỉ là tham chiếu, không phải lợi nhuận đảm bảo.";
    }
  }
  if (resultsTableWrap) {
    resultsTableWrap.hidden = true;
  }
  if (!opportunities.length) setState("Không có cơ hội đạt đủ điều kiện hiện tại.");
  else setState(`${opportunities.length} cơ hội đạt điều kiện.`);
  opportunities.forEach((item, index) => {
    opportunityExplanations.appendChild(renderOpportunityExplanation(item, index));
  });
  (payload.asset_failures || []).forEach((failure) => {
    const item = document.createElement("div");
    item.textContent = `Không tải được ${failure.asset}: ${failure.message}`;
    item.className = "error";
    secondaryResults.appendChild(item);
  });
  dataStatus.textContent = payload.data_timestamp ? `Dữ liệu: ${new Date(payload.data_timestamp).toLocaleString("vi-VN")}` : "Đã nhận dữ liệu";
}

async function loadAssets() {
  appendTerminal("[INIT] Đang kết nối backend và tải danh sách tài sản từ Bybit…", "info");
  try {
    const payload = await getJson("/api/v1/assets");
    renderAssets(payload);
    serviceStatus.textContent = "API đang hoạt động";
    appendTerminal(`[INIT] Đã kết nối thành công: tải được ${payload.assets?.length || 0} tài sản (${payload.assets?.map((a) => a.base_coin).join(", ") || "none"}).`, "success");
  } catch (error) {
    serviceStatus.textContent = "API không sẵn sàng";
    serviceStatus.classList.add("error");
    setState(error.message, "error");
    appendTerminal(`[INIT] LỖI: ${error.message}`, "error");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  if (liveDesk.isWanted()) liveDesk.stop();
  const scanInput = scanPayloadFromForm();
  if (scanInput.error) {
    setState(scanInput.error, "error");
    appendTerminal(`[QUÉT] LỖI FORM: ${scanInput.error}`, "error");
    return;
  }
  const payload = scanInput.payload;
  button.disabled = true;
  clearTerminal();
  appendTerminal("[QUÉT] Bắt đầu quét cơ hội options…", "info");
  appendTerminal(`[QUÉT] Bộ lọc: Tài sản=${payload.assets?.length ? payload.assets.join(",") : "Tất cả"} | Chiến lược=${(payload.strategies || []).join(",")} | Chế độ=${payload.valuation_mode || "executable"}`, "info");
  setState("Đang lấy dữ liệu và dựng bề mặt biến động…");
  try {
    const scanData = await streamJson("/api/v1/opportunities/scan/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderResults(scanData);
    appendTerminal(`[QUÉT] Nhận kết quả thành công: ${scanData.opportunities?.length || 0} cơ hội đạt điều kiện.`, "success");
  } catch (error) {
    setState(error.message, "error");
    appendTerminal(`LỖI: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
});

liveToggle.addEventListener("click", () => {
  if (liveDesk.isWanted()) {
    if (liveDesk.canRetry()) {
      liveDesk.reconnect();
      return;
    }
    liveDesk.stop();
    appendTerminal("[LIVE] Đã dừng live feed. Không có lệnh nào được gửi.");
    return;
  }
  const scanInput = scanPayloadFromForm();
  if (scanInput.error) {
    setState(scanInput.error, "error");
    appendTerminal(`[LIVE] ${scanInput.error}`, "error");
    return;
  }
  appendTerminal("[LIVE] Mở live feed cho bộ lọc hiện tại…");
  liveDesk.connect(scanInput.payload);
});

backtestExitPolicy.addEventListener("change", updateBacktestExitFields);
updateBacktestExitFields();

monitoringForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(monitoringForm);
  const request = monitoringRequest(data);
  const requestKey = JSON.stringify(request);
  if (monitoringSocket && monitoringSocket.readyState <= 1) {
    if (requestKey === monitoringRequestKey) {
      monitoringSocket.close();
      monitoringSocket = null;
      monitoringRequestKey = null;
      document.querySelector("#monitoring-submit").textContent = "Cập nhật theo dõi";
      setMonitoringState("Đã dừng live monitoring.");
      return;
    }
    monitoringSocket.close();
    monitoringSocket = null;
  }
  connectMonitoringStream(request, requestKey);
});

function monitoringRequest(formData) {
  const baseCoin = String(formData.get("base_coin") || "").trim().toUpperCase();
  const symbol = String(formData.get("symbol") || "").trim();
  const profile = formData.get("policy_profile");
  const profileHours = { day_trade: 24, swing: 24 * 7 };
  const maxHoldingHours = optionalNumber(formData, "max_holding_hours") ?? profileHours[profile];
  const stopLoss = optionalNumber(formData, "stop_loss_price");
  const takeProfit = optionalNumber(formData, "take_profit_price");
  const thesisStatus = formData.get("thesis_status") || "unknown";
  const hasPolicy = symbol && (
    profile !== "review" ||
    stopLoss !== null ||
    takeProfit !== null ||
    maxHoldingHours !== null ||
    thesisStatus === "invalid"
  );
  return {
    base_coin: baseCoin || "ALL",
    position_type: formData.get("position_type") || "all",
    policies: hasPolicy ? [{
      symbol,
      thesis_status: thesisStatus,
      stop_loss_price: stopLoss,
      take_profit_price: takeProfit,
      max_holding_hours: maxHoldingHours ?? null,
    }] : [],
    persist: true,
  };
}

function connectMonitoringStream(request, requestKey = JSON.stringify(request)) {
  const button = document.querySelector("#monitoring-submit");
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/api/v1/positions/stream`);
  monitoringSocket = socket;
  monitoringRequestKey = requestKey;
  button.textContent = "Đang kết nối…";
  setMonitoringState("Đang kết nối live monitoring ở chế độ read-only…");
  appendTerminal(`[MONITOR] Khởi tạo kết nối theo dõi vị thế cho tài sản ${request.base_coin || "ALL"} (read-only)…`, "info");

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify(request));
    button.textContent = "Dừng live";
    appendTerminal("[MONITOR] Đã mở WebSocket /api/v1/positions/stream thành công.", "success");
  });
  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "snapshot") {
      renderMonitoringResult(payload);
      appendTerminal(`[MONITOR] Nhận snapshot vị thế: ${payload.positions?.length || 0} vị thế, Quyết định: CLOSE=${payload.summary?.close || 0}, HOLD=${payload.summary?.hold || 0}, REVIEW=${payload.summary?.review || 0}.`, "success");
      return;
    }
    if (payload.type === "error") {
      setMonitoringState(payload.message || "Live monitoring gặp lỗi.", "error");
      appendTerminal(`[MONITOR] LỖI: ${payload.message || "Live monitoring gặp lỗi"}`, "error");
      return;
    }
    const statusMessages = {
      starting: "Đang khởi tạo live monitoring…",
      connected: "Đã kết nối Bybit private stream; đang nhận cập nhật live…",
      reconciled: "Đã reconnect và reconcile lại với REST; tiếp tục nhận cập nhật live.",
      disconnected: "Mất kết nối Bybit; đang thử reconnect…",
    };
    if (payload.status && statusMessages[payload.status]) {
      setMonitoringState(statusMessages[payload.status]);
      appendTerminal(`[MONITOR] Trạng thái Bybit: ${statusMessages[payload.status]}`, "info");
    }
  });
  socket.addEventListener("error", () => {
    setMonitoringState("Không thể kết nối live monitoring. Kiểm tra credential và server.", "error");
    appendTerminal("[MONITOR] Lỗi kết nối WebSocket live monitoring.", "error");
  });
  socket.addEventListener("close", () => {
    if (monitoringSocket !== socket) return;
    monitoringSocket = null;
    monitoringRequestKey = null;
    button.textContent = "Cập nhật theo dõi";
    appendTerminal("[MONITOR] Đã đóng kết nối live monitoring.", "info");
  });
}

backtestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(backtestForm);
  if (!backtestAsset.value) {
    setBacktestState("Chưa có tài sản để backtest.", "error");
    return;
  }
  const start = new Date(data.get("start_time"));
  const end = new Date(data.get("end_time"));
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start >= end) {
    setBacktestState("Hãy chọn khoảng thời gian hợp lệ.", "error");
    return;
  }
  const policy = data.get("exit_policy");
  const payload = {
    assets: [backtestAsset.value],
    start_time: start.toISOString(),
    end_time: end.toISOString(),
    filters: {
      strategies: [data.get("strategy")],
      fee_per_contract: Number(data.get("fee_per_contract")),
      slippage_bps: Number(data.get("slippage_bps")),
      quantity: 1,
      contract_multiplier: 1,
      include_unvalidated: true,
    },
    exit_policy: {
      type: policy,
      profit_target_pct: Number(data.get("profit_target_pct")),
      stop_loss_pct: Number(data.get("stop_loss_pct")),
      min_dte: Number(data.get("min_dte_exit")),
    },
    signal_interval_minutes: Number(data.get("signal_interval_minutes")),
  };
  const button = document.querySelector("#backtest-submit");
  button.disabled = true;
  setBacktestState("Đang replay tín hiệu và kiểm tra quy tắc đóng lệnh…");
  appendTerminal(`[BACKTEST] Bắt đầu backtest: Tài sản=${payload.assets.join(",")} | Chiến lược=${payload.filters.strategies.join(",")} | Từ=${payload.start_time} Đến=${payload.end_time} | Exit=${payload.exit_policy.type}`, "info");
  appendTerminal("[BACKTEST] Đang nạp snapshot lịch sử và replay tín hiệu theo exit policy…", "info");
  try {
    const backtestResult = await getJson("/api/v1/backtests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderBacktestResult(backtestResult);
    appendTerminal(`[BACKTEST] Hoàn tất: ${backtestResult.total_trades || 0} giao dịch, Win rate: ${((backtestResult.win_rate || 0) * 100).toFixed(1)}%, P&L: ${number(backtestResult.total_pnl)} USDT.`, "success");
  } catch (error) {
    setBacktestState(error.message, "error");
    backtestQuality.hidden = true;
    appendTerminal(`LỖI BACKTEST: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
});
// ==========================================
// Strategy Builder & Trade Notebook Engine
// ==========================================

function initStrategyBuilder() {
  if (builderState.initialized) return;
  builderState.initialized = true;

  if (builderAssetSelect) {
    builderAssetSelect.addEventListener("change", () => {
      builderState.asset = builderAssetSelect.value;
      builderState.expiry = "";
      builderState.legs = [];
      loadBuilderOptionChain(builderState.asset);
    });
  }

  if (builderExpirySelect) {
    builderExpirySelect.addEventListener("change", () => {
      builderState.expiry = builderExpirySelect.value;
      if (builderState.chainData) {
        renderBuilderChain(builderState.chainData, builderState.expiry);
      }
      if (builderState.activePreset && builderState.activePreset !== "custom") {
        applyBuilderPreset(builderState.activePreset);
      }
    });
  }

  if (builderPresetButtons) {
    builderPresetButtons.querySelectorAll(".preset-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        builderPresetButtons.querySelectorAll(".preset-chip").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        const preset = btn.dataset.preset;
        builderState.activePreset = preset;
        applyBuilderPreset(preset);
      });
    });
  }

  if (builderAddLegBtn) {
    builderAddLegBtn.addEventListener("click", () => {
      const now = new Date();
      now.setDate(now.getDate() + 14);
      const defaultExp = builderState.expiry || now.toISOString().split("T")[0];
      const defaultStrike = builderState.spot > 0 ? Math.round(builderState.spot) : 60000;
      builderState.legs.push({
        option_type: "call",
        strike: defaultStrike,
        expiry: defaultExp,
        iv: 0.65,
        spot: builderState.spot || defaultStrike,
        position: 1,
        quantity: 1,
        mid_price: 1000,
        bid: 980,
        ask: 1020,
        symbol: `${builderState.asset}-${defaultExp}-${defaultStrike}-C`,
      });
      renderBuilderLegs();
      evaluateBuilder();
    });
  }

  if (builderClearLegsBtn) {
    builderClearLegsBtn.addEventListener("click", () => {
      builderState.legs = [];
      renderBuilderLegs();
      evaluateBuilder();
    });
  }

  if (builderEvaluateBtn) {
    builderEvaluateBtn.addEventListener("click", evaluateBuilder);
  }

  if (builderSaveNotebookBtn) {
    builderSaveNotebookBtn.addEventListener("click", saveBuilderToNotebook);
  }

  loadBuilderOptionChain(builderState.asset || "BTC");
}

async function loadBuilderOptionChain(asset) {
  if (builderChainStatus) {
    builderChainStatus.textContent = `Đang tải chuỗi ${asset}...`;
  }
  try {
    const data = await getJson(`/api/v1/options/chain/${asset}`);
    builderState.chainData = data;
    builderState.spot = data.spot || 0;
    if (builderSpotDisplay) {
      builderSpotDisplay.textContent = `$${number(data.spot, 2)}`;
    }

    if (builderExpirySelect) {
      builderExpirySelect.replaceChildren();
      (data.expiries || []).forEach((exp) => {
        const opt = document.createElement("option");
        opt.value = exp;
        opt.textContent = exp;
        builderExpirySelect.appendChild(opt);
      });
      if (data.expiries && data.expiries.length) {
        if (!builderState.expiry || !data.expiries.includes(builderState.expiry)) {
          builderState.expiry = data.expiries[0];
        }
        builderExpirySelect.value = builderState.expiry;
      } else {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Không có kỳ hạn nào";
        builderExpirySelect.appendChild(opt);
      }
    }

    if (builderChainStatus) {
      builderChainStatus.textContent = `${data.contracts?.length || 0} hợp đồng`;
    }

    renderBuilderChain(data, builderState.expiry);

    if (builderState.legs.length === 0) {
      applyBuilderPreset(builderState.activePreset || "bull_call_vertical");
    }
  } catch (err) {
    if (builderChainStatus) {
      builderChainStatus.textContent = `Không tải được: ${err.message}`;
    }
    appendTerminal(`[BUILDER] Lỗi tải chuỗi options: ${err.message}`, "error");
  }
}

function renderBuilderChain(chainData, selectedExpiry) {
  if (!builderChainTbody) return;
  builderChainTbody.replaceChildren();

  const contracts = (chainData.contracts || []).filter((c) => !selectedExpiry || c.expiry?.startsWith(selectedExpiry) || c.symbol?.includes(selectedExpiry));
  const strikeMap = new Map();
  contracts.forEach((c) => {
    const s = Number(c.strike);
    if (!strikeMap.has(s)) {
      strikeMap.set(s, { call: null, put: null });
    }
    const optType = String(c.option_type || "").toLowerCase();
    if (optType === "call") strikeMap.get(s).call = c;
    else if (optType === "put") strikeMap.get(s).put = c;
  });

  const strikes = [...strikeMap.keys()].sort((a, b) => a - b);
  const currentSpot = builderState.spot || 0;

  strikes.forEach((strike) => {
    const pair = strikeMap.get(strike);
    const tr = document.createElement("tr");

    // Call Action cell
    const tdCallAction = document.createElement("td");
    if (pair.call) {
      const btnBuy = document.createElement("button");
      btnBuy.type = "button";
      btnBuy.className = "btn-chain-action btn-buy";
      btnBuy.textContent = "+ Mua";
      btnBuy.addEventListener("click", () => addLegFromContract(pair.call, 1));
      const btnSell = document.createElement("button");
      btnSell.type = "button";
      btnSell.className = "btn-chain-action btn-sell";
      btnSell.textContent = "+ Bán";
      btnSell.addEventListener("click", () => addLegFromContract(pair.call, -1));
      tdCallAction.append(btnBuy, " ", btnSell);
    } else {
      tdCallAction.textContent = "—";
    }
    tr.appendChild(tdCallAction);

    // Call IV, Bid, Ask, OI
    cell(tr, pair.call ? percent(pair.call.mark_iv || pair.call.iv || 0.65) : "—");
    cell(tr, pair.call ? number(pair.call.bid, 2) : "—");
    cell(tr, pair.call ? number(pair.call.ask, 2) : "—");
    cell(tr, pair.call ? number(pair.call.open_interest, 0) : "—");

    // Strike cell
    const tdStrike = document.createElement("td");
    tdStrike.className = "chain-strike-cell";
    if (currentSpot > 0 && Math.abs(strike - currentSpot) / currentSpot < 0.015) {
      tdStrike.classList.add("chain-strike-atm");
    }
    tdStrike.textContent = number(strike, 0);
    tr.appendChild(tdStrike);

    // Put Bid, Ask, IV, OI
    cell(tr, pair.put ? number(pair.put.bid, 2) : "—");
    cell(tr, pair.put ? number(pair.put.ask, 2) : "—");
    cell(tr, pair.put ? percent(pair.put.mark_iv || pair.put.iv || 0.65) : "—");
    cell(tr, pair.put ? number(pair.put.open_interest, 0) : "—");

    // Put Action cell
    const tdPutAction = document.createElement("td");
    if (pair.put) {
      const btnBuy = document.createElement("button");
      btnBuy.type = "button";
      btnBuy.className = "btn-chain-action btn-buy";
      btnBuy.textContent = "+ Mua";
      btnBuy.addEventListener("click", () => addLegFromContract(pair.put, 1));
      const btnSell = document.createElement("button");
      btnSell.type = "button";
      btnSell.className = "btn-chain-action btn-sell";
      btnSell.textContent = "+ Bán";
      btnSell.addEventListener("click", () => addLegFromContract(pair.put, -1));
      tdPutAction.append(btnBuy, " ", btnSell);
    } else {
      tdPutAction.textContent = "—";
    }
    tr.appendChild(tdPutAction);

    builderChainTbody.appendChild(tr);
  });
}

function addLegFromContract(contract, position) {
  const exp = contract.expiry ? String(contract.expiry).split("T")[0] : builderState.expiry;
  builderState.legs.push({
    option_type: String(contract.option_type || "call").toLowerCase(),
    strike: Number(contract.strike),
    expiry: exp,
    iv: Number(contract.mark_iv || contract.iv || 0.65),
    spot: builderState.spot || Number(contract.spot_price || contract.underlying_price || 60000),
    position: position,
    quantity: 1,
    mid_price: position > 0 ? (Number(contract.ask) || Number(contract.mark_price) || 0) : (Number(contract.bid) || Number(contract.mark_price) || 0),
    bid: Number(contract.bid || 0),
    ask: Number(contract.ask || 0),
    symbol: contract.symbol || "",
  });
  renderBuilderLegs();
  evaluateBuilder();
}

async function applyBuilderPreset(presetName) {
  if (presetName === "custom") return;
  try {
    const payload = {
      strategy_type: presetName,
      asset: builderState.asset,
      expiry: builderState.expiry || undefined,
    };
    const res = await getJson("/api/v1/builder/populate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.legs && res.legs.length) {
      builderState.legs = res.legs.map((leg) => ({
        option_type: leg.option_type,
        strike: leg.strike,
        expiry: leg.expiry ? String(leg.expiry).split("T")[0] : builderState.expiry,
        iv: leg.iv || 0.65,
        spot: leg.spot || builderState.spot,
        position: leg.position || 1,
        quantity: leg.quantity || 1,
        mid_price: leg.mid_price || 0,
        bid: leg.bid || 0,
        ask: leg.ask || 0,
        symbol: leg.symbol || "",
      }));
      renderBuilderLegs();
      evaluateBuilder();
    }
  } catch (err) {
    appendTerminal(`[BUILDER] Không thể nạp mẫu ${presetName}: ${err.message}`, "error");
  }
}

function renderBuilderLegs() {
  if (!builderLegsTbody) return;
  builderLegsTbody.replaceChildren();

  if (!builderState.legs.length) {
    if (builderLegsEmpty) builderLegsEmpty.hidden = false;
    return;
  }
  if (builderLegsEmpty) builderLegsEmpty.hidden = true;

  builderState.legs.forEach((leg, index) => {
    const tr = document.createElement("tr");

    // Position (Buy/Sell)
    const tdPos = document.createElement("td");
    const selPos = document.createElement("select");
    const optBuy = document.createElement("option");
    optBuy.value = "1";
    optBuy.textContent = "Mua (+1)";
    const optSell = document.createElement("option");
    optSell.value = "-1";
    optSell.textContent = "Bán (-1)";
    selPos.append(optBuy, optSell);
    selPos.value = String(leg.position);
    selPos.addEventListener("change", () => {
      leg.position = Number(selPos.value);
      evaluateBuilder();
    });
    tdPos.appendChild(selPos);
    tr.appendChild(tdPos);

    // Qty
    const tdQty = document.createElement("td");
    const inpQty = document.createElement("input");
    inpQty.type = "number";
    inpQty.min = "1";
    inpQty.value = String(leg.quantity || 1);
    inpQty.style.maxWidth = "55px";
    inpQty.addEventListener("change", () => {
      leg.quantity = Math.max(1, Number(inpQty.value) || 1);
      evaluateBuilder();
    });
    tdQty.appendChild(inpQty);
    tr.appendChild(tdQty);

    // Option Type (Call/Put)
    const tdType = document.createElement("td");
    const selType = document.createElement("select");
    const optCall = document.createElement("option");
    optCall.value = "call";
    optCall.textContent = "Call";
    const optPut = document.createElement("option");
    optPut.value = "put";
    optPut.textContent = "Put";
    selType.append(optCall, optPut);
    selType.value = leg.option_type;
    tdType.appendChild(selType);
    tr.appendChild(tdType);

    // Strike
    const tdStrike = document.createElement("td");
    const inpStrike = document.createElement("input");
    inpStrike.type = "number";
    inpStrike.value = String(leg.strike);
    tdStrike.appendChild(inpStrike);
    tr.appendChild(tdStrike);

    // Expiry
    const tdExp = document.createElement("td");
    tdExp.textContent = leg.expiry ? String(leg.expiry).split("T")[0] : "—";
    tr.appendChild(tdExp);

    // IV
    const tdIv = document.createElement("td");
    const inpIv = document.createElement("input");
    inpIv.type = "number";
    inpIv.step = "any";
    inpIv.value = String(Math.round((leg.iv || 0.65) * 100));
    inpIv.style.maxWidth = "60px";
    inpIv.addEventListener("change", () => {
      leg.iv = (Number(inpIv.value) || 65) / 100;
      evaluateBuilder();
    });
    tdIv.appendChild(inpIv);
    tr.appendChild(tdIv);

    // Price
    const tdPrice = document.createElement("td");
    const inpPrice = document.createElement("input");
    inpPrice.type = "number";
    inpPrice.step = "any";
    inpPrice.value = String(number(leg.mid_price || 0, 2));
    inpPrice.addEventListener("change", () => {
      leg.mid_price = Number(inpPrice.value) || 0;
      evaluateBuilder();
    });
    tdPrice.appendChild(inpPrice);
    tr.appendChild(tdPrice);

    // Contract sync helper when strike or option_type changes
    const onLegContractChanged = () => {
      leg.option_type = selType.value;
      leg.strike = Number(inpStrike.value) || 0;
      if (builderState.chainData && Array.isArray(builderState.chainData.contracts)) {
        const matching = builderState.chainData.contracts.find((c) => {
          const typeMatch = String(c.option_type || "").toLowerCase() === leg.option_type.toLowerCase();
          const strikeMatch = Math.abs(Number(c.strike) - leg.strike) < 0.01;
          const expMatch = !leg.expiry || !c.expiry || c.expiry.startsWith(leg.expiry.split("T")[0]) || (c.symbol && c.symbol.includes(leg.expiry.split("T")[0]));
          return typeMatch && strikeMatch && expMatch;
        }) || builderState.chainData.contracts.find((c) => {
          const typeMatch = String(c.option_type || "").toLowerCase() === leg.option_type.toLowerCase();
          const strikeMatch = Math.abs(Number(c.strike) - leg.strike) < 0.01;
          return typeMatch && strikeMatch;
        });

        if (matching) {
          const mMid = matching.mark_price || (matching.bid && matching.ask ? (matching.bid + matching.ask) / 2 : matching.bid || matching.ask || 0);
          const mIv = matching.mark_iv || matching.iv || 0.65;
          leg.mid_price = Number(mMid) || leg.mid_price;
          leg.iv = Number(mIv) || leg.iv;
          leg.bid = Number(matching.bid) || 0;
          leg.ask = Number(matching.ask) || 0;
          leg.symbol = matching.symbol || leg.symbol;
          inpPrice.value = String(number(leg.mid_price, 2));
          inpIv.value = String(Math.round(leg.iv * 100));
        }
      }
      evaluateBuilder();
    };

    selType.addEventListener("change", onLegContractChanged);
    inpStrike.addEventListener("change", onLegContractChanged);

    // Remove Action
    const tdRemove = document.createElement("td");
    const btnRemove = document.createElement("button");
    btnRemove.type = "button";
    btnRemove.className = "btn-remove-leg";
    btnRemove.setAttribute("aria-label", "Xóa chân");
    btnRemove.appendChild(createSvgIcon("x"));
    btnRemove.addEventListener("click", () => {
      builderState.legs.splice(index, 1);
      renderBuilderLegs();
      evaluateBuilder();
    });
    tdRemove.appendChild(btnRemove);
    tr.appendChild(tdRemove);

    builderLegsTbody.appendChild(tr);
  });
}

async function evaluateBuilder() {
  if (!builderState.legs || !builderState.legs.length) {
    if (builderLegsEmpty) builderLegsEmpty.hidden = false;
    if (builderStatusBadge) builderStatusBadge.textContent = "Chưa có chân";
    if (bmNetPremium) bmNetPremium.textContent = "$0.00";
    if (bmMaxProfit) bmMaxProfit.textContent = "$0.00";
    if (bmMaxLoss) bmMaxLoss.textContent = "$0.00";
    if (bmRrRatio) bmRrRatio.textContent = "--";
    if (bmBreakeven) bmBreakeven.textContent = "--";
    if (builderPayoffSvg) builderPayoffSvg.replaceChildren();
    return;
  }
  if (builderLegsEmpty) builderLegsEmpty.hidden = true;
  if (builderStatusBadge) builderStatusBadge.textContent = "Đang tính toán...";

  try {
    const payload = {
      strategy_type: builderState.activePreset || "custom",
      legs: builderState.legs.map((l) => ({
        option_type: l.option_type,
        strike: Number(l.strike),
        expiry: l.expiry,
        iv: Number(l.iv) > 2 ? Number(l.iv) / 100 : Number(l.iv) || 0.65,
        spot: Number(l.spot) || builderState.spot || 60000,
        position: Number(l.position) || 1,
        quantity: Number(l.quantity) || 1,
        mid_price: Number(l.mid_price) || 0,
        bid: Number(l.bid) || 0,
        ask: Number(l.ask) || 0,
        symbol: l.symbol || "",
      })),
      risk_free_rate: 0.05,
    };

    const res = await getJson("/api/v1/builder/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    builderState.evaluation = res;
    if (builderStatusBadge) builderStatusBadge.textContent = "Đã tính toán";
    if (bmNetPremium) {
      const netP = Number(res.net_premium) || 0;
      if (netP < -0.001) {
        bmNetPremium.textContent = `+$${number(Math.abs(netP), 2)} (Credit)`;
        bmNetPremium.className = "text-success";
      } else if (netP > 0.001) {
        bmNetPremium.textContent = `$${number(netP, 2)} (Debit)`;
        bmNetPremium.className = "text-danger";
      } else {
        bmNetPremium.textContent = "$0.00";
        bmNetPremium.className = "";
      }
    }
    if (bmMaxProfit) {
      if (res.max_profit === null || res.max_profit === undefined) {
        bmMaxProfit.textContent = "Không giới hạn";
        bmMaxProfit.className = "text-success";
      } else if (res.max_profit < 0) {
        bmMaxProfit.textContent = `Lỗ mọi kịch bản ($${number(Math.abs(res.max_profit), 2)})`;
        bmMaxProfit.className = "text-danger";
      } else {
        bmMaxProfit.textContent = `$${number(res.max_profit, 2)}`;
        bmMaxProfit.className = "text-success";
      }
    }
    if (bmMaxLoss) {
      if (res.max_loss === null || res.max_loss === undefined) {
        bmMaxLoss.textContent = "Không giới hạn";
        bmMaxLoss.className = "text-danger";
      } else {
        bmMaxLoss.textContent = `$${number(res.max_loss, 2)}`;
        bmMaxLoss.className = "text-danger";
      }
    }
    if (bmRrRatio) {
      bmRrRatio.textContent = res.risk_reward_ratio != null ? number(res.risk_reward_ratio, 2) : "--";
    }
    if (bmBreakeven) {
      bmBreakeven.textContent = res.breakevens?.length ? res.breakevens.map((b) => `$${number(b, 2)}`).join(", ") : "Không có";
    }
    if (bgDelta) bgDelta.textContent = number(res.greeks?.delta, 4);
    if (bgGamma) bgGamma.textContent = number(res.greeks?.gamma, 4);
    if (bgTheta) bgTheta.textContent = number(res.greeks?.theta, 4);
    if (bgVega) bgVega.textContent = number(res.greeks?.vega, 4);

    renderBuilderPayoffChart(res.payoff_curve || [], res.breakevens || [], builderState.spot);
  } catch (err) {
    if (builderStatusBadge) builderStatusBadge.textContent = "Lỗi tính toán";
    appendTerminal(`[BUILDER] Lỗi tính toán payoff: ${err.message}`, "error");
  }
}

function renderBuilderPayoffChart(curve, breakevens, spot) {
  if (!builderPayoffSvg) return;
  builderPayoffSvg.replaceChildren();

  if (!curve || curve.length < 2) return;

  const width = 600;
  const height = 280;
  const padLeft = 60;
  const padRight = 30;
  const padTop = 30;
  const padBottom = 40;

  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  const spots = curve.map((pt) => pt.spot);
  const pnls = curve.map((pt) => pt.pnl);

  const minSpot = Math.min(...spots);
  const maxSpot = Math.max(...spots);
  let minPnl = Math.min(0, ...pnls);
  let maxPnl = Math.max(0, ...pnls);

  // Add 10% headroom
  const pnlSpan = maxPnl - minPnl || 1;
  minPnl -= pnlSpan * 0.05;
  maxPnl += pnlSpan * 0.05;

  const scaleX = (s) => padLeft + ((s - minSpot) / (maxSpot - minSpot || 1)) * chartW;
  const scaleY = (p) => padTop + ((maxPnl - p) / (maxPnl - minPnl || 1)) * chartH;

  const svgNS = "http://www.w3.org/2000/svg";

  // Zero PnL line
  const zeroY = scaleY(0);
  const zeroLine = document.createElementNS(svgNS, "line");
  zeroLine.setAttribute("x1", String(padLeft));
  zeroLine.setAttribute("y1", String(zeroY));
  zeroLine.setAttribute("x2", String(width - padRight));
  zeroLine.setAttribute("y2", String(zeroY));
  zeroLine.setAttribute("stroke", "#43586c");
  zeroLine.setAttribute("stroke-width", "1.5");
  zeroLine.setAttribute("stroke-dasharray", "4 4");
  builderPayoffSvg.appendChild(zeroLine);

  // Zero PnL label
  const zeroText = document.createElementNS(svgNS, "text");
  zeroText.setAttribute("x", String(padLeft - 8));
  zeroText.setAttribute("y", String(zeroY + 4));
  zeroText.setAttribute("text-anchor", "end");
  zeroText.setAttribute("fill", "#7893a8");
  zeroText.setAttribute("font-size", "11");
  zeroText.textContent = "$0";
  builderPayoffSvg.appendChild(zeroText);

  // Current Spot line
  if (spot >= minSpot && spot <= maxSpot) {
    const spotX = scaleX(spot);
    const spotLine = document.createElementNS(svgNS, "line");
    spotLine.setAttribute("x1", String(spotX));
    spotLine.setAttribute("y1", String(padTop));
    spotLine.setAttribute("x2", String(spotX));
    spotLine.setAttribute("y2", String(height - padBottom));
    spotLine.setAttribute("stroke", "#8eb5ff");
    spotLine.setAttribute("stroke-width", "1.5");
    spotLine.setAttribute("stroke-dasharray", "3 3");
    builderPayoffSvg.appendChild(spotLine);

    const spotText = document.createElementNS(svgNS, "text");
    spotText.setAttribute("x", String(spotX));
    spotText.setAttribute("y", String(padTop - 8));
    spotText.setAttribute("text-anchor", "middle");
    spotText.setAttribute("fill", "#8eb5ff");
    spotText.setAttribute("font-size", "10");
    spotText.setAttribute("font-weight", "bold");
    spotText.textContent = `Spot: $${number(spot, 0)}`;
    builderPayoffSvg.appendChild(spotText);
  }

  // Payoff path
  let pathD = "";
  curve.forEach((pt, i) => {
    const x = scaleX(pt.spot);
    const y = scaleY(pt.pnl);
    pathD += (i === 0 ? "M " : " L ") + x.toFixed(1) + " " + y.toFixed(1);
  });

  const path = document.createElementNS(svgNS, "path");
  path.setAttribute("d", pathD);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "#62d4a4");
  path.setAttribute("stroke-width", "2.5");
  builderPayoffSvg.appendChild(path);

  // Breakeven dots
  (breakevens || []).forEach((be) => {
    if (be >= minSpot && be <= maxSpot) {
      const beX = scaleX(be);
      const circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("cx", String(beX));
      circle.setAttribute("cy", String(zeroY));
      circle.setAttribute("r", "5");
      circle.setAttribute("fill", "#ffe082");
      circle.setAttribute("stroke", "#000");
      circle.setAttribute("stroke-width", "1.5");
      builderPayoffSvg.appendChild(circle);

      const beText = document.createElementNS(svgNS, "text");
      beText.setAttribute("x", String(beX));
      beText.setAttribute("y", String(zeroY + 16));
      beText.setAttribute("text-anchor", "middle");
      beText.setAttribute("fill", "#ffe082");
      beText.setAttribute("font-size", "10");
      beText.textContent = `BE $${number(be, 0)}`;
      builderPayoffSvg.appendChild(beText);
    }
  });

  // Min/Max spot axis labels
  const minText = document.createElementNS(svgNS, "text");
  minText.setAttribute("x", String(padLeft));
  minText.setAttribute("y", String(height - padBottom + 18));
  minText.setAttribute("fill", "#7893a8");
  minText.setAttribute("font-size", "11");
  minText.textContent = `$${number(minSpot, 0)}`;
  builderPayoffSvg.appendChild(minText);

  const maxText = document.createElementNS(svgNS, "text");
  maxText.setAttribute("x", String(width - padRight));
  maxText.setAttribute("y", String(height - padBottom + 18));
  maxText.setAttribute("text-anchor", "end");
  maxText.setAttribute("fill", "#7893a8");
  maxText.setAttribute("font-size", "11");
  maxText.textContent = `$${number(maxSpot, 0)}`;
  builderPayoffSvg.appendChild(maxText);
}

async function saveBuilderToNotebook() {
  if (!builderState.legs || !builderState.legs.length) {
    alert("Vui lòng thêm ít nhất một chân vào chiến lược trước khi lưu.");
    return;
  }
  const payload = {
    asset: builderState.asset,
    strategy_type: builderState.activePreset || "custom",
    legs: builderState.legs,
    entry_spot: builderState.spot || Number(builderState.legs[0]?.spot || 0),
    target_profit_pct: 50.0,
    stop_loss_pct: 50.0,
    notes: `Lưu từ Strategy Builder (${builderState.activePreset || "custom"})`,
    source: "builder",
  };
  try {
    const res = await getJson("/api/v1/notebook/positions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    appendTerminal(`[NOTEBOOK] Đã lưu vị thế ${res.position?.id} (${payload.strategy_type}) vào Sổ tay giám sát.`, "success");
    window.location.hash = "#monitoring";
  } catch (err) {
    appendTerminal(`[NOTEBOOK] Lỗi lưu vị thế: ${err.message}`, "error");
  }
}

async function openOpportunityInBuilder(item) {
  const asset = item.asset || item.base_coin || (item.symbol ? item.symbol.split("-")[0] : "BTC");
  builderState.asset = asset;
  builderState.activePreset = item.strategy || "custom";

  // Determine common expiry
  const oppExp = opportunityExpiry(item);
  if (oppExp) {
    builderState.expiry = String(oppExp).split("T")[0];
  }

  const legs = [];
  const rawLegs = opportunityLegs(item);
  if (rawLegs.length) {
    rawLegs.forEach((l) => {
      const bid = Number(l.bid_price ?? l.bid ?? 0);
      const ask = Number(l.ask_price ?? l.ask ?? 0);
      const mark = Number(l.mark_price ?? l.market_price ?? l.market_mid ?? (bid && ask ? (bid + ask) / 2 : bid || ask || 0));
      const pos = Number(l.position ?? (inferredLegPosition ? inferredLegPosition(item.strategy, l, rawLegs) : 1));
      const mid = pos > 0 ? (ask > 0 ? ask : mark) : (bid > 0 ? bid : mark);
      const exp = l.expiry_at || l.expiry || oppExp || "";

      legs.push({
        option_type: String(l.option_type || (l.symbol && l.symbol.endsWith("-C") ? "call" : "put")).toLowerCase(),
        strike: Number(legStrike(l)) || 0,
        expiry: exp ? String(exp).split("T")[0] : builderState.expiry,
        iv: Number(l.market_iv ?? l.implied_volatility ?? l.fair_iv ?? 0.65),
        spot: Number(l.spot_price ?? item.spot_price ?? item.underlying_price ?? 0),
        position: pos,
        quantity: 1,
        mid_price: mid,
        bid: bid,
        ask: ask,
        symbol: l.symbol || "",
      });
    });
  } else {
    const bid = Number(item.bid_price ?? 0);
    const ask = Number(item.ask_price ?? 0);
    const mid = Number(item.market_mid ?? item.fair_price ?? item.mark_price ?? (bid && ask ? (bid + ask) / 2 : bid || ask || 0));
    legs.push({
      option_type: String(item.option_type || (item.symbol && item.symbol.endsWith("-C") ? "call" : "put")).toLowerCase(),
      strike: Number(item.strike) || 0,
      expiry: oppExp ? String(oppExp).split("T")[0] : builderState.expiry,
      iv: Number(item.market_iv ?? item.implied_volatility ?? 0.65),
      spot: Number(item.spot_price ?? item.underlying_price ?? 0),
      position: 1,
      quantity: 1,
      mid_price: mid,
      bid: bid,
      ask: ask,
      symbol: item.symbol || "",
    });
  }

  builderState.legs = legs;
  builderState.spot = Number(item.spot_price || item.underlying_price || 0);

  if (builderAssetSelect) {
    builderAssetSelect.value = asset;
  }
  if (builderSpotDisplay && builderState.spot > 0) {
    builderSpotDisplay.textContent = `$${number(builderState.spot, 2)}`;
  }

  window.location.hash = "#builder";

  // Pre-load option chain for the asset in background, sync expiry, and render
  try {
    const chainData = await getJson(`/api/v1/options/chain/${asset}`);
    builderState.chainData = chainData;
    if (chainData.spot) builderState.spot = chainData.spot;
    if (builderExpirySelect) {
      builderExpirySelect.replaceChildren();
      (chainData.expiries || []).forEach((exp) => {
        const opt = document.createElement("option");
        opt.value = exp;
        opt.textContent = exp;
        builderExpirySelect.appendChild(opt);
      });
      if (builderState.expiry && chainData.expiries && chainData.expiries.includes(builderState.expiry)) {
        builderExpirySelect.value = builderState.expiry;
      } else if (chainData.expiries && chainData.expiries.length) {
        builderState.expiry = chainData.expiries[0];
        builderExpirySelect.value = builderState.expiry;
      }
    }
    if (builderChainStatus) {
      builderChainStatus.textContent = `${chainData.contracts?.length || 0} hợp đồng`;
    }
    renderBuilderChain(chainData, builderState.expiry);
  } catch (err) {
    console.warn("Could not preload builder chain for opportunity:", err);
  }

  renderBuilderLegs();
  evaluateBuilder();
}

async function saveOpportunityToNotebook(item) {
  const asset = item.asset || item.base_coin || (item.symbol ? item.symbol.split("-")[0] : "BTC");
  const rawLegs = opportunityLegs(item);
  const oppExp = opportunityExpiry(item);

  const mappedLegs = rawLegs.length
    ? rawLegs.map((l) => {
        const bid = Number(l.bid_price ?? l.bid ?? 0);
        const ask = Number(l.ask_price ?? l.ask ?? 0);
        const mark = Number(l.mark_price ?? l.market_price ?? l.market_mid ?? (bid && ask ? (bid + ask) / 2 : bid || ask || 0));
        const pos = Number(l.position ?? (inferredLegPosition ? inferredLegPosition(item.strategy, l, rawLegs) : 1));
        const entry = pos > 0 ? (ask > 0 ? ask : mark) : (bid > 0 ? bid : mark);
        const exp = l.expiry_at || l.expiry || oppExp || "";
        return {
          symbol: l.symbol || "",
          option_type: String(l.option_type || (l.symbol && l.symbol.endsWith("-C") ? "call" : "put")).toLowerCase(),
          strike: Number(legStrike(l)) || 0,
          position: pos,
          quantity: 1,
          entry_price: entry,
          expiry: exp ? String(exp).split("T")[0] : "",
        };
      })
    : [
        {
          symbol: item.symbol || "",
          option_type: String(item.option_type || (item.symbol && item.symbol.endsWith("-C") ? "call" : "put")).toLowerCase(),
          strike: Number(item.strike) || 0,
          position: 1,
          quantity: 1,
          entry_price: Number(item.market_mid || item.fair_price || item.mark_price || 0),
          expiry: oppExp ? String(oppExp).split("T")[0] : "",
        },
      ];

  const payload = {
    asset: asset,
    strategy_type: item.strategy || "single_option",
    legs: mappedLegs,
    entry_spot: Number(item.spot_price || item.underlying_price || 0),
    target_profit_pct: 50.0,
    stop_loss_pct: 50.0,
    notes: `Tín hiệu Scanner: Edge=${item.edge_after_costs} | EV=${item.expected_value || item.estimated_ev}`,
    source: "scanner",
  };
  try {
    const res = await getJson("/api/v1/notebook/positions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    appendTerminal(`[NOTEBOOK] Đã lưu cơ hội ${res.position?.id} (${payload.strategy_type}) vào Sổ tay.`, "success");
  } catch (err) {
    appendTerminal(`[NOTEBOOK] Lỗi lưu cơ hội: ${err.message}`, "error");
  }
}

// ==========================================
// Trade Notebook & Smart Monitor Logic
// ==========================================

async function loadTradeNotebook() {
  if (nbRefreshBtn) nbRefreshBtn.disabled = true;
  try {
    const [positionsData, monitorData] = await Promise.all([
      getJson("/api/v1/notebook/positions"),
      getJson("/api/v1/notebook/monitor"),
    ]);
    const positions = positionsData.positions || [];
    const evaluations = monitorData.evaluations || [];
    renderTradeNotebook(positions, evaluations);
  } catch (err) {
    appendTerminal(`[NOTEBOOK] Lỗi nạp Sổ tay & Smart Monitor: ${err.message}`, "error");
  } finally {
    if (nbRefreshBtn) nbRefreshBtn.disabled = false;
  }
}

function renderTradeNotebook(positions, evaluations) {
  if (!nbPositionsTbody) return;
  nbPositionsTbody.replaceChildren();

  const evalMap = new Map();
  evaluations.forEach((e) => evalMap.set(e.position_id, e));

  let totalPnl = 0;
  let tpCount = 0;
  let slCount = 0;
  let holdCount = 0;

  positions.forEach((pos) => {
    const ev = evalMap.get(pos.id);
    const pnl = ev ? Number(ev.unrealized_pnl || 0) : 0;
    totalPnl += pnl;

    const action = ev?.decision?.action || "REVIEW";
    if (action === "TAKE_PROFIT") tpCount++;
    else if (action === "CUT_LOSS") slCount++;
    else if (action === "HOLD") holdCount++;

    const tr = document.createElement("tr");

    // ID
    const tdId = document.createElement("td");
    tdId.textContent = pos.id;
    tr.appendChild(tdId);

    // Asset & Strategy
    const tdStrat = document.createElement("td");
    const strongAsset = document.createElement("strong");
    strongAsset.textContent = pos.asset;
    const br = document.createElement("br");
    const smallStrat = document.createElement("small");
    smallStrat.className = "muted";
    smallStrat.textContent = strategyLabel(pos.strategy_type);
    tdStrat.append(strongAsset, br, smallStrat);
    tr.appendChild(tdStrat);

    // Legs Summary
    const tdLegs = document.createElement("td");
    const legsList = (pos.legs || []).map((l) => `${l.position > 0 ? "+" : "-"}${l.quantity || 1} ${l.option_type?.toUpperCase()} ${number(l.strike, 0)}`).join(" / ");
    tdLegs.textContent = legsList || "1 leg";
    tr.appendChild(tdLegs);

    // Spot Entry / Current
    const tdSpot = document.createElement("td");
    const curSpot = ev?.current_spot || pos.entry_spot || 0;
    tdSpot.textContent = `$${number(pos.entry_spot, 1)} → $${number(curSpot, 1)}`;
    tr.appendChild(tdSpot);

    // Unrealized PnL
    const tdPnl = document.createElement("td");
    tdPnl.textContent = `$${number(pnl, 2)}`;
    tdPnl.className = pnl >= 0 ? "text-success" : "text-danger";
    tdPnl.style.fontWeight = "bold";
    tr.appendChild(tdPnl);

    // Smart Monitor Badge
    const tdAction = document.createElement("td");
    const badge = document.createElement("span");
    const actionVn = ev?.decision?.action_vn || "XEM XÉT";
    badge.textContent = actionVn;
    if (action === "TAKE_PROFIT") {
      badge.className = "smart-badge smart-badge-profit";
    } else if (action === "CUT_LOSS") {
      badge.className = "smart-badge smart-badge-cut";
    } else if (action === "HOLD") {
      badge.className = "smart-badge smart-badge-hold";
    } else {
      badge.className = "smart-badge smart-badge-review";
    }
    tdAction.appendChild(badge);
    tr.appendChild(tdAction);

    // Reasons / Triggers
    const tdReasons = document.createElement("td");
    tdReasons.textContent = ev?.decision?.reason || pos.notes || "Thesis intact";
    tr.appendChild(tdReasons);

    // Action buttons (Close / Delete)
    const tdOps = document.createElement("td");
    const btnClose = document.createElement("button");
    btnClose.type = "button";
    btnClose.className = "btn-action-small";
    btnClose.textContent = "Đóng";
    btnClose.addEventListener("click", async () => {
      try {
        await getJson(`/api/v1/notebook/positions/${pos.id}/close`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ exit_spot: curSpot, exit_pnl: pnl, notes: "Đóng thủ công từ UI" }),
        });
        appendTerminal(`[NOTEBOOK] Đã đóng vị thế ${pos.id}.`, "info");
        loadTradeNotebook();
      } catch (e) {
        appendTerminal(`[NOTEBOOK] Lỗi đóng vị thế: ${e.message}`, "error");
      }
    });

    const btnDel = document.createElement("button");
    btnDel.type = "button";
    btnDel.className = "btn-action-small btn-danger";
    btnDel.textContent = "Xóa";
    btnDel.addEventListener("click", async () => {
      try {
        await getJson(`/api/v1/notebook/positions/${pos.id}`, { method: "DELETE" });
        appendTerminal(`[NOTEBOOK] Đã xóa vị thế ${pos.id}.`, "info");
        loadTradeNotebook();
      } catch (e) {
        appendTerminal(`[NOTEBOOK] Lỗi xóa vị thế: ${e.message}`, "error");
      }
    });

    tdOps.append(btnClose, btnDel);
    tr.appendChild(tdOps);

    nbPositionsTbody.appendChild(tr);
  });

  if (nbStatTotal) nbStatTotal.textContent = String(positions.length);
  if (nbStatPnl) {
    nbStatPnl.textContent = `$${number(totalPnl, 2)}`;
    nbStatPnl.className = totalPnl >= 0 ? "text-success" : "text-danger";
  }
  if (nbStatTp) nbStatTp.textContent = String(tpCount);
  if (nbStatSl) nbStatSl.textContent = String(slCount);
  if (nbStatHold) nbStatHold.textContent = String(holdCount);

  if (nbEmptyState) nbEmptyState.hidden = positions.length > 0;
}

if (nbRefreshBtn) {
  nbRefreshBtn.addEventListener("click", loadTradeNotebook);
}

valuationModeInputs.forEach((input) => input.addEventListener("change", syncValuationModeInputs));
syncValuationModeInputs();

window.addEventListener("hashchange", syncWorkspaceFromHash);
syncWorkspaceFromHash();

clearTerminalButton.addEventListener("click", clearTerminal);

const detailOpenBuilderBtn = document.querySelector("#detail-open-builder");
const detailSaveNotebookBtn = document.querySelector("#detail-save-notebook");

if (detailOpenBuilderBtn) {
  detailOpenBuilderBtn.addEventListener("click", () => {
    if (selectedOpportunity) {
      openOpportunityInBuilder(selectedOpportunity);
    }
  });
}

if (detailSaveNotebookBtn) {
  detailSaveNotebookBtn.addEventListener("click", () => {
    if (selectedOpportunity) {
      saveOpportunityToNotebook(selectedOpportunity);
    }
  });
}

closeDetailButton.addEventListener("click", () => {
  detailPanel.hidden = true;
  selectedOpportunity = null;
});

loadAssets();
