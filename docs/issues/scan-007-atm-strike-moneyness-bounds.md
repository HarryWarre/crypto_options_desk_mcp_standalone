# SCAN-007 — ATM Proximity & Moneyness Bounds for Option Strike Selection

Status: verified  
Branch: `feat/scanner-strike-moneyness-bounds`  
Target: `main`  

Remote publication is pending because this repository has no configured issue tracker connection.

## Problem

When scanning for option opportunities (particularly multi-leg strategies such as Long Strangle, Iron Butterfly, Straddles, and Vertical Spreads in Synthetic or Theoretical mode), the scanner generates candidate legs with strikes that are excessively far from the At-The-Money (ATM) spot price:

1. **Unrealistic Deep OTM / Far-from-ATM Strikes**:
   - For example, with underlying HYPE trading around spot ~$91.4, the scanner paired a **Put K50** (strike 50 vs spot 91.4, delta ≈ -0.0005, moneyness ≈ 0.54) with a Call K82 in a Long Strangle.
   - On live exchanges like Bybit, these deep OTM strikes have zero trading volume (`volume_24h = 0`), zero open interest (`open_interest = 0`), and phantom order books (e.g., bid 0.01 vs ask 1.37 vs mark 0.0025).
   - In practice, these options cannot be traded at viable prices ("thực tế không có option giá đó").

2. **Synthetic & Theoretical Pricing Artifacts**:
   - In `synthetic` mode, the scanner estimates synthetic bid/ask around mark or fair value with an assumed spread (e.g., 100 bps). For a deep OTM strike like Put K50 with near-zero delta and mark ≈ 0.0025, synthesizing a bid/ask and combining it into multi-leg strategies produces deceptive opportunities with simulated payoffs and positive edges that do not reflect executable reality.

3. **Unconstrained Leg Generation in Multi-Leg Strategies**:
   - In `_same_expiry_strategy_leg_sets()` (`src/options_lib/opportunity_scanner.py`), multi-leg strategies such as `long_strangle` iterate through the full Cartesian product of all puts with `strike < spot` and all calls with `strike > spot`.
   - Without constraints on moneyness bounds (e.g. strike / spot between 0.70 and 1.30, or delta bounds), the scanner generates pairs across the entire strike spectrum (e.g. min strike 10 to max strike 160 for HYPE).

## Outcome

1. **Strike Moneyness & ATM Proximity Filtering**:
   - Introduce strike moneyness constraints in `ScanRequest` (e.g. `min_moneyness` and `max_moneyness`, defaulting to sensible bounds such as `[0.70, 1.30]` or configurable via API/UI).
   - Alternatively or additionally, support an ATM delta filter range or max strike distance from spot (e.g. filtering out contracts where delta is near zero `< 0.02` or `> 0.98` by default).

2. **Realistic Multi-Leg Candidate Pairing**:
   - Constrain leg generation in multi-leg strategies (`long_strangle`, `iron_condor`, `butterfly`, `vertical_spread`) to only combine legs within realistic relative distances and viable moneyness windows around ATM.

3. **Liquidity / Viability Guardrails in Synthetic Mode**:
   - Avoid creating synthetic quotes for contracts that have no open interest and zero trading volume when their strikes are deep OTM/ITM.

4. **Web UI & API Alignment**:
   - Allow users in the web interface to adjust or see the moneyness / strike proximity filter, while providing sensible defaults so deep OTM "ghost" strikes are excluded out-of-the-box.

## Source Context

- Core opportunity scanner: `src/options_lib/opportunity_scanner.py` (`_same_expiry_strategy_leg_sets`, `_scan_multi_leg_candidate`, `_precheck`, `ScanRequest`).
- Market data adapter: `src/bybit_api/options_market_data.py`.
- Scan API & validation: `src/options_app/api.py`.
- Web UI & form submission: `src/options_app/static/app.js`, `src/options_app/static/index.html`.
- Domain glossary: [CONTEXT.md](../../CONTEXT.md).

## Acceptance Criteria

- [x] `ScanRequest` supports filtering by strike moneyness (`min_moneyness`, `max_moneyness`) and/or delta proximity to prevent deep OTM/ITM phantom strikes.
- [x] Multi-leg strategy generators (`long_strangle`, `butterfly`, `iron_condor`, etc.) only generate candidate leg combinations within realistic moneyness and strike distance bounds around spot.
- [x] Scanner excludes deep OTM strikes (e.g., Put K50 when spot is ~91) unless the user explicitly expands moneyness/delta filters.
- [x] Automated tests verify that contracts far away from ATM are filtered out and multi-leg combinations do not pair extreme strikes.
- [x] Web UI and API handle moneyness/strike proximity gracefully with sensible default values.

