const serviceStatus = document.querySelector("#service-status");
const dataStatus = document.querySelector("#data-status");
const assetList = document.querySelector("#asset-list");
const form = document.querySelector("#scan-form");
const resultState = document.querySelector("#result-state");
const resultsBody = document.querySelector("#results-body");
const secondaryResults = document.querySelector("#secondary-results");
const evidenceStatus = document.querySelector("#evidence-status");

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
  return Number(value).toFixed(digits);
}

function percent(value) {
  return value === null || value === undefined ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
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

loadAssets();
