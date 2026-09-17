const serviceStatus = document.querySelector("#service-status");
const dataStatus = document.querySelector("#data-status");
const assetList = document.querySelector("#asset-list");
const form = document.querySelector("#scan-form");
const resultState = document.querySelector("#result-state");
const resultsBody = document.querySelector("#results-body");
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
const liveOpportunityBody = document.querySelector("#live-opportunity-body");
const signalChart = document.querySelector("#signal-chart");
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
    liveOpportunityBody,
    signalChart,
    liveSignalStatus,
    liveFeed,
    liveRejectionSummary,
  },
  getSelectedAssets: () => [...form.querySelectorAll('input[name="assets"]:checked')].map((input) => input.value),
  opportunitySymbol,
  strategyLabel,
  onOpportunityDetail: showOpportunityDetail,
  onLog: appendTerminal,
});

const WORKSPACE_META = Object.freeze({
  scanner: {
    eyebrow: "Nghiên cứu quyền chọn / Scanner",
    title: "Crypto Options Scanner",
    description: "Tìm hợp đồng có chênh lệch giữa giá mô hình và giá có thể mua.",
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
  if (workspace !== "scanner" && liveDesk.isWanted()) liveDesk.stop();

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
  document.body.dataset.activeWorkspace = workspace;
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
  return `Hết hạn ${date} ${time}`;
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
  line.textContent = `${new Date().toLocaleTimeString("vi-VN")} ${message}`;
  scanTerminal.appendChild(line);
  scanTerminal.scrollTop = scanTerminal.scrollHeight;
}

function clearTerminal() {
  scanTerminal.replaceChildren();
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
    return `Đây là định giá với bid/ask tổng hợp cho ${asset}; edge, payoff, EV, xác suất và RR được tính theo spread giả định, không khẳng định giá khớp thực tế.`;
  }
  if (isTheoreticalMode(item?.valuation_mode || activeScanValuationMode)) {
    return `Đây là định giá mô hình của ${asset}; payoff, EV, xác suất và RR được tính từ fair value nhưng không khẳng định giá khớp hay lợi nhuận thực tế.`;
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
  heading.append(title, badge);
  card.appendChild(heading);

  const takeaway = document.createElement("p");
  takeaway.className = "explanation-takeaway";
  takeaway.textContent = strategyTakeaway(item, legs);
  card.appendChild(takeaway);

  const legList = document.createElement("div");
  legList.className = "explanation-legs";
  legs.forEach((leg) => {
    const position = inferredLegPosition(item?.strategy, leg, legs);
    const legLine = document.createElement("span");
    legLine.className = position > 0 ? "buy-leg" : "sell-leg";
    const action = position > 0 ? "Mua" : "Bán";
    const strike = legStrike(leg);
    legLine.textContent = `${action} K${strike === undefined ? "—" : number(strike, 2)} ${optionTypeLabel(leg)} · ${legExpiryLabel(leg, item)}`;
    legList.appendChild(legLine);
  });
  card.appendChild(legList);

  const executablePrice = firstDefined(item?.estimated_entry, item?.executable_entry, item?.market_mid);
  const fairPrice = firstDefined(item?.fair_price);
  const edge = Number(item?.edge_after_costs);
  const facts = document.createElement("div");
  facts.className = "explanation-facts";
  facts.append(
    explanationFact(synthetic ? "Giá vào mô hình" : "Tiền vào/ra ước tính", theoretical ? "Không có giá khớp" : signedPriceLabel(executablePrice), modelMode ? "theoretical-value" : ""),
    explanationFact("Mô hình định giá", signedPriceLabel(fairPrice), modelMode ? "theoretical-value" : ""),
    explanationFact("Edge sau phí", theoretical ? "Không tính" : Number.isFinite(edge) ? `${edge >= 0 ? "+" : ""}${number(edge, 4)}` : "—", modelMode ? "theoretical-value" : edge >= 0 ? "positive" : "negative"),
    explanationFact(modelMode ? "EV mô hình" : "EV ước tính", estimatedNumber(firstDefined(item?.estimated_ev, item?.expected_value, item?.ev)), modelMode ? "theoretical-value" : ""),
    explanationFact(modelMode ? "Xác suất có lãi (mô hình)" : "Xác suất có lãi", estimateProbability(firstDefined(item?.win_probability, item?.win_rate, item?.probability_of_profit)), modelMode ? "theoretical-value" : ""),
    explanationFact(modelMode ? "RR (mô hình)" : "RR", estimateRatio(firstDefined(item?.rr, item?.risk_reward, item?.risk_reward_ratio)), modelMode ? "theoretical-value" : ""),
    explanationFact(modelMode ? "Lỗ tối đa (mô hình)" : "Lỗ tối đa", estimatedNumber(item?.max_loss), modelMode ? "theoretical-value" : "negative"),
  );
  card.appendChild(facts);

  const extra = document.createElement("p");
  extra.className = "explanation-extra muted";
  const maxProfit = item?.max_profit;
  const breakevens = Array.isArray(item?.breakevens) ? item.breakevens : [];
  const parts = [];
  if (maxProfit !== undefined && maxProfit !== null) parts.push(`${modelMode ? "Lãi tối đa (mô hình)" : "Lãi tối đa"}: ${number(maxProfit, 2)}`);
  if (breakevens.length) parts.push(`Hòa vốn: ${breakevens.map((value) => `K${number(value, 2)}`).join(" và ")}`);
  parts.push(`${modelMode ? "IV edge mô hình" : "IV edge"}: ${percent(item?.iv_edge)}`);
  extra.textContent = parts.join(" · ");
  card.appendChild(extra);
  return card;
}

function svgNode(name, attributes = {}, text = undefined) {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([attribute, value]) => node.setAttribute(attribute, String(value)));
  if (text !== undefined) node.textContent = text;
  return node;
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
    metric(modelMode ? "Xác suất có lãi (mô hình)" : "Xác suất có lãi (ước tính)", estimateProbability(firstDefined(item?.win_probability, item?.win_rate, item?.probability_of_profit)), modelMode ? "theoretical-value" : ""),
    metric(modelMode ? "RR (mô hình)" : "RR (ước tính)", estimateRatio(firstDefined(item?.rr, item?.risk_reward, item?.risk_reward_ratio)), modelMode ? "theoretical-value" : ""),
    metric(modelMode ? "Lỗ tối đa (mô hình)" : "Lỗ tối đa", estimatedNumber(item?.max_loss), modelMode ? "theoretical-value" : "negative"),
    metric(modelMode ? "Lãi tối đa (mô hình)" : "Lãi tối đa", estimatedNumber(item?.max_profit), modelMode ? "theoretical-value" : "positive"),
    metric("Điểm hòa vốn", (Array.isArray(item?.breakevens) ? item.breakevens : []).map((value) => number(value, 2)).join(", ") || "Không có dữ liệu"),
  );
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
  pnlChartAssumptions.textContent = `${quoteAssumption}Phương pháp / giả định API: ${methodologyNote(item)}`;
  if (points.length) {
    setScenarioState(`Hiển thị ${points.length} điểm payoff tại đáo hạn do API trả về.`);
  } else {
    setScenarioState("API chưa trả về payoff_curve cho cơ hội này; các giá trị không có được ghi rõ là không có dữ liệu.", "error");
  }
}

