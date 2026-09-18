# PM-009 — Options Strategy Builder, Trade Notebook & Smart Position Monitoring

Status: done
Branch: `feat/options-strategy-builder-and-smart-monitoring`
Worktree: `/Users/hoangviet/Flowsurface/.worktrees/options-strategy-builder-and-smart-monitoring`
Target: `main`

## Problem

1. **Position Monitoring Limitation**:
   The current Position Monitoring module (`/api/v1/positions/monitor` and WS `/api/v1/positions/stream`) requires private Bybit API credentials (`BYBIT_API_KEY`, `BYBIT_API_SECRET`) with live exchange positions. When users paper-trade or follow signals manually, they cannot track their positions. Furthermore, it only evaluates raw single-leg positions against static numerical stop-loss or take-profit prices, lacking awareness of multi-leg options structures (spreads, condors, straddles, butterflies) and the scanner's original trading thesis.

2. **Absence of an Options Strategy Builder**:
   Traders need a visual, interactive strategy builder—similar to open-source tools like `opstrat` (abhijith-git/opstrat), `OptionLab` (rgaveiga/optionlab), and `OpenBull` (marketcalls/openbull)—that fetches current live options chains from Bybit (BTC, ETH, SOL) across expiries and strikes, supports all strategies present in the scanner, and allows custom leg assembly with real-time payoff diagrams, Greeks, and probability metrics.

3. **Broken Signal-to-Trade-to-Exit Loop**:
   When the scanner identifies an edge or an opportunity:
   - There is no direct way to save the signal into a trade journal ("Notebook").
   - There is no continuous, intelligent re-valuation of the position that monitors whether to **HOLD (Giữ)**, **CUT LOSS / ABANDON (Bỏ)**, or **TAKE PROFIT (Chốt lời)** based on the ongoing performance relative to the scanner's original thesis and target pricing.

## Target Flow

```text
1. Scanner Signal / Edge
          ↓
2. Open in Strategy Builder (or Direct One-Click Save)
          ↓
3. Save to Trade Notebook (Journaling entry price, strikes, target, EV, thesis)
          ↓
4. Live Public Market Data Ingestion (Mark, Bid/Ask, Greeks, Spot)
          ↓
5. Smart Position Valuation & Thesis Verification Engine
          ↓
6. Actionable Decision Output:
   • 🟢 CHỐT LỜI (Take Profit): Profit target reached or spot hit target
   • 🔴 BỎ / CẮT LỖ (Cut Loss): Stop loss hit, thesis invalidated, or critical DTE decay
   • 🟡 GIỮ (Hold): Edge continues, theta working, thesis intact
```

## Strategy Support in Builder

The builder must support all strategies available in the scanner and scenario engine:
- `long_call`, `long_put`
- `bull_call_vertical`, `bear_call_vertical`
- `bull_put_vertical`, `bear_put_vertical`
- `iron_condor`, `iron_butterfly`
- `long_straddle`, `short_straddle`
- `long_strangle`, `short_strangle`
- `calendar_spread`
- `butterfly`, `broken_wing_butterfly`
- `covered_call`, `protective_put`
- `custom` (Add, modify, or remove arbitrary legs)

## Open-Source Architecture References

- **Payoff & Greeks Modeling**: Leveraging internal `options_lib.scenario_engine` and `options_lib.payoff_metrics` together with inspiration from `opstrat` and `OptionLab`.
- **Live Chain Fetching**: Utilizing `bybit_api.options_market_data.BybitOptionMarketDataAdapter` to fetch live contracts, grouping by expiration and organizing into a Call/Put strike ladder.
- **Persistence**: Durable local SQLite database (`trade_notebook_positions`), ensuring trades persist across sessions without requiring remote accounts.

## Acceptance Criteria

- [x] New git branch `feat/options-strategy-builder-and-smart-monitoring` created and active.
- [x] Backend API provides `GET /api/v1/options/chain/{asset}` with live Bybit options chains grouped by expiry and strikes.
- [x] Backend API provides `POST /api/v1/builder/evaluate` returning net debit/credit, max profit, max loss, risk/reward, breakevens, Greeks, and expiry payoff curves.
- [x] Backend provides persistent SQLite Trade Notebook storage (`/api/v1/notebook/positions`, CRUD endpoints).
- [x] Backend provides Smart Monitor evaluation (`GET /api/v1/notebook/monitor`) calculating real-time mark-to-market PnL, Greeks, and emitting actionable Vietnamese suggestions: `CHỐT LỜI`, `BỎ / CẮT LỖ`, `GIỮ`.
- [x] Frontend Workspace Navigation includes **Strategy Builder** (Tab 02).
- [x] Strategy Builder UI renders options chain, preset strategy buttons, customizable legs table, interactive SVG payoff chart, and "Lưu vào Sổ tay / Monitor" action.
- [x] Scanner opportunities include "➕ Lưu vào Sổ tay / Monitor" and "🛠 Mở trong Builder" buttons.
- [x] Position Monitoring view displays both Trade Notebook positions (with live valuations and smart recommendation badges) and Bybit account monitoring.
- [x] Automated tests for strategy builder, notebook persistence, smart monitor valuation logic, and API endpoints pass.

## Review outcome

- Standards review: `git diff --check` is clean. No whitespace errors or trailing blank lines. No `innerHTML` used in client JavaScript.
- Safety & contract: domain semantics in `CONTEXT.md` are completely preserved. Read-only presentation and paper trading models without live order mutations.
- Test verification: 314 Python unit & API tests pass; 30 Playwright E2E tests pass (24.2s).

