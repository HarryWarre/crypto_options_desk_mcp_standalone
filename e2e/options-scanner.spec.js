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
  await page.addInitScript((liveOpportunity) => {
    class MockWebSocket extends EventTarget {
      static OPEN = 1;

      constructor(url) {
        super();
        this.url = url;
        this.readyState = 0;
        setTimeout(() => {
          this.readyState = MockWebSocket.OPEN;
          this.dispatchEvent(new Event("open"));
        }, 0);
      }

      send(payload) {
        const request = JSON.parse(payload);
        if (this.url.includes("/api/v1/opportunities/stream")) {
          window.__liveRequest = request;
          setTimeout(() => {
            this.dispatchEvent(new MessageEvent("message", {
              data: JSON.stringify({ type: "stream_status", status: "starting" }),
            }));
            this.dispatchEvent(new MessageEvent("message", {
              data: JSON.stringify({ type: "log", message: "[OPTIONS] live snapshot ready" }),
            }));
            this.dispatchEvent(new MessageEvent("message", {
              data: JSON.stringify({
                type: "snapshot",
                payload: {
                  timestamp: "2026-09-15T14:46:33Z",
                  data_timestamp: "2026-09-15T14:46:33Z",
                  valuation_mode: "executable",
                  opportunities: window.__emptyLiveSnapshot ? [] : [liveOpportunity],
                  rejections: [],
                  asset_failures: [],
                  issues: [],
                  scan_context: {},
                  live_desk: {
                    selected_assets: ["BTC"],
                    observed_assets: [{
                      asset: "BTC",
                      spot: 76227.9,
                      contract_count: 700,
                      valid_quote_count: 35,
                    }],
                    option_quotes: window.__emptyLiveSnapshot ? [] : [{
                      asset: "BTC",
                      symbol: "BTC-30OCT26-73000-C-USDT",
                      option_type: "Call",
                      strike: 73000,
                      expiry_at: "2026-10-30T08:00:00Z",
                      spot_price: 76227.9,
                      mark_price: 5872.5,
                      mark_iv: 0.3889,
                      bid_price: 5835,
                      ask_price: 5910,
                      delta: 0.55,
                      volume_24h: 39,
                      open_interest: 19.53,
                      quote_timestamp: "2026-09-15T14:46:33Z",
                    }],
                    timestamp: "2026-09-15T14:46:33Z",
                    data_timestamp: "2026-09-15T14:46:33Z",
                    source: "mock-live-market",
                    rejection_reasons: {
                      spread_above_maximum: 4,
                      low_liquidity: 2,
                    },
                    execution_allowed: false,
                  },
                },
                execution_allowed: false,
              }),
            }));
          }, 0);
          return;
        }
        window.__monitoringRequest = request;
        setTimeout(() => {
          this.dispatchEvent(new MessageEvent("message", {
            data: JSON.stringify({ type: "stream_status", status: "connected" }),
          }));
          this.dispatchEvent(new MessageEvent("message", {
            data: JSON.stringify({
              type: "snapshot",
              payload: {
                captured_at: "2026-09-15T14:46:33Z",
                source: "bybit-websocket",
                reconciliation_status: "complete",
                issues: [],
                positions: [{
                  symbol: "BTCUSDT",
                  side: "long",
                  quantity: 1,
                  avg_entry_price: 65000,
                  mark_price: 70000,
                  unrealized_pnl: 5000,
                }],
                decisions: [{
                  symbol: "BTCUSDT",
                  action: "close",
                  severity: "high",
                  reasons: ["take_profit_price_triggered"],
                }],
                summary: { close: 1, hold: 0, review: 0 },
              },
              persistence: { enabled: true, status: "saved" },
              execution_allowed: false,
            }),
          }));
        }, 0);
      }

      close() {
        this.readyState = 3;
        this.dispatchEvent(new Event("close"));
      }
    }

    window.WebSocket = MockWebSocket;
  }, opportunity);

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

  await page.route("**/api/v1/positions/monitor", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        analysis_type: "position_monitoring",
        data: {
          captured_at: "2026-09-15T14:46:33Z",
          source: "bybit-rest",
          reconciliation_status: "complete",
          issues: [],
          positions: [{
            symbol: "BTCUSDT",
            side: "long",
            quantity: 1,
            avg_entry_price: 65000,
            mark_price: 70000,
            unrealized_pnl: 5000,
          }],
          decisions: [{
            symbol: "BTCUSDT",
            action: "close",
            severity: "high",
            reasons: ["take_profit_price_triggered"],
          }],
          summary: { close: 1, hold: 0, review: 0 },
        },
        persistence: { enabled: true, status: "saved" },
      }),
    });
  });

}

