# BOT-001 — Virtual Paper Trading & Margin Simulation Engine

**Status:** in-progress  
**Branch:** `feat/options-neutral-spread-paper-bot`  
**Target:** `main`

## 1. Problem & Context
The existing options desk implementation has a naive placeholder `paper_mode` in `covered_call_bot.py` which only logs messages and assigns entry price directly from `mid_price`. It lacks:
1. True account balance tracking (initial capital, cash, margin, realized and unrealized PnL).
2. Realistic order matching: using live Bybit market depth (Bid/Ask) rather than hypothetical mid-prices, with realistic taker/maker fees and configurable slippage.
3. Multi-leg position tracking: evaluating composite structures (Iron Condor, Strangle, Spreads) and tracking mark-to-market valuations across live option chains.
4. Portfolio Margin (PMM) estimation & Liquidation buffer monitoring: crucial when deploying aggressive leverage / full capital strategies.
5. Durable persistence: saving state to SQLite so that simulation state survives bot restarts and interruptions.

## 2. Architecture & Components

```text
Bybit Market Data (Live Ticker / Orderbook / Mark Price)
                       │
                       ▼
            ┌─────────────────────┐
            │   MatchingEngine    │ (Simulates fill at Best Bid / Best Ask + slippage & fees)
            └──────────┬──────────┘
                       │ Fills
                       ▼
            ┌─────────────────────┐
            │   PaperAccount      │ (Balances, Cash, Positions, Realized/Unrealized PnL)
            └──────────┬──────────┘
                       │ Positions & Spot Price
                       ▼
            ┌─────────────────────┐
            │   MarginCalculator  │ (Bybit PMM-style Margin & Liquidation Buffer)
            └──────────┬──────────┘
                       │ State Sync
                       ▼
            ┌─────────────────────┐
            │   PaperStorage      │ (SQLite durable persistence)
            └─────────────────────┘
```

## 3. Sub-tasks
- [ ] **BOT-001A**: `PaperAccount` with virtual balance, cash, positions, trade logs, and mark-to-market PnL updates.
- [ ] **BOT-001B**: `MatchingEngine` supporting Limit & Market orders with realistic bid/ask fills, slippage, and Bybit fee deduction.
- [ ] **BOT-001C**: `MarginCalculator` estimating Bybit Portfolio Margin for multi-leg strategies and providing margin utilization alerts.
- [ ] **BOT-001D**: `PaperStorage` SQLite implementation with transactional safety and serialization/deserialization.
- [ ] **BOT-001E**: Unit tests in `tests/test_paper_broker.py` covering order fills, PnL updates, margin calculations, and persistence.

