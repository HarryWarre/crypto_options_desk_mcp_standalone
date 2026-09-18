# BOT-002 — Dynamic Iron Condor & Neutral Spread Strategy Engine

**Status:** backlog  
**Branch:** `feat/options-neutral-spread-paper-bot`  
**Target:** `main`

## 1. Problem & Context
To execute neutral, high-probability options strategies (such as Iron Condors and Short Strangles) automatically on Bybit:
1. The bot must identify sideways regime conditions where option premiums are inflated relative to historical volatility.
2. The bot must dynamically select target expirations (Weekly: 7–14 DTE) and strike ladders mapped to target Delta bounds (e.g. Short Delta ~0.15, Long Wings ~0.03).
3. The execution engine must safely leg into multi-leg combinations without exposing the account to unhedged single-leg gap risk (anti-leg risk: Long wings executed first to establish margin credit, then short legs placed).

## 2. Target Strategy Specs (Wide-Wing Iron Condor)
- **Asset:** BTC, ETH, SOL
- **Market Bias:** Delta Neutral (Absolute net delta < 0.05)
- **Tenor:** 7 – 14 DTE (Weekly cycle to capture peak Theta decay)
- **Strikes:**
  - Short Call: Delta ~ +0.15 (85% OTM)
  - Short Put: Delta ~ -0.15 (85% OTM)
  - Long Call Wing: Delta ~ +0.03 (Protective cap)
  - Long Put Wing: Delta ~ -0.03 (Protective cap)
- **Probability of Profit (PoP):** 70% – 75%
- **Entry Triggers:**
  - Trend / Range: ADX(14) < 25 or Bollinger Bands Squeeze
  - Volatility Spread: $\text{IV} - \text{RV} \ge 8.0\text{ vol pts}$

## 3. Sub-tasks
- [ ] **BOT-002A**: Market regime & Volatility screener integrating `opportunity_scanner.py` metrics.
- [ ] **BOT-002B**: Dynamic contract selector using live Bybit options chain, Greek interpolation, and `builder.py` templates.
- [ ] **BOT-002C**: Multi-leg execution workflow (Legging-in engine with post-only limit orders, order chasing, and timeout rollback).