function showOpportunityDetail(item) {
  selectedOpportunity = item;
  detailPanel.hidden = false;
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
    ? `Dựng bid/ask theo spread giả định ${number(firstDefined(activeScanContext?.assumptions?.assumed_spread_bps, activeScanContext?.applied_filters?.assumed_spread_bps), 0)} bps quanh mark/fair value.`
    : "Định giá theo fair value mô hình khi thị trường thiếu bid/ask.";
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
      appendTerminal(event.message);
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

function renderResults(payload) {
  activeScanValuationMode = payload.valuation_mode || payload.scan_context?.valuation_mode || "executable";
  activeScanContext = payload.scan_context || null;
  resultsBody.replaceChildren();
  secondaryResults.replaceChildren();
  opportunityExplanations.replaceChildren();
  renderScanContext(payload.scan_context);
  renderValuationModeNotice(activeScanValuationMode);
  renderHistoricalContext(payload.historical_volatility_contexts);
  detailPanel.hidden = true;
  selectedOpportunity = null;
  if (resultsGuide) {
    resultsGuide.hidden = true;
  }
  if (!opportunities.length) setState("Không có cơ hội đạt đủ điều kiện hiện tại.");
  else setState(`${opportunities.length} cơ hội đạt điều kiện.`);
  opportunities.forEach((item, index) => {
    opportunityExplanations.appendChild(renderOpportunityExplanation(item, index));
    const row = document.createElement("tr");
    renderInstrumentCell(row, item);
    cell(row, expiryLabel(item));
    cell(row, strategyLabel(item.strategy));
    const theoretical = isTheoreticalMode(item.valuation_mode || activeScanValuationMode);
    const synthetic = isSyntheticMode(item.valuation_mode || activeScanValuationMode);
    const modelMode = theoretical || synthetic;
    const hasQuote = synthetic
      ? Number.isFinite(Number(item.bid_price)) && Number.isFinite(Number(item.ask_price))
      : Number(item.bid_price) > 0 && Number(item.ask_price) > 0;
    const quoteLabel = hasQuote
      ? synthetic
        ? `Giả định ${number(item.market_mid)}`
        : `Tham khảo ${number(item.market_mid)}`
      : "—";
    cell(row, modelMode ? quoteLabel : number(item.market_mid), modelMode ? "theoretical-value" : "");
    cell(row, number(item.fair_price), modelMode ? "theoretical-value" : "");
    cell(row, percent(item.iv_edge), item.iv_edge >= 0 ? "positive" : "negative");
    cell(row, theoretical ? "Không tính" : number(item.edge_after_costs), theoretical ? "theoretical-value" : item.edge_after_costs >= 0 ? "positive" : "negative");
    cell(row, theoretical ? `Mô hình ${number(item.max_loss)}` : synthetic ? `Ước tính ${number(item.max_loss)}` : number(item.max_loss), modelMode ? "theoretical-value" : "");
    cell(row, `OI ${number(item.open_interest, 0)} · Vol ${number(item.volume_24h, 0)}`);
    const actionCell = document.createElement("td");
    const detailButton = document.createElement("button");
    detailButton.type = "button";
    detailButton.className = "secondary-button compact-button";
    if (synthetic) {
      detailButton.textContent = "Xem payoff tổng hợp";
      detailButton.addEventListener("click", () => showOpportunityDetail(item));
    } else if (theoretical) {
      detailButton.textContent = "Xem payoff mô hình";
      detailButton.addEventListener("click", () => showOpportunityDetail(item));
    } else {
      detailButton.textContent = "Xem payoff / P&L";
      detailButton.addEventListener("click", () => showOpportunityDetail(item));
    }
    actionCell.appendChild(detailButton);
    row.appendChild(actionCell);
    resultsBody.appendChild(row);
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
  appendTerminal("Đang tải danh sách tài sản từ Bybit…");
  try {
    const payload = await getJson("/api/v1/assets");
    renderAssets(payload);
    serviceStatus.textContent = "API đang hoạt động";
    appendTerminal(`Đã tải ${payload.assets?.length || 0} tài sản.`, "success");
  } catch (error) {
    serviceStatus.textContent = "API không sẵn sàng";
    serviceStatus.classList.add("error");
    setState(error.message, "error");
    appendTerminal(`LỖI: ${error.message}`, "error");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  if (liveDesk.isWanted()) liveDesk.stop();
  const scanInput = scanPayloadFromForm();
  if (scanInput.error) {
    setState(scanInput.error, "error");
    return;
  }
  const payload = scanInput.payload;
  button.disabled = true;
  clearTerminal();
  appendTerminal("Bắt đầu quét…");
  setState("Đang lấy dữ liệu và dựng bề mặt biến động…");
  try {
    renderResults(await streamJson("/api/v1/opportunities/scan/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }));
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
      setMonitoringState("Đã dừng live monitoring. Không có lệnh nào được gửi.");
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

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify(request));
    button.textContent = "Dừng live";
  });
  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "snapshot") {
      renderMonitoringResult(payload);
      return;
    }
    if (payload.type === "error") {
      setMonitoringState(payload.message || "Live monitoring gặp lỗi.", "error");
      return;
    }
    const statusMessages = {
      starting: "Đang khởi tạo live monitoring…",
      connected: "Đã kết nối Bybit private stream; đang nhận cập nhật live…",
      reconciled: "Đã reconnect và reconcile lại với REST; tiếp tục nhận cập nhật live.",
      disconnected: "Mất kết nối Bybit; đang thử reconnect…",
    };
    if (payload.status && statusMessages[payload.status]) setMonitoringState(statusMessages[payload.status]);
  });
  socket.addEventListener("error", () => {
    setMonitoringState("Không thể kết nối live monitoring. Kiểm tra credential và server.", "error");
  });
  socket.addEventListener("close", () => {
    if (monitoringSocket !== socket) return;
    monitoringSocket = null;
    monitoringRequestKey = null;
    button.textContent = "Cập nhật theo dõi";
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
  try {
    appendTerminal("Bắt đầu backtest lịch sử…");
    renderBacktestResult(await getJson("/api/v1/backtests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }));
    appendTerminal("Backtest hoàn tất.", "success");
  } catch (error) {
    setBacktestState(error.message, "error");
    backtestQuality.hidden = true;
    appendTerminal(`LỖI BACKTEST: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
});
valuationModeInputs.forEach((input) => input.addEventListener("change", syncValuationModeInputs));
syncValuationModeInputs();

window.addEventListener("hashchange", syncWorkspaceFromHash);
syncWorkspaceFromHash();

clearTerminalButton.addEventListener("click", clearTerminal);

closeDetailButton.addEventListener("click", () => {
  detailPanel.hidden = true;
  selectedOpportunity = null;
});

loadAssets();