async function openLiveDesk(page) {
  await page.getByRole("link", { name: "Live Desk" }).click();
  await expect(page).toHaveURL(/#live-desk$/);
  await expect(page.locator("#live-desk-view")).toBeVisible();
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
  await expect(page.getByLabel("Lỗ tối đa mỗi ý tưởng")).toHaveAttribute("placeholder", "Không giới hạn");
  await expect(page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ })).toBeVisible();
  await expect(page.getByRole("group", { name: "Bạn muốn tìm ý tưởng nào?" })).toBeVisible();
  await expect(page.locator('.strategy-card input[type="checkbox"]')).toHaveCount(13);

  const advancedFilters = page.getByTestId("advanced-filters");
  await expect(advancedFilters.locator(".advanced-content")).not.toBeVisible();
  await expect(page.getByLabel("IV edge tối thiểu")).not.toBeVisible();
  await expect(page.getByLabel("Delta tối thiểu")).not.toBeVisible();
  await expect(page.getByLabel("Phí mỗi chiều")).not.toBeVisible();
});

test("scans successfully without entering maximum loss (unconstrained loss)", async ({ page }) => {
  let submittedPayload = null;
  page.on("request", (req) => {
    if (req.url().includes("/api/v1/opportunities/scan/stream")) {
      submittedPayload = req.postDataJSON();
    }
  });

  // Do not fill "Lỗ tối đa mỗi ý tưởng"
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();

  await expect(page.locator("#result-state")).toContainText("1 cơ hội");
  await expect(page.locator("#opportunity-explanations .explanation-card")).toHaveCount(1);
  await expect(page.locator("#scan-context")).toContainText("không giới hạn");
  expect(submittedPayload.max_loss).toBeNull();
});

test("prevents submission and flags invalid state when negative maximum loss is entered", async ({ page }) => {
  const maxLossInput = page.getByLabel("Lỗ tối đa mỗi ý tưởng");
  await maxLossInput.fill("-10");
  expect(await maxLossInput.evaluate((el) => el.validity.valid)).toBe(false);
  expect(await maxLossInput.evaluate((el) => el.validity.rangeUnderflow)).toBe(true);

  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  await expect(page.locator("#result-state")).toHaveText("Chọn điều kiện rồi bấm “Quét cơ hội”.");
});

test("connects the live options feed and updates the desk dashboard", async ({ page }) => {
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("100");
  await openLiveDesk(page);
  await page.getByRole("button", { name: "Bật live feed" }).click();

  await expect(page.locator("#live-connection")).toContainText("Live feed · 1 option quotes");
  await expect(page.locator("#live-session-state")).toHaveText("LIVE");
  await expect(page.locator("#live-stat-spot")).toHaveText("76.2k");
  await expect(page.locator("#live-stat-opportunities")).toHaveText("1");
  await expect(page.locator("#live-stat-contracts")).toHaveText("700");
  await expect(page.locator("#live-stat-rejections")).toHaveText("6");
  await expect(page.locator("#market-strip")).toContainText("BTC");
  await expect(page.locator("#market-strip")).toContainText("700 contracts");
  await expect(page.locator("#live-rejection-summary")).toContainText("spread_above_maximum");
  await expect(page.locator("#live-option-tape")).toContainText("Bid");
  await expect(page.locator("#live-option-tape")).toContainText("Ask");
  await expect(page.locator("#live-option-chart")).toContainText("BTC-30OCT26-73000-C-USDT");
  await expect(page.locator("#live-option-chart circle")).toHaveCount(3);
  await expect(page.locator("#live-feed")).toContainText("Option quote");
  await expect(page.locator("#live-toggle")).toHaveText("Dừng live feed");
  expect(await page.evaluate(() => window.__liveRequest.max_loss)).toBe(100);

  await page.getByRole("button", { name: "Dừng live feed" }).click();
  await expect(page.locator("#live-connection")).toContainText("Live feed đang tắt");
});

