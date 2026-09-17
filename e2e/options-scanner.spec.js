const { test, expect } = require("@playwright/test");

const opportunity = {
  asset: "BTC",
  symbol: "BTC-30OCT26-73000-C-USDT",
  strategy: "long_call",
  option_type: "Call",
  strike: 73000,
  expiry_at: "2026-10-30T08:00:00Z",
  spot_price: 76227.9,
  bid_price: 5835,
  ask_price: 5910,
  market_mid: 5872.5,
  market_iv: 0.3889,
  fair_iv: 0.3891,
  iv_edge: 0.0002,
  fair_price: 6138.3,
  edge_after_costs: 228.3,
  max_loss: 5910,
  max_profit: null,
  expected_value: 228.3,
  win_probability: 0.54,
  risk_reward: null,
  breakevens: [79100],
  methodology: "Payoff dùng giá vào/ra và chi phí của lần quét.",
  payoff_curve: [
    { underlying_price: 65000, pnl: -5910 },
    { underlying_price: 73000, pnl: -5910 },
    { underlying_price: 79100, pnl: 0 },
    { underlying_price: 85000, pnl: 5900 },
  ],
  volume_24h: 39,
  open_interest: 19.53,
  quote_timestamp: "2026-09-15T14:46:33Z",
  dte: 45,
  legs: [{
    symbol: "BTC-30OCT26-73000-C-USDT",
    option_type: "Call",
    strike: 73000,
    expiry_at: "2026-10-30T08:00:00Z",
    spot_price: 76227.9,
    fair_iv: 0.3891,
    bid_price: 5835,
    ask_price: 5910,
    position: 1,
  }],
};

const theoreticalVerticalOpportunity = {
  ...opportunity,
  asset: "DOGE",
  symbol: "DOGE-30OCT26-0.07-C/DOGE-30OCT26-0.14-C",
  strategy: "bull_call_vertical",
  option_type: "multi",
  valuation_mode: "theoretical",
  bid_price: 0.009,
  ask_price: 0.011,
  market_mid: 0.01,
  fair_price: 0.01,
  edge_after_costs: null,
  max_loss: 0.01,
  max_profit: 0.06,
  expected_value: 0.02,
  win_probability: 0.45,
  risk_reward: 1.2,
  breakevens: [0.08],
  payoff_curve: [
    { underlying_price: 0, pnl: -0.01 },
    { underlying_price: 0.07, pnl: -0.01 },
    { underlying_price: 0.08, pnl: 0 },
    { underlying_price: 0.14, pnl: 0.06 },
  ],
  legs: [
    {
      ...opportunity.legs[0],
      symbol: "DOGE-30OCT26-0.07-C",
      strike: 0.07,
      expiry_at: "2026-10-30T08:00:00Z",
      position: 1,
    },
    {
      ...opportunity.legs[0],
      symbol: "DOGE-30OCT26-0.14-C",
      strike: 0.14,
      expiry_at: "2026-10-30T08:00:00Z",
      position: -1,
    },
  ],
};

const syntheticOpportunity = {
  ...theoreticalVerticalOpportunity,
  valuation_mode: "synthetic",
  bid_price: 0.0105,
  ask_price: 0.0115,
  market_mid: 0.011,
  edge_after_costs: 0.004,
  estimated_entry: 0.0115,
  quote_source: "synthetic_mark_or_fair_value",
};

async function mockApi(page) {
  await page.route("**/api/v1/assets", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      assets: [{ base_coin: "BTC", status: "Trading", contract_count: 700 }],
      issues: [],
      fetched_at: "2026-09-15T14:46:33Z",
    }),
  }));

  await page.route("**/api/v1/opportunities/scan/stream", async (route) => {
    const body = route.request().postDataJSON();

    if (Number(body.max_loss) === 2) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "scanner_unavailable",
            message: "Không thể hoàn tất lượt quét. Vui lòng thử lại.",
          },
        }),
      });
      return;
    }

    const empty = Number(body.max_loss) === 1;
    const payload = {
      timestamp: "2026-09-15T14:46:33Z",
      data_timestamp: "2026-09-15T14:46:33Z",
      valuation_mode: body.valuation_mode || "executable",
      opportunities: empty ? [] : [body.valuation_mode === "theoretical" ? theoreticalVerticalOpportunity : body.valuation_mode === "synthetic" ? syntheticOpportunity : opportunity],
      rejections: [],
      asset_failures: [],
      issues: [],
      evidence_status: "insufficient_evidence",
      evidence_gate_status: "open_unvalidated_signals",
      execution_allowed: false,
      scan_context: {
        market_view: body.market_view || "up",
        time_horizon: body.time_horizon || "7_30",
        max_loss: Number(body.max_loss) || null,
        strategies: body.strategies || ["long_call"],
        strategy_preference: body.strategy_preference || null,
        assumptions: {
          risk_free_rate: Number(body.risk_free_rate) || 0.05,
          fee_per_contract: 2.5,
          slippage_bps: 7,
          assumed_spread_bps: Number(body.assumed_spread_bps) || 100,
          quantity: 1,
          contract_multiplier: 1,
          include_unvalidated: true,
        },
        applied_filters: {
          min_dte: body.min_dte,
          max_dte: body.max_dte,
          min_iv_edge: body.min_iv_edge || 0,
          min_expected_value: body.min_expected_value === null ? null : Number(body.min_expected_value || 0),
        },
      },
    };
    const events = [
      { type: "log", message: "[OPTIONS] scan started" },
      { type: "log", message: "[OPTIONS] scan completed" },
      { type: "result", payload },
    ];

    await route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
    });
  });

}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Crypto Options Scanner" })).toBeVisible();
  await expect(page.getByText("BTC", { exact: false }).first()).toBeVisible();
});

