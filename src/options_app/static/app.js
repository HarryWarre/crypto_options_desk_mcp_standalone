const serviceStatus = document.querySelector("#service-status");
const dataStatus = document.querySelector("#data-status");
const assetList = document.querySelector("#asset-list");
const form = document.querySelector("#scan-form");
const resultState = document.querySelector("#result-state");
const resultsBody = document.querySelector("#results-body");
const secondaryResults = document.querySelector("#secondary-results");
const resultsGuide = document.querySelector("#results-guide");
const scanContext = document.querySelector("#scan-context");
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

let selectedOpportunity = null;
let activeScanContext = null;
let scenarioRequestId = 0;

const SVG_NS = "http://www.w3.org/2000/svg";
const PNL_PATHS = Object.freeze([
  { key: "Giá -10%", label: "Giá -10%", move: -10, color: "#ef8f8f" },
  { key: "Giá -5%", label: "Giá -5%", move: -5, color: "#f0bb87" },
  { key: "Giá hiện tại", label: "Giá hiện tại", move: 0, color: "#62d4a4" },
  { key: "Giá +5%", label: "Giá +5%", move: 5, color: "#8eb5ff" },
  { key: "Giá +10%", label: "Giá +10%", move: 10, color: "#c79cff" },
]);

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
  return firstDefined(item?.expiry_at, firstLeg?.expiry_at, firstLeg?.expiry);
}