test("renders live market context when the snapshot has no opportunities", async ({ page }) => {
  await page.evaluate(() => { window.__emptyLiveSnapshot = true; });
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("100");
  await openLiveDesk(page);
  await page.getByRole("button", { name: "Bật live feed" }).click();

  await expect(page.locator("#live-session-state")).toHaveText("LIVE");
  await expect(page.locator("#live-stat-spot")).toHaveText("76.2k");
  await expect(page.locator("#live-stat-opportunities")).toHaveText("0");
  await expect(page.locator("#live-stat-contracts")).toHaveText("700");
  await expect(page.locator("#live-stat-rejections")).toHaveText("6");
  await expect(page.locator("#market-strip")).toContainText("700 contracts");
  await expect(page.locator("#live-option-tape")).toContainText("Chưa có option quote");
  await expect(page.locator("#live-feed")).toContainText("chưa có option quote");
  await expect(page.locator("#live-rejection-summary")).toContainText("low_liquidity");
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

  await expect(page.locator("#opportunity-explanations")).toContainText(opportunity.symbol);
  await expect(page.locator("#opportunity-explanations")).toContainText("30/10/2026");
  await expect(page.locator("#opportunity-explanations")).toContainText("Còn 45 ngày");
  await expect(page.locator("#opportunity-explanations")).toContainText("Kỳ vọng BTC tăng giá");
  await expect(page.locator("#opportunity-explanations")).toBeVisible();
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
  await expect(page.locator("#valuation-mode-notice")).toContainText("fair value mô hình");
  await expect(page.locator("#opportunity-explanations")).toContainText("Tham khảo");
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
  await expect(page.locator("#opportunity-explanations")).toContainText("Giả định");
  await expect(page.locator("#opportunity-explanations")).toContainText("0.004");
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
  await expect(page.locator("#opportunity-explanations .explanation-card")).toHaveCount(0);
  await expect(page.locator("#opportunity-explanations")).toBeHidden();
  await expect(page.locator("#results-guide")).toBeHidden();
  await expect(page.locator("#valuation-mode-notice")).toBeHidden();
  await expect(page.locator("#historical-context")).toBeHidden();
});

test("shows an understandable error when the scan service fails", async ({ page }) => {
  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("2");
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();

  await expect(page.locator("#result-state")).toHaveText("Không thể hoàn tất lượt quét. Vui lòng thử lại.");
  await expect(page.locator("#scan-terminal")).toContainText("Không thể hoàn tất lượt quét");
});

test("terminal acts as a live backend monitoring system and records step logs", async ({ page }) => {
  const terminal = page.locator("#scan-terminal");
  const details = page.locator(".technical-log");

  await expect(details).toHaveJSProperty("open", true);
  await expect(terminal).toBeVisible();
  await expect(terminal).toContainText("[INIT]");
  await expect(terminal).toContainText("tài sản");

  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1000");
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();

  await expect(terminal).toContainText("[QUÉT]");
  await expect(terminal).toContainText("[OPTIONS] scan started");
  await expect(terminal).toContainText("[OPTIONS] scan completed");

  await page.getByRole("button", { name: "Xóa log" }).click();
  await expect(terminal).toContainText("Nhật ký hệ thống đã được xóa");
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

test("starts in the scanner workspace with a professional module sidebar", async ({ page }) => {
  const sidebar = page.getByRole("complementary", { name: "Điều hướng workspace" });

  await expect(sidebar).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "Scanner" })).toHaveAttribute("aria-current", "page");
  await expect(sidebar.getByRole("link", { name: "Backtest" })).toBeVisible();
  await expect(page.locator("#scanner-view")).toBeVisible();
  await expect(page.locator("#backtest-view")).not.toBeVisible();
  await expect(sidebar).toContainText("Sắp ra mắt");
  await expect(sidebar.locator('[aria-disabled="true"]')).toHaveCount(2);

  // Results panel must not show empty or unpopulated borders on initial load
  await expect(page.locator("#valuation-mode-notice")).toBeHidden();
  await expect(page.locator("#results-guide")).toBeHidden();
  await expect(page.locator("#historical-context")).toBeHidden();
  await expect(page.locator("#results-table-wrap")).toBeHidden();
});