test("shows only beginner controls in the quick scan by default", async ({ page }) => {
  const quickControls = page.locator("#scan-form");

  await expect(quickControls).toBeVisible();
  await expect(page.getByRole("group", { name: "Tài sản" })).toBeVisible();
  await expect(page.getByLabel("Thời hạn")).toBeVisible();
  await expect(page.getByLabel("Lỗ tối đa mỗi ý tưởng")).toBeVisible();
  await expect(page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ })).toBeVisible();
  await expect(page.getByRole("group", { name: "Bạn muốn tìm ý tưởng nào?" })).toBeVisible();
  await expect(page.locator('.strategy-card input[type="checkbox"]')).toHaveCount(13);

  const advancedFilters = page.getByTestId("advanced-filters");
  await expect(advancedFilters.locator(".advanced-content")).not.toBeVisible();
  await expect(page.getByLabel("IV edge tối thiểu")).not.toBeVisible();
  await expect(page.getByLabel("Delta tối thiểu")).not.toBeVisible();
  await expect(page.getByLabel("Phí mỗi chiều")).not.toBeVisible();
});

test("shows strategy checkbox cards and keeps all strategy choices available", async ({ page }) => {
  const strategyPicker = page.getByRole("group", { name: "Bạn muốn tìm ý tưởng nào?" });

  for (const strategy of [
    "long_call",
    "long_put",
    "call_vertical",
    "put_vertical",
    "iron_condor",
    "iron_butterfly",
    "long_straddle",
    "long_strangle",
    "protective_put",
    "covered_call",
    "calendar_spread",
    "butterfly",
    "broken_wing_butterfly",
  ]) {
    await expect(strategyPicker.locator(`input[type="checkbox"][value="${strategy}"]`)).toBeVisible();
  }

  await expect(strategyPicker).toContainText("có thể chọn nhiều chiến lược");
});

test("keeps advanced filters collapsed until the user expands them", async ({ page }) => {
  const advancedFilters = page.getByTestId("advanced-filters");
  const toggle = advancedFilters.locator("summary");

  await expect(advancedFilters).not.toHaveAttribute("open");
  await expect(advancedFilters.locator(".advanced-content")).not.toBeVisible();

  await toggle.click();

  await expect(advancedFilters).toHaveAttribute("open", "");
  await expect(advancedFilters.locator(".advanced-content")).toBeVisible();
  await expect(advancedFilters.getByLabel("IV edge tối thiểu (%)")).toBeVisible();
  await expect(advancedFilters.getByLabel("Delta tối thiểu")).toBeVisible();
  await expect(advancedFilters.getByLabel("Bid–ask tối đa (%)")).toBeVisible();
  await expect(advancedFilters.getByLabel("Phí mỗi chiều")).toBeVisible();
  await expect(advancedFilters.getByLabel("Lãi suất mô hình (%/năm)")).toBeVisible();
});

test("submits a backend-compatible quick-scan payload and renders results", async ({ page }) => {
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1000");

  const scanRequest = page.waitForRequest((request) => (
    request.url().includes("/api/v1/opportunities/scan/stream")
  ));
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  const payload = (await scanRequest).postDataJSON();

  expect(payload).toMatchObject({
    assets: ["BTC"],
    strategies: ["long_call"],
    market_view: "custom",
    time_horizon: "7_30",
    min_dte: 7,
    max_dte: 30,
    risk_free_rate: expect.any(Number),
    min_iv_edge: 0,
    max_loss: 1000,
    include_unvalidated: true,
  });

  await expect(page.locator("#results-body")).toContainText(opportunity.symbol);
  await expect(page.locator("#results-body")).toContainText("30/10/2026");
  await expect(page.locator("#results-body")).toContainText("Còn 45 ngày");
  await expect(page.locator("#opportunity-explanations")).toContainText("Kỳ vọng BTC tăng giá");
  await expect(page.locator("#scan-context")).toContainText("Nhiều chiến lược");
  await expect(page.locator("#result-state")).toContainText("1");
});

