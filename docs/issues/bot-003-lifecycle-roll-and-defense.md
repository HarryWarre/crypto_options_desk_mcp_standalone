# BOT-003 — Lifecycle Management, Compounding & Defensive Rolling

**Status:** backlog  
**Branch:** `feat/options-neutral-spread-paper-bot`  
**Target:** `main`

## 1. Problem & Context
When operating an aggressive options strategy (maximizing growth across the entire portfolio):
1. **Early Profit Taking:** Holding until final expiration exposes positions to severe gamma risk during the final days. Taking profit early at 50% of maximum credit drastically increases compounding frequency (capital turns over 2–3x faster).
2. **Defensive Adjustment (Roll Untested Side):** When underlying spot drifts toward one short strike, rolling the opposite, untested side closer to spot generates additional credit to buffer against the threatened side.
3. **Expiration Handling:** Positions nearing expiration (DTE <= 1) must be systematically rolled out to the next weekly cycle to avoid pin risk.

## 2. Decision Rules & Thresholds
- **Take Profit (TP):** Close all 4 legs when Unrealized PnL >= 50% of Net Credit Collected.
- **Defense Trigger:** When spot price breaches 0.50 standard deviations toward a short strike, initiate "Roll Untested Side" to restore Delta neutrality.
- **Stop Loss (SL) / Circuit Breaker:** Liquidate position if Unrealized Loss exceeds 2.0x Net Credit Collected.
- **Time Exit:** Close or roll when DTE <= 1.0 day.

## 3. Sub-tasks
- [ ] **BOT-003A**: Real-time position mark-to-market evaluation loop.
- [ ] **BOT-003B**: 50% TP automatic close & immediate capital recycling trigger.
- [ ] **BOT-003C**: Defense engine: Roll untested side algorithm.
- [ ] **BOT-003D**: DTE <= 1 rollover & emergency stop-loss protection.