test("opens live desk as a separate workspace with direct option quote chart", async ({ page }) => {
  const sidebar = page.getByRole("complementary", { name: "Điều hướng workspace" });
  const liveDeskLink = sidebar.getByRole("link", { name: "Live Desk" });

  await expect(liveDeskLink).toBeVisible();
  await liveDeskLink.click();

  await expect(page).toHaveURL(/#live-desk$/);
  await expect(page.locator("#live-desk-view")).toBeVisible();
  await expect(page.locator("#scanner-view #live-desk")).toHaveCount(0);
  await expect(page.locator("#live-option-chart")).toBeVisible();

  await page.getByRole("button", { name: "Bật live feed" }).click();
  await expect(page.locator("#live-option-chart")).toContainText("BTC-30OCT26-73000-C-USDT");
  await expect(page.locator("#live-option-tape")).toContainText("Bid");
  await expect(page.locator("#live-option-tape")).toContainText("Ask");
});

test("exposes position monitoring from the module sidebar", async ({ page }) => {
  const sidebar = page.getByRole("complementary", { name: "Điều hướng workspace" });
  const monitoringLink = sidebar.getByRole("link", { name: "Position Monitoring" });

  await expect(monitoringLink).toBeVisible();
  await expect(monitoringLink).toHaveAttribute("href", "#monitoring");

  await monitoringLink.click();

  await expect(page).toHaveURL(/#monitoring$/);
  await expect(monitoringLink).toHaveAttribute("aria-current", "page");
  await expect(page.locator("#position-monitoring-view")).toBeVisible();
  await expect(page.locator("#scanner-view")).not.toBeVisible();
  await expect(page.locator("#monitoring-state")).toContainText("Chưa có dữ liệu theo dõi");
});

test("runs a read-only position check and renders the exit decision", async ({ page }) => {
  const sidebar = page.getByRole("complementary", { name: "Điều hướng workspace" });
  await sidebar.getByRole("link", { name: "Position Monitoring" }).click();
  await page.getByRole("button", { name: "Cập nhật theo dõi" }).click();
  await expect.poll(() => page.evaluate(() => window.__monitoringRequest)).toMatchObject({
    base_coin: "BTC",
    position_type: "all",
    policies: [],
    persist: true,
  });

  await expect(page.locator("#monitoring-state")).toContainText("Đã cập nhật");
  await expect(page.locator("#monitoring-metrics")).toContainText("CLOSE");
  await expect(page.locator("#monitoring-decisions-body")).toContainText("CLOSE · Cần đóng thủ công");
  await expect(page.locator("#monitoring-decisions-body")).toContainText("take_profit_price_triggered");
});

test("uses observed-symbol and policy dropdowns without manual symbol entry", async ({ page }) => {
  await page.getByRole("link", { name: "Position Monitoring" }).click();
  await page.locator("#monitoring-submit").click();
  await expect(page.locator("#monitoring-symbol option[value='BTCUSDT']")).toHaveCount(1);

  await page.locator("#monitoring-symbol").selectOption("BTCUSDT");
  await page.locator("#monitoring-policy-profile").selectOption("day_trade");
  await page.locator("#monitoring-submit").click();

  await expect.poll(() => page.evaluate(() => window.__monitoringRequest)).toMatchObject({
    policies: [{
      symbol: "BTCUSDT",
      max_holding_hours: 24,
    }],
  });
});

test("switches between scanner and backtest without stacking workspaces", async ({ page }) => {
  const sidebar = page.getByRole("complementary", { name: "Điều hướng workspace" });

  await sidebar.getByRole("link", { name: "Backtest" }).click();
  await expect(page).toHaveURL(/#backtest$/);
  await expect(sidebar.getByRole("link", { name: "Backtest" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator("#backtest-view")).toBeVisible();
  await expect(page.locator("#scanner-view")).not.toBeVisible();

  await sidebar.getByRole("link", { name: "Scanner" }).click();
  await expect(page).toHaveURL(/#scanner$/);
  await expect(page.locator("#scanner-view")).toBeVisible();
  await expect(page.locator("#backtest-view")).not.toBeVisible();
});

test("opens the backtest workspace from a deep link and preserves browser history", async ({ page }) => {
  await page.goto("/#backtest");

  const sidebar = page.getByRole("complementary", { name: "Điều hướng workspace" });
  await expect(page.locator("#backtest-view")).toBeVisible();
  await expect(page.locator("#scanner-view")).not.toBeVisible();
  await expect(sidebar.getByRole("link", { name: "Backtest" })).toHaveAttribute("aria-current", "page");

  await page.goBack();
  await expect(page).toHaveURL(/#scanner$/);
  await expect(page.locator("#scanner-view")).toBeVisible();
});

test("keeps the workspace shell inside desktop and mobile viewports", async ({ page }) => {
  for (const viewport of [
    { width: 1280, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.reload();
    await expect(page.locator(".app-shell")).toBeVisible();

    const overflow = await page.locator(".app-shell").evaluate((shell) => ({
      clientWidth: shell.clientWidth,
      scrollWidth: shell.scrollWidth,
    }));
    expect(overflow.scrollWidth, `workspace shell overflows at ${viewport.width}px`).toBeLessThanOrEqual(overflow.clientWidth);
  }
});

test("runs a historical backtest and renders exit reasons", async ({ page }) => {
  await page.getByRole("link", { name: "Backtest" }).click();
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

test("captures clean results panel screenshots on initial load and empty scan without ghost borders", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(page.locator("#valuation-mode-notice")).toBeHidden();
  await expect(page.locator("#results-guide")).toBeHidden();
  await expect(page.locator("#historical-context")).toBeHidden();
  await expect(page.locator("#results-table-wrap")).toBeHidden();
  await page.locator(".results-panel").screenshot({ path: "test-results/screenshots/scanner-initial.png" });

  await page.getByLabel("Lỗ tối đa mỗi ý tưởng").fill("1");
  await page.getByRole("button", { name: /Quét cơ hội|Tìm cơ hội/ }).click();
  await expect(page.locator("#result-state")).toContainText("Không có cơ hội");
  await expect(page.locator("#valuation-mode-notice")).toBeHidden();
  await expect(page.locator("#results-guide")).toBeHidden();
  await expect(page.locator("#historical-context")).toBeHidden();
  await expect(page.locator("#results-table-wrap")).toBeHidden();
  await page.locator(".results-panel").screenshot({ path: "test-results/screenshots/scanner-empty.png" });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".results-panel").screenshot({ path: "test-results/screenshots/scanner-mobile-empty.png" });
});

test("navigates to Strategy Builder, evaluates preset, and renders payoff chart", async ({ page }) => {
  await page.route("**/api/v1/options/chain/BTC", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        asset: "BTC",
        spot: 65000,
        expiries: ["2026-10-30", "2026-11-27"],
        contracts: [
          { symbol: "BTC-30OCT26-60000-C", option_type: "call", strike: 60000, expiry: "2026-10-30", mark_iv: 0.65, mark_price: 6500, bid: 6400, ask: 6600, open_interest: 50 },
          { symbol: "BTC-30OCT26-70000-C", option_type: "call", strike: 70000, expiry: "2026-10-30", mark_iv: 0.60, mark_price: 1500, bid: 1450, ask: 1550, open_interest: 30 },
          { symbol: "BTC-30OCT26-60000-P", option_type: "put", strike: 60000, expiry: "2026-10-30", mark_iv: 0.65, mark_price: 1200, bid: 1150, ask: 1250, open_interest: 40 },
          { symbol: "BTC-30OCT26-70000-P", option_type: "put", strike: 70000, expiry: "2026-10-30", mark_iv: 0.60, mark_price: 6200, bid: 6100, ask: 6300, open_interest: 25 },
        ],
      }),
    });
  });

  await page.route("**/api/v1/builder/populate", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        strategy_type: "bull_call_vertical",
        legs: [
          { option_type: "call", strike: 60000, expiry: "2026-10-30", position: 1, quantity: 1, mid_price: 6500, iv: 0.65, spot: 65000 },
          { option_type: "call", strike: 70000, expiry: "2026-10-30", position: -1, quantity: 1, mid_price: 1500, iv: 0.60, spot: 65000 },
        ],
      }),
    });
  });

  await page.route("**/api/v1/builder/evaluate", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        strategy_type: "bull_call_vertical",
        net_premium: 5000,
        max_profit: 5000,
        max_loss: -5000,
        risk_reward_ratio: 1.0,
        breakevens: [65000],
        greeks: { delta: 0.35, gamma: 0.00002, theta: -15.2, vega: 45.1 },
        payoff_curve: [
          { spot: 55000, pnl: -5000 },
          { spot: 60000, pnl: -5000 },
          { spot: 65000, pnl: 0 },
          { spot: 70000, pnl: 5000 },
          { spot: 75000, pnl: 5000 },
        ],
      }),
    });
  });

  // Navigate to builder
  await page.locator('a[href="#builder"]').click();
  await expect(page.locator("#strategy-builder-view")).toBeVisible();
  await expect(page.locator("#builder-title")).toContainText("Options Strategy Builder");

  // Verify legs loaded from preset
  await expect(page.locator("#builder-legs-tbody tr")).toHaveCount(2);

  // Click Evaluate
  await page.locator("#builder-evaluate-btn").click();
  await expect(page.locator("#bm-net-premium")).toContainText("5000.00");
  await expect(page.locator("#bm-max-profit")).toContainText("5000.00");
  await expect(page.locator("#builder-payoff-svg path")).toBeVisible();
});