test("opts into theoretical valuation and labels the result as non-executable", async ({ page }) => {
  await expect(page.getByLabel("Executable — mặc định")).toBeChecked();
  await page.getByLabel("Theoretical — bỏ qua bid/ask").check();

  const scanRequest = page.waitForRequest((request) => (
    request.url().includes("/api/v1/opportunities/scan/stream")
  ));
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  expect((await scanRequest).postDataJSON()).toMatchObject({ valuation_mode: "theoretical" });

  await expect(page.locator("#valuation-mode-notice")).toBeVisible();
  await expect(page.locator("#valuation-mode-notice")).toContainText("không phải giá khớp");
  await expect(page.locator("#results-body")).toContainText("Tham khảo");
  await expect(page.getByRole("button", { name: "Xem payoff mô hình" })).toBeEnabled();
  await expect(page.locator("#opportunity-explanations")).toContainText("Hết hạn 30/10/2026");
  await expect(page.locator("#opportunity-explanations")).toContainText("EV mô hình");
  await page.getByRole("button", { name: "Xem payoff mô hình" }).click();
  await expect(page.locator("#opportunity-detail")).toBeVisible();
  await expect(page.locator("#detail-metrics")).toContainText("Lỗ tối đa (mô hình)");
});

test("opts into synthetic quotes and calculates the full estimated metrics", async ({ page }) => {
  await expect(page.getByLabel("Executable — mặc định")).toBeChecked();
  await page.getByLabel("Synthetic — spread giả định").check();
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1000");

  const scanRequest = page.waitForRequest((request) => (
    request.url().includes("/api/v1/opportunities/scan/stream")
  ));
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  expect((await scanRequest).postDataJSON()).toMatchObject({
    valuation_mode: "synthetic",
    assumed_spread_bps: 100,
  });

  await expect(page.locator("#valuation-mode-notice")).toBeVisible();
  await expect(page.locator("#valuation-mode-notice")).toContainText("spread giả định");
  await expect(page.locator("#results-body")).toContainText("Giả định");
  await expect(page.locator("#results-body")).toContainText("0.004");
  await expect(page.getByRole("button", { name: "Xem payoff tổng hợp" })).toBeEnabled();
  await page.getByRole("button", { name: "Xem payoff tổng hợp" }).click();
  await expect(page.locator("#detail-metrics")).toContainText("Lỗ tối đa (mô hình)");
});

test("submits selected strategy checkboxes, including spread group expansion", async ({ page }) => {
  await page.getByLabel("Mua call").uncheck();
  await page.getByLabel("Mua put").check();
  await page.getByLabel("Call spread").check();
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1000");
  const request = page.waitForRequest((candidate) => candidate.url().includes("/api/v1/opportunities/scan/stream"));
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  expect((await request).postDataJSON()).toMatchObject({
    market_view: "custom",
    strategies: ["long_put", "bull_call_vertical", "bear_call_vertical"],
  });
});

test("applies explicit Advanced overrides and shows them in the scan context", async ({ page }) => {
  const advancedFilters = page.getByTestId("advanced-filters");
  await advancedFilters.locator("summary").click();
  await page.getByLabel("Mua call").uncheck();
  await page.getByLabel("Mua put").check();
  await advancedFilters.getByLabel("Ngày tối thiểu").fill("10");
  await advancedFilters.getByLabel("Ngày tối đa").fill("20");
  await advancedFilters.getByLabel("Lãi suất mô hình (%/năm)").fill("7");
  await advancedFilters.getByLabel("EV tối thiểu").fill("12.5");
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1000");

  const request = page.waitForRequest((candidate) => candidate.url().includes("/api/v1/opportunities/scan/stream"));
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  expect((await request).postDataJSON()).toMatchObject({
    strategies: ["long_put"],
    min_dte: 10,
    max_dte: 20,
    risk_free_rate: 0.07,
    min_expected_value: 12.5,
  });
  await expect(page.locator("#scan-context")).toContainText("Lãi suất: 7.00%");
  await expect(page.locator("#scan-context")).toContainText("Trượt giá: 7 bps");
  await expect(page.locator("#scan-context")).toContainText("EV tối thiểu: 12.50");
});