function expiryLabel(item) {
  const rawExpiry = opportunityExpiry(item);
  if (!rawExpiry) return "—";
  const parsedExpiry = new Date(rawExpiry);
  return Number.isNaN(parsedExpiry.getTime()) ? String(rawExpiry) : parsedExpiry.toLocaleString("vi-VN");
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

function scenarioStrategyType(strategy) {
  const normalized = normalizedStrategy(strategy);
  if (["bull_call_vertical", "bear_call_vertical", "bull_call_spread", "bear_call_spread", "call_vertical"].includes(normalized)) {
    return "call_vertical";
  }
  if (["bull_put_vertical", "bear_put_vertical", "bull_put_spread", "bear_put_spread", "put_vertical"].includes(normalized)) {
    return "put_vertical";
  }
  if (["iron_condor", "iron_butterfly"].includes(normalized)) return normalized;
  return normalized;
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

function scenarioLeg(item, leg, legs) {
  return {
    symbol: legSymbol(leg),
    option_type: firstDefined(leg?.option_type, leg?.type, item?.option_type),
    strike: legStrike(leg),
    expiry: firstDefined(leg?.expiry, leg?.expiry_at, item?.expiry_at),
    valuation_time: firstDefined(leg?.valuation_time, leg?.quote_timestamp, item?.quote_timestamp),
    spot: firstDefined(leg?.spot, leg?.spot_price, item?.spot_price),
    iv: firstDefined(leg?.iv, leg?.fair_iv, leg?.market_iv, item?.fair_iv),
    risk_free_rate: firstDefined(
      leg?.risk_free_rate,
      activeScanContext?.assumptions?.risk_free_rate,
      Number(form.elements.risk_free_rate_pct?.value || 5) / 100,
    ),
    bid: firstDefined(leg?.bid, leg?.bid_price, item?.bid_price),
    ask: firstDefined(leg?.ask, leg?.ask_price, item?.ask_price),
    position: inferredLegPosition(item?.strategy, leg, legs),
  };
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

function strategyTakeaway(item, legs) {
  const asset = firstDefined(item?.asset, "tài sản");
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
  const card = document.createElement("article");
  card.className = "explanation-card";

  const heading = document.createElement("div");
  heading.className = "explanation-heading";
  const title = document.createElement("h3");
  title.textContent = `${index + 1}. ${firstDefined(item?.asset, "—")} · ${strategyLabel(item?.strategy)}`;
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = `${legs.length} chân`;
  heading.append(title, badge);
  card.appendChild(heading);

  const takeaway = document.createElement("p");
  takeaway.className = "explanation-takeaway";
  takeaway.textContent = strategyTakeaway(item, legs);
  card.appendChild(takeaway);
  if (item?.risk_note) {
    const riskNote = document.createElement("p");
    riskNote.className = "explanation-extra muted";
    riskNote.textContent = `Lưu ý: ${item.risk_note}`;
    card.appendChild(riskNote);
  }

  const legList = document.createElement("div");
  legList.className = "explanation-legs";
  legs.forEach((leg) => {
    const position = inferredLegPosition(item?.strategy, leg, legs);
    const legLine = document.createElement("span");
    legLine.className = position > 0 ? "buy-leg" : "sell-leg";
    const action = position > 0 ? "Mua" : "Bán";
    const strike = legStrike(leg);
    legLine.textContent = `${action} K${strike === undefined ? "—" : number(strike, 2)} ${optionTypeLabel(leg)}`;
    legList.appendChild(legLine);
  });
  card.appendChild(legList);

  const executablePrice = firstDefined(item?.executable_entry, item?.market_mid);
  const fairPrice = firstDefined(item?.fair_price);
  const edge = Number(item?.edge_after_costs);
  const facts = document.createElement("div");
  facts.className = "explanation-facts";
  facts.append(
    explanationFact("Tiền vào/ra ước tính", signedPriceLabel(executablePrice)),
    explanationFact("Mô hình định giá", signedPriceLabel(fairPrice)),
    explanationFact("Edge sau phí", Number.isFinite(edge) ? `${edge >= 0 ? "+" : ""}${number(edge, 4)}` : "—", edge >= 0 ? "positive" : "negative"),
    explanationFact("Lỗ tối đa", number(item?.max_loss, 2), "negative"),
  );
  card.appendChild(facts);

  const extra = document.createElement("p");
  extra.className = "explanation-extra muted";
  const maxProfit = item?.max_profit;
  const breakevens = Array.isArray(item?.breakevens) ? item.breakevens : [];
  const parts = [];
  if (maxProfit !== undefined && maxProfit !== null) parts.push(`Lãi tối đa: ${number(maxProfit, 2)}`);
  if (breakevens.length) parts.push(`Hòa vốn: ${breakevens.map((value) => `K${number(value, 2)}`).join(" và ")}`);
  parts.push(`IV edge: ${percent(item?.iv_edge)}`);
  extra.textContent = parts.join(" · ");
  card.appendChild(extra);
  return card;
}

function scenarioHorizonDays(item) {
  const dte = Number(item?.dte);
  if (Number.isFinite(dte) && dte > 0) return dte;
  const expiry = Date.parse(opportunityExpiry(item) || "");
  const valuation = Date.parse(firstDefined(item?.quote_timestamp, new Date().toISOString()));
  const derived = (expiry - valuation) / 86_400_000;
  return Number.isFinite(derived) && derived > 0 ? derived : 1;
}

function scenarioTimePoints(item) {
  const horizon = Math.max(0.25, scenarioHorizonDays(item));
  const pointCount = Math.min(13, Math.max(2, Math.ceil(horizon) + 1));
  return Array.from({ length: pointCount }, (_, index) => {
    if (index === pointCount - 1) return horizon;
    return Math.round((horizon * index / (pointCount - 1)) * 10) / 10;
  });
}

function buildAutomaticScenarioSet(item) {
  const timePoints = scenarioTimePoints(item);
  const scenarios = PNL_PATHS.flatMap((path) => timePoints.map((elapsedDays) => ({
    name: `${path.key} · Ngày ${number(elapsedDays, 1)}`,
    underlying_move_pct: path.move,
    iv_move: 0,
    elapsed_days: elapsedDays,
  })));
  return { horizon: timePoints[timePoints.length - 1], paths: PNL_PATHS, timePoints, scenarios };
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

function dayLabel(value) {
  const amount = Number(value);
  return Number.isInteger(amount) ? String(amount) : number(amount, 1);
}

function showPnlTooltip(path, scenario, event) {
  if (!pnlChartTooltip || !pnlChartShell) return;
  const shellBounds = pnlChartShell.getBoundingClientRect();
  const left = Math.min(Math.max(event.clientX - shellBounds.left + 12, 8), Math.max(8, shellBounds.width - 180));
  const top = Math.min(Math.max(event.clientY - shellBounds.top - 62, 8), Math.max(8, shellBounds.height - 70));
  pnlChartTooltip.textContent = `${path.label} · Ngày ${dayLabel(scenario.elapsed_days)}\nP&L: ${number(scenario.pnl, 2)}`;
  pnlChartTooltip.style.left = `${left}px`;
  pnlChartTooltip.style.top = `${top}px`;
  pnlChartTooltip.hidden = false;
}

function addPnlChartLegend(groups) {
  pnlChartLegend.replaceChildren();
  groups.filter((group) => group.points.length).forEach((group) => {
    const item = document.createElement("span");
    item.className = "chart-legend-item";
    const swatch = document.createElement("span");
    swatch.className = "chart-legend-swatch";
    swatch.style.backgroundColor = group.path.color;
    const label = document.createElement("span");
    label.textContent = group.path.label;
    item.append(swatch, label);
    pnlChartLegend.appendChild(item);
  });
}

function renderPnlChart(report, spec) {
  pnlChart.replaceChildren();
  pnlChartLegend.replaceChildren();
  pnlChartTooltip.hidden = true;
  const scenarios = (report.scenarios || []).filter((scenario) => Number.isFinite(Number(scenario.pnl)));
  if (!scenarios.length) {
    pnlChartStatus.textContent = "Chưa có dữ liệu";
    return;
  }

  const groups = spec.paths.map((path) => ({
    path,
    points: scenarios
      .filter((scenario) => String(scenario.name || "").startsWith(`${path.key} ·`))
      .sort((left, right) => Number(left.elapsed_days) - Number(right.elapsed_days)),
  }));
  if (!groups.some((group) => group.points.length)) groups[2].points = scenarios;
  addPnlChartLegend(groups);

  const width = 960;
  const height = 430;
  const margin = { top: 24, right: 24, bottom: 58, left: 72 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const values = [0, ...scenarios.map((scenario) => Number(scenario.pnl))];
  let minPnl = Math.min(...values);
  let maxPnl = Math.max(...values);
  const pnlSpan = Math.max(maxPnl - minPnl, 1);
  minPnl -= pnlSpan * 0.12;
  maxPnl += pnlSpan * 0.12;
  const horizon = Math.max(spec.horizon, ...scenarios.map((scenario) => Number(scenario.elapsed_days) || 0), 0.25);
  const x = (day) => margin.left + (Number(day) / horizon) * innerWidth;
  const y = (pnl) => margin.top + ((maxPnl - Number(pnl)) / (maxPnl - minPnl)) * innerHeight;

  pnlChart.setAttribute("aria-label", `Biểu đồ P&L theo thời gian, từ ngày 0 đến ngày ${dayLabel(horizon)}`);
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

  const xTicks = spec.timePoints.length <= 7
    ? spec.timePoints
    : spec.timePoints.filter((_value, index) => index === 0 || index === spec.timePoints.length - 1 || index % 2 === 0);
  xTicks.forEach((day) => {
    const xPosition = x(day);
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
    }, day === 0 ? "Hôm nay" : `Ngày ${dayLabel(day)}`));
  });

  pnlChart.append(
    svgNode("line", { x1: margin.left, x2: margin.left, y1: margin.top, y2: height - margin.bottom, stroke: "#526273" }),
    svgNode("line", { x1: margin.left, x2: width - margin.right, y1: height - margin.bottom, y2: height - margin.bottom, stroke: "#526273" }),
    svgNode("text", { x: 18, y: margin.top + innerHeight / 2, fill: "#9aabb8", "font-size": 12, transform: `rotate(-90 18 ${margin.top + innerHeight / 2})`, "text-anchor": "middle" }, "P&L"),
    svgNode("text", { x: margin.left + innerWidth / 2, y: height - 10, fill: "#9aabb8", "font-size": 12, "text-anchor": "middle" }, "Thời gian trôi qua"),
  );

  const todayX = x(0);
  const expiryX = x(horizon);
  pnlChart.append(
    svgNode("line", { x1: todayX, x2: todayX, y1: margin.top, y2: height - margin.bottom, stroke: "#62d4a4", "stroke-dasharray": "4 5" }),
    svgNode("line", { x1: expiryX, x2: expiryX, y1: margin.top, y2: height - margin.bottom, stroke: "#f0bb87", "stroke-dasharray": "4 5" }),
  );

  groups.forEach((group) => {
    if (!group.points.length) return;
    const pathData = group.points.map((scenario, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command} ${x(scenario.elapsed_days).toFixed(2)} ${y(scenario.pnl).toFixed(2)}`;
    }).join(" ");
    pnlChart.appendChild(svgNode("path", {
      d: pathData,
      fill: "none",
      stroke: group.path.color,
      "stroke-width": 2.5,
      "stroke-linejoin": "round",
      "stroke-linecap": "round",
    }));
    group.points.forEach((scenario) => {
      const point = svgNode("circle", {
        cx: x(scenario.elapsed_days),
        cy: y(scenario.pnl),
        r: 4,
        fill: group.path.color,
        stroke: "#0f151c",
        "stroke-width": 1.5,
        tabindex: 0,
      });
      point.addEventListener("pointerenter", (event) => showPnlTooltip(group.path, scenario, event));
      point.addEventListener("pointerleave", () => { pnlChartTooltip.hidden = true; });
      point.addEventListener("focus", () => {
        pnlChartTooltip.textContent = `${group.path.label} · Ngày ${dayLabel(scenario.elapsed_days)}\nP&L: ${number(scenario.pnl, 2)}`;
        pnlChartTooltip.hidden = false;
      });
      point.addEventListener("blur", () => { pnlChartTooltip.hidden = true; });
      pnlChart.appendChild(point);
    });
  });
  pnlChartStatus.textContent = "Mô phỏng tự động";
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

function renderScenarioReport(report, spec) {
  renderPnlChart(report, spec);
  scenarioResultsBody.replaceChildren();
  detailMetrics.replaceChildren();
  detailMetrics.append(
    metric("Lỗ tối đa", number(report.max_loss, 2), "negative"),
    metric("Lãi tối đa", number(report.max_profit, 2), "positive"),
    metric("Điểm hòa vốn", (report.breakevens || []).map((value) => number(value, 2)).join(", ") || "—"),
  );
  (report.scenarios || []).forEach((scenario) => {
    const row = document.createElement("tr");
    const greeks = scenario.greeks || {};
    cell(row, scenario.name || "Kịch bản");
    cell(row, number(scenario.underlying_price, 2));
    cell(row, percent(scenario.implied_volatility));
    cell(row, number(scenario.elapsed_days, 1));
    cell(row, number(scenario.pnl, 2), scenario.pnl >= 0 ? "positive" : "negative");
    cell(row, number(greeks.delta, 4));
    cell(row, number(greeks.gamma, 4));
    cell(row, number(greeks.theta, 4));
    cell(row, number(greeks.vega, 4));
    cell(row, number(greeks.rho, 4));
    scenarioResultsBody.appendChild(row);
  });
  if (report.scenarios && report.scenarios.length) {
    setScenarioState(`Đã dựng ${report.scenarios.length} điểm mô phỏng từ hôm nay đến ngày đáo hạn.`);
  } else {
    setScenarioState("API không trả về kịch bản nào.", "error");
  }
}

async function showOpportunityDetail(item) {
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
  setScenarioState("Đang tự động mô phỏng P&L theo thời gian…");
  detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });

  const requestId = ++scenarioRequestId;
  const spec = buildAutomaticScenarioSet(item);
  pnlChartAssumptions.textContent = `Mô phỏng tự động từ ngày 0 đến ngày ${dayLabel(spec.horizon)}: giá cơ sở được stress ở −10%, −5%, 0%, +5%, +10% so với hiện tại và IV giữ nguyên. Đây là mô phỏng tham khảo, không phải dự đoán đường giá.`;
  try {
    const report = await getJson("/api/v1/scenarios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy_type: scenarioStrategyType(item.strategy),
        legs: legs.map((leg) => scenarioLeg(item, leg, legs)),
        scenarios: spec.scenarios,
        execution: {
          fee_per_contract: Number(activeScanContext?.assumptions?.fee_per_contract ?? form.elements.fee_per_contract.value),
          slippage_bps: Number(activeScanContext?.assumptions?.slippage_bps ?? form.elements.slippage_bps.value),
          contract_multiplier: Number(activeScanContext?.assumptions?.contract_multiplier ?? form.elements.contract_multiplier.value),
          exit_price_source: "model",
        },
      }),
    });
    if (requestId === scenarioRequestId && selectedOpportunity === item) renderScenarioReport(report, spec);
  } catch (error) {
    if (requestId !== scenarioRequestId || selectedOpportunity !== item) return;
    pnlChartStatus.textContent = "Không có dữ liệu";
    setScenarioState(error.message, "error");
  }
}

function renderAssets(payload) {
  assetList.replaceChildren();
  const assets = payload.assets || [];
  if (!assets.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "Không tìm thấy tài sản đang giao dịch.";
    assetList.appendChild(empty);
    return;
  }
  const preferredAsset = assets.find((asset) => asset.base_coin === "BTC") || assets[0];
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
  });
  return (payload.issues || []).length;
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
  const assumptions = context.assumptions || {};
  const appliedFilters = context.applied_filters || {};
  const maxLoss = context.max_loss === null || context.max_loss === undefined
    ? "không giới hạn"
    : number(context.max_loss, 2);
  const edgeText = Number(appliedFilters.min_iv_edge) > 0
    ? ` · Edge IV tối thiểu: ${percent(appliedFilters.min_iv_edge)}`
    : "";
  scanContext.textContent = `${context.summary || `Đã dùng: ${views[context.market_view] || "Tùy chỉnh"} · ${horizons[context.time_horizon] || "Thời hạn tùy chỉnh"}`} · Chiến lược: ${strategies || "mặc định"} · Lỗ tối đa: ${maxLoss}${edgeText} · Lãi suất: ${percent(assumptions.risk_free_rate ?? context.risk_free_rate)} · Phí: ${number(assumptions.fee_per_contract, 2)} mỗi chiều · Trượt giá: ${number(assumptions.slippage_bps, 0)} bps`;
  scanContext.hidden = false;
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

function renderResults(payload) {
  activeScanContext = payload.scan_context || null;
  resultsBody.replaceChildren();
  secondaryResults.replaceChildren();
  opportunityExplanations.replaceChildren();
  renderScanContext(payload.scan_context);
  detailPanel.hidden = true;
  selectedOpportunity = null;
  const opportunities = payload.opportunities || [];
  resultsGuide.hidden = !opportunities.length;
  if (!opportunities.length) setState("Không có cơ hội đạt đủ điều kiện hiện tại.");
  else setState(`${opportunities.length} cơ hội đạt điều kiện.`);
  opportunities.forEach((item, index) => {
    opportunityExplanations.appendChild(renderOpportunityExplanation(item, index));
    const row = document.createElement("tr");
    renderInstrumentCell(row, item);
    cell(row, expiryLabel(item));
    cell(row, strategyLabel(item.strategy));
    cell(row, number(item.market_mid));
    cell(row, number(item.fair_price));
    cell(row, percent(item.iv_edge), item.iv_edge >= 0 ? "positive" : "negative");
    cell(row, number(item.edge_after_costs), item.edge_after_costs >= 0 ? "positive" : "negative");
    cell(row, number(item.max_loss));
    cell(row, `OI ${number(item.open_interest, 0)} · Vol ${number(item.volume_24h, 0)}`);
    const actionCell = document.createElement("td");
    const detailButton = document.createElement("button");
    detailButton.type = "button";
    detailButton.className = "secondary-button compact-button";
    detailButton.textContent = "Xem P&L";
    detailButton.addEventListener("click", () => showOpportunityDetail(item));
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
  const data = new FormData(form);
  const useAdvancedStrategies = data.get("use_advanced_strategies") === "on";
  const strategies = useAdvancedStrategies
    ? data.getAll("strategies")
    : [data.get("quick_strategy") || "long_call"];
  const assets = data.getAll("assets");
  if (!assets.length) {
    setState("Hãy chọn ít nhất một tài sản để quét.", "error");
    return;
  }
  const horizon = selectedTimeHorizon(data.get("time_horizon"));
  const simpleContext = simpleScanContext(data.get("quick_strategy"), data.get("time_horizon"));
  const payload = {
    risk_free_rate: useAdvancedStrategies
      ? optionalDecimal(data, "risk_free_rate_pct", 100) ?? 0.05
      : 0.05,
    assets, strategies,
    min_dte: useAdvancedStrategies ? optionalNumber(data, "min_dte") : horizon.min_dte,
    max_dte: useAdvancedStrategies ? optionalNumber(data, "max_dte") : horizon.max_dte,
    min_iv_edge: useAdvancedStrategies
      ? optionalDecimal(data, "min_iv_edge", 100) || 0
      : optionalDecimal(data, "quick_target_edge_pct", 100) || 0,
    max_loss: useAdvancedStrategies ? optionalNumber(data, "max_loss") : optionalNumber(data, "quick_max_loss"),
    include_unvalidated: true,
  };
  if (!useAdvancedStrategies) Object.assign(payload, simpleContext);
  if (useAdvancedStrategies) {
    Object.assign(payload, {
      min_delta: optionalNumber(data, "min_delta"),
      max_delta: optionalNumber(data, "max_delta"),
      min_volume_24h: Number(data.get("min_volume_24h")),
      min_open_interest: Number(data.get("min_open_interest")),
      max_spread_pct: optionalDecimal(data, "max_spread_pct", 100),
      min_edge_after_costs: Number(data.get("min_edge_after_costs")),
      max_results: optionalNumber(data, "max_results"),
      fee_per_contract: Number(data.get("fee_per_contract")),
      slippage_bps: Number(data.get("slippage_bps")),
      quantity: Number(data.get("quantity")),
      contract_multiplier: Number(data.get("contract_multiplier")),
    });
  }
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

clearTerminalButton.addEventListener("click", clearTerminal);

closeDetailButton.addEventListener("click", () => {
  scenarioRequestId += 1;
  detailPanel.hidden = true;
  selectedOpportunity = null;
});

loadAssets();