test("saves strategy builder position to trade notebook and verifies smart monitor badge", async ({ page }) => {
  let createdPosition = null;

  await page.route("**/api/v1/options/chain/BTC", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        asset: "BTC",
        spot: 65000,
        expiries: ["2026-10-30"],
        contracts: [
          { symbol: "BTC-30OCT26-65000-C", option_type: "call", strike: 65000, expiry: "2026-10-30", mark_iv: 0.65, mark_price: 3000, bid: 2950, ask: 3050, open_interest: 50 },
        ],
      }),
    });
  });

  await page.route("**/api/v1/builder/populate", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        strategy_type: "long_call",
        legs: [
          { option_type: "call", strike: 65000, expiry: "2026-10-30", position: 1, quantity: 1, mid_price: 3000, iv: 0.65, spot: 65000 },
        ],
      }),
    });
  });

  await page.route("**/api/v1/builder/evaluate", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        strategy_type: "long_call",
        net_premium: 3000,
        max_profit: null,
        max_loss: -3000,
        risk_reward_ratio: null,
        breakevens: [68000],
        greeks: { delta: 0.5, gamma: 0.00003, theta: -20, vega: 60 },
        payoff_curve: [{ spot: 60000, pnl: -3000 }, { spot: 70000, pnl: 2000 }],
      }),
    });
  });

  await page.route("**/api/v1/notebook/positions", async (route) => {
    if (route.request().method() === "POST") {
      const data = JSON.parse(route.request().postData());
      createdPosition = {
        id: "nb-1234",
        created_at: new Date().toISOString(),
        asset: data.asset,
        strategy_type: data.strategy_type,
        legs: data.legs,
        entry_spot: data.entry_spot,
        status: "open",
        notes: data.notes,
        source: data.source,
      };
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ position: createdPosition }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ positions: createdPosition ? [createdPosition] : [] }),
      });
    }
  });

  await page.route("**/api/v1/notebook/monitor", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        evaluations: createdPosition ? [{
          position_id: "nb-1234",
          current_spot: 72000,
          unrealized_pnl: 4000,
          decision: { action: "TAKE_PROFIT", action_vn: "CHỐT LỜI", reason: "Target reached" },
        }] : [],
      }),
    });
  });

  // Go to builder, click save to notebook
  await page.locator('a[href="#builder"]').click();
  await page.locator("#builder-save-notebook-btn").click();

  // Expect auto-redirect to monitoring workspace
  await expect(page.locator("#position-monitoring-view")).toBeVisible();
  await expect(page.locator("#nb-positions-tbody")).toContainText("nb-1234");
  await expect(page.locator(".smart-badge-profit")).toContainText("CHỐT LỜI");
});