test("can disable the EV gate by clearing the advanced threshold", async ({ page }) => {
  const advancedFilters = page.getByTestId("advanced-filters");
  await advancedFilters.locator("summary").click();
  await advancedFilters.locator('input[name="use_advanced_strategies"]').check();
  await advancedFilters.getByLabel("EV tối thiểu").fill("");
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1000");

  const request = page.waitForRequest((candidate) => candidate.url().includes("/api/v1/opportunities/scan/stream"));
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  expect((await request).postDataJSON().min_expected_value).toBeNull();
});

test("keeps scan controls within the viewport on desktop and mobile", async ({ page }) => {
  for (const viewport of [
    { width: 1280, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.reload();
    await expect(page.locator("#scan-form")).toBeVisible();

    const overflow = await page.locator("#scan-form").evaluate((form) => ({
      clientWidth: form.clientWidth,
      scrollWidth: form.scrollWidth,
    }));
    expect(overflow.scrollWidth, `controls overflow at ${viewport.width}px`).toBeLessThanOrEqual(overflow.clientWidth);
  }
});

test("explains an empty scan result", async ({ page }) => {
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1");
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();

  await expect(page.locator("#result-state")).toBeVisible();
  await expect(page.locator("#result-state")).toContainText("Không có cơ hội");
  await expect(page.locator("#results-body tr")).toHaveCount(0);
});

test("shows an understandable error when the scan service fails", async ({ page }) => {
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("2");
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();

  await expect(page.locator("#result-state")).toHaveText("Không thể hoàn tất lượt quét. Vui lòng thử lại.");
  await expect(page.locator("#scan-terminal")).toContainText("Không thể hoàn tất lượt quét");
});

test("renders API payoff curve and estimated outcome metrics from a quick-scan result", async ({ page }) => {
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1000");
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  await page.getByRole("button", { name: "Xem payoff" }).click();

  await expect(page.locator("#opportunity-detail")).toBeVisible();
  await expect(page.locator("#pnl-chart")).toBeVisible();
  await expect(page.locator("#pnl-chart")).toHaveAttribute("aria-label", /tại đáo hạn theo giá cơ sở/);
  await expect(page.locator('#pnl-chart line[stroke="#ef8f8f"]')).toHaveCount(1);
  await expect(page.locator("#pnl-chart-legend")).toContainText("P&L tại đáo hạn");
  await expect(page.locator("#detail-metrics")).toContainText("5910.00");
  await expect(page.locator("#detail-metrics")).toContainText("EV ước tính");
  await expect(page.locator("#detail-metrics")).toContainText("54.00%");
  await expect(page.locator("#detail-metrics")).toContainText("Không có dữ liệu");
  await expect(page.locator("#pnl-chart-assumptions")).toContainText("Phương pháp / giả định API");
  await expect(page.locator("#scenario-state")).toContainText("4 điểm payoff");
});

test("runs a historical backtest and renders exit reasons", async ({ page }) => {
  await page.route("**/api/v1/backtests", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.assets).toEqual(["BTC"]);
    expect(body.filters.strategies).toEqual(["long_call"]);
    expect(body.exit_policy).toMatchObject({ type: "profit_target", profit_target_pct: 0.5 });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        engine: "snapshot_replay",
        status: "completed",
        data_quality: {
          snapshot_count: 48,
          signal_evaluations: 12,
          fill_model: "top_of_book_bid_ask",
          lookahead_free: true,
        },
        report: {
          status: "insufficient_evidence",
          train: { trade_count: 1 },
          holdout: { trade_count: 1, net_pnl: 125, expected_value: 125, max_drawdown: 0 },
        },
        trades: [{
          entry_time: "2026-01-10T00:00:00Z",
          exit_time: "2026-01-11T00:00:00Z",
          strategy: "long_call",
          exit_reason: "profit_target",
          gross_pnl: 150,
          net_pnl: 125,
          return_pct: 25,
        }],
        unresolved: [],
      }),
    });
  });

  await page.locator("#backtest-asset").selectOption("BTC");
  await page.locator("#backtest-start").fill("2026-01-01T00:00");
  await page.locator("#backtest-end").fill("2026-02-01T00:00");
  await page.locator("#backtest-exit-policy").selectOption("profit_target");
  await page.locator("#backtest-profit-target").fill("0.5");
  await page.getByRole("button", { name: "Chạy backtest" }).click();

  await expect(page.locator("#backtest-state")).toContainText("1 trade");
  await expect(page.locator("#backtest-quality")).toContainText("Look-ahead: đã kiểm soát");
  await expect(page.locator("#backtest-trades-body")).toContainText("profit_target");
  await expect(page.locator("#backtest-metrics")).toContainText("125.00");
});
