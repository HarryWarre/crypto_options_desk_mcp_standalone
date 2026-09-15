const serviceStatus = document.querySelector("#service-status");
const dataStatus = document.querySelector("#data-status");
const assetList = document.querySelector("#asset-list");
const form = document.querySelector("#scan-form");
const resultState = document.querySelector("#result-state");
const resultsBody = document.querySelector("#results-body");
const secondaryResults = document.querySelector("#secondary-results");
const evidenceStatus = document.querySelector("#evidence-status");
const detailPanel = document.querySelector("#opportunity-detail");
const detailSummary = document.querySelector("#detail-summary");
const closeDetailButton = document.querySelector("#close-detail");
const scenarioForm = document.querySelector("#scenario-form");
const scenarioState = document.querySelector("#scenario-state");
const detailMetrics = document.querySelector("#detail-metrics");
const scenarioResultsBody = document.querySelector("#scenario-results-body");
const scenarioWarnings = document.querySelector("#scenario-warnings");

let selectedOpportunity = null;

function setState(message, className = "") {
  resultState.textContent = message;
  resultState.className = `state-message ${className}`.trim();
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

function setScenarioState(message, className = "") {
  scenarioState.textContent = message;
  scenarioState.className = `state-message ${className}`.trim();
}

function scenarioStatus(status) {
  return {
    ok: "Đã tính",
    model_only: "Chỉ dùng mô hình",
    extrapolated: "Ngoại suy bề mặt",
  }[status] || status || "—";
}

function warningText(warning) {
  const labels = {
    model_only: "Chỉ dùng mô hình, chưa có bề mặt biến động",
    surface_extrapolated: "IV nằm ngoài vùng quan sát của bề mặt biến động",
    execution_costs: "P&L đã tính phí và trượt giá theo giả định",
  };
  const message = labels[warning.code] || warning.message || "Có cảnh báo chưa xác định";
  return warning.symbol ? `${message} (${warning.symbol})` : message;
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

function renderWarnings(warnings) {
  scenarioWarnings.replaceChildren();
  (warnings || []).forEach((warning) => {
    const item = document.createElement("div");
    item.className = "warning-item";
    item.textContent = warningText(warning);
    scenarioWarnings.appendChild(item);
  });
}

function renderScenarioReport(report) {
  scenarioResultsBody.replaceChildren();
  detailMetrics.replaceChildren();
  detailMetrics.append(
    metric("Trạng thái", scenarioStatus(report.status)),
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
  renderWarnings(report.warnings);
  if (report.scenarios && report.scenarios.length) {
    setScenarioState("Đã tính theo giả định mô hình; đây chưa phải bằng chứng EV dương.");
  } else {
    setScenarioState("API không trả về kịch bản nào.", "error");
  }
}

function showOpportunityDetail(item) {
  selectedOpportunity = item;
  detailPanel.hidden = false;
  detailSummary.textContent = `${item.asset} · ${item.symbol} · ${item.strategy === "long_call" ? "Mua call" : "Mua put"}`;
  scenarioResultsBody.replaceChildren();
  detailMetrics.replaceChildren();
  scenarioWarnings.replaceChildren();
  setScenarioState("Điều chỉnh kịch bản rồi bấm “Tính P&L”.");
  detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
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
  assets.forEach((asset) => {
    const label = document.createElement("label");
    label.className = "asset-choice";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "assets";
    input.value = asset.base_coin;
    input.checked = true;
    label.append(input, document.createTextNode(`${asset.base_coin} (${asset.contract_count})`));
    assetList.appendChild(label);
  });
  return (payload.issues || []).length;
}

async function getJson(path, options = {}) {
  const response = await fetch(path, { headers: { "Accept": "application/json" }, ...options });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { error: { message: await response.text() } };
  if (!response.ok) throw new Error(payload?.error?.message || "Yêu cầu thất bại");
  return payload;
}

function optionalNumber(formData, name) {
  const value = formData.get(name);
  return value === "" || value === null ? null : Number(value);
}

function renderResults(payload) {
  resultsBody.replaceChildren();
  secondaryResults.replaceChildren();
  detailPanel.hidden = true;
  selectedOpportunity = null;
  const opportunities = payload.opportunities || [];
  evidenceStatus.textContent = payload.evidence_gate_status === "blocked_unvalidated" ? "Đã chặn: chưa kiểm định" : "Chưa kiểm định EV";
  if (!opportunities.length) setState("Không có cơ hội đạt đủ điều kiện hiện tại.");
  else setState(`${opportunities.length} tín hiệu nghiên cứu, chưa phải lệnh giao dịch.`);
  opportunities.forEach((item) => {
    const row = document.createElement("tr");
    cell(row, `${item.asset} · ${item.symbol}`, "symbol");
    cell(row, new Date(item.expiry_at).toLocaleString("vi-VN"));
    cell(row, item.strategy === "long_call" ? "Mua call" : "Mua put");
    cell(row, number(item.market_mid));
    cell(row, number(item.fair_price));
    cell(row, percent(item.iv_edge), item.iv_edge >= 0 ? "positive" : "negative");
    cell(row, number(item.edge_after_costs), item.edge_after_costs >= 0 ? "positive" : "negative");
    cell(row, number(item.max_loss));
    cell(row, `OI ${number(item.open_interest, 0)} · Vol ${number(item.volume_24h, 0)}`);
    cell(row, item.evidence_status === "not_validated" ? "Chưa kiểm định" : "Thiếu bằng chứng");
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
  const issues = payload.issues || [];
  if (issues.length) {
    const item = document.createElement("div");
    item.textContent = `${issues.length} cảnh báo chất lượng dữ liệu được giữ lại trong kết quả.`;
    secondaryResults.appendChild(item);
  }
  dataStatus.textContent = payload.data_timestamp ? `Dữ liệu: ${new Date(payload.data_timestamp).toLocaleString("vi-VN")}` : "Đã nhận dữ liệu";
}

async function loadAssets() {
  try {
    const payload = await getJson("/api/v1/assets");
    const issueCount = renderAssets(payload);
    serviceStatus.textContent = issueCount
      ? `API đang hoạt động · ${issueCount} cảnh báo dữ liệu`
      : "API đang hoạt động";
  } catch (error) {
    serviceStatus.textContent = "API không sẵn sàng";
    serviceStatus.classList.add("error");
    setState(error.message, "error");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  const data = new FormData(form);
  const strategies = data.getAll("strategies");
  const assets = data.getAll("assets");
  if (!assets.length) {
    setState("Hãy chọn ít nhất một tài sản để quét.", "error");
    return;
  }
  const payload = {
    risk_free_rate: Number(data.get("risk_free_rate")), assets, strategies,
    min_dte: optionalNumber(data, "min_dte"), max_dte: optionalNumber(data, "max_dte"),
    min_delta: optionalNumber(data, "min_delta"), max_delta: optionalNumber(data, "max_delta"),
    min_volume_24h: Number(data.get("min_volume_24h")), min_open_interest: Number(data.get("min_open_interest")),
    min_iv_edge: Number(data.get("min_iv_edge")), max_spread_pct: optionalNumber(data, "max_spread_pct"),
    min_edge_after_costs: Number(data.get("min_edge_after_costs")), max_loss: optionalNumber(data, "max_loss"),
    max_results: optionalNumber(data, "max_results"), fee_per_contract: Number(data.get("fee_per_contract")),
    slippage_bps: Number(data.get("slippage_bps")), quantity: Number(data.get("quantity")),
    contract_multiplier: Number(data.get("contract_multiplier")),
    include_unvalidated: data.has("include_unvalidated"),
  };
  button.disabled = true;
  setState("Đang lấy dữ liệu và dựng bề mặt biến động…");
  try {
    renderResults(await getJson("/api/v1/opportunities/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }));
  } catch (error) {
    setState(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

closeDetailButton.addEventListener("click", () => {
  detailPanel.hidden = true;
  selectedOpportunity = null;
});

scenarioForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedOpportunity) {
    setScenarioState("Hãy chọn một cơ hội trước.", "error");
    return;
  }
  const data = new FormData(scenarioForm);
  const scenario = {
    name: "Kịch bản tùy chỉnh",
    underlying_move_pct: Number(data.get("underlying_move_pct")),
    iv_move: Number(data.get("iv_move_points")) / 100,
    elapsed_days: Number(data.get("elapsed_days")),
  };
  const payload = {
    strategy_type: selectedOpportunity.strategy,
    legs: [{
      symbol: selectedOpportunity.symbol,
      option_type: selectedOpportunity.option_type,
      strike: selectedOpportunity.strike,
      expiry: selectedOpportunity.expiry_at,
      valuation_time: selectedOpportunity.quote_timestamp,
      spot: selectedOpportunity.spot_price,
      iv: selectedOpportunity.fair_iv,
      risk_free_rate: Number(form.elements.risk_free_rate.value),
      bid: selectedOpportunity.bid_price,
      ask: selectedOpportunity.ask_price,
      position: 1,
    }],
    scenarios: [scenario],
    execution: {
      fee_per_contract: Number(form.elements.fee_per_contract.value),
      slippage_bps: Number(form.elements.slippage_bps.value),
      contract_multiplier: Number(form.elements.contract_multiplier.value),
      exit_price_source: "model",
    },
  };
  const button = scenarioForm.querySelector("button[type=submit]");
  button.disabled = true;
  setScenarioState("Đang tính P&L và Greeks…");
  try {
    renderScenarioReport(await getJson("/api/v1/scenarios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }));
  } catch (error) {
    setScenarioState(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

loadAssets();
