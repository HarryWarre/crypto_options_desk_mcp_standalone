# PM-011 — Fix Strategy Builder Profit & Cost Projections and Scanner Signal Handoff

Status: in-progress  
Branch: `fix/builder-profit-cost-projection`  
Target: `main`  

Remote publication is pending because this repository has no configured issue tracker connection.

## Problem

When following a signal from the **Opportunity Scanner** (e.g. BTC Iron Condor with strikes Put K64000 / Put K81000 / Call K83000 / Call K84000 expiring 2026-10-02) and replicating or opening it in the **Options Strategy Builder**, the profit/cost projection display shows nonsensical metrics:

- **Chi phí ròng**: `$55.00`
- **Lợi nhuận tối đa**: `$-55.00` (Negative maximum profit)
- **Thua lỗ tối đa**: `$-17055.00`
- **Điểm hòa vốn**: `Không có`
- **Payoff Chart**: Inverted and downward sloping, showing guaranteed losses across all price points.

In contrast, the Scanner signal correctly projected:
- **Tiền vào/ra ước tính**: Nhận credit khoảng `2245.00`
- **Lãi tối đa**: `2245.00`
- **Lỗ tối đa**: `14755.00`
- **Hòa vốn**: `K78755.00`
- **PoP**: `69%`

### Root Causes

1. **Unsynchronized Leg Market Price / IV on Manual Strike & Type Edits in Builder**:
   - In `src/options_app/static/app.js`, when a user selects an Iron Condor preset, default legs are populated with default strikes and market prices (e.g. Put K82000 @ $2,575, Put K80000 @ $1,550).
   - When the user edits the `Strike` input (`inpStrike`) in the table to match the Scanner signal (changing Put K82000 to K64000 and Put K80000 to K81000), `app.js` only updates `leg.strike = Number(inpStrike.value)`.
   - It **does not update** `leg.mid_price`, `leg.bid`, `leg.ask`, or `leg.iv` from the active option chain (`builderState.chainData`).
   - Consequently, Put K64000 (deep OTM, actual market price ~$25) retained the price of Put K82000 ($2,575), and Put K81000 (ATM, actual market price ~$2,000) retained $1,550.
   - This caused an inverted spread: paying $2,575 for a deep OTM put and receiving only $1,550 for an ATM put, turning an intended **credit** spread into an unintended **debit** spread with a guaranteed loss of -$55.

2. **Broken Data Field Mapping in Scanner-to-Builder Handoff (`openOpportunityInBuilder`)**:
   - In `src/options_app/static/app.js`, `openOpportunityInBuilder(item)` attempts to extract:
     `l.market_price || l.market_mid || 0` and `l.bid || 0`, `l.ask || 0`, `l.implied_volatility`.
   - However, the canonical `OpportunityLeg` and scanner serialized objects use:
     `l.bid_price`, `l.ask_price`, `l.fair_price`, `l.mark_price`, `l.market_iv`.
   - Because `l.market_price` and `l.market_mid` do not exist on `OpportunityLeg`, `mid_price` falls back to `0`, `bid` falls back to `0`, and `iv` falls back to default `0.65`.
   - Additionally, `openOpportunityInBuilder` does not update the asset select (`#builder-asset-select`) or expiry select (`#builder-expiry-select`), nor does it trigger option chain loading for that asset.

3. **Ambiguous Debit vs. Credit UI Labeling and Lack of Inversion Warnings**:
   - In the builder metrics strip:
     - `bmNetPremium` is unconditionally labeled `Chi phí ròng` (Net Cost), displaying negative numbers for net credit (e.g. `$-2245.00`) and positive numbers for net debit (e.g. `$55.00`).
     - When `max_profit < 0` (e.g. `$-55.00`), the UI simply displays `Lợi nhuận tối đa $-55.00` without warning the user that the strategy is structurally impaired (negative max profit means guaranteed loss in 100% of outcomes due to inverted pricing).
     - The UI should clearly distinguish between **Credit nhận về** (net premium < 0) and **Chi phí trả (Debit)** (net premium > 0), and provide a warning banner when a spread has inverted leg pricing.

## Proposed Solution

1. **Auto-Lookup Market Quotes on Leg Edits in Strategy Builder**:
   - In `src/options_app/static/app.js`, whenever the user changes `Strike` or `Option Type` (Call/Put) on any leg in `renderBuilderLegs()`:
     - Automatically look up the matching contract in `builderState.chainData.contracts` for the leg's expiry, strike, and option type.
     - If a matching contract is found, auto-fill `leg.mid_price`, `leg.bid`, `leg.ask`, `leg.iv`, and `leg.symbol`.
     - If no exact quote exists in the chain, calculate or estimate fair value using Black-Scholes based on the current spot, strike, and average IV, and flag it as estimated.
     - Trigger `evaluateBuilder()` with the updated market prices.

2. **Fix Scanner-to-Builder Handoff (`openOpportunityInBuilder`)**:
   - Correctly map `OpportunityLeg` fields:
     - `mid_price`: `(l.bid_price + l.ask_price) / 2` if available, else `l.mark_price || l.fair_price || 0`
     - `bid`: `l.bid_price || 0`
     - `ask`: `l.ask_price || 0`
     - `iv`: `l.market_iv || l.fair_iv || 0.65`
     - `option_type`: `String(l.option_type || "").toLowerCase()`
     - `expiry`: `l.expiry_at || l.expiry || ""`
   - Synchronize workspace controls:
     - Set `builderState.asset = asset` and `builderAssetSelect.value = asset`
     - Set `builderState.expiry = expiry` and update `builderExpirySelect`
     - Load the option chain for the asset in the background so the chain table aligns with the selected opportunity.

3. **Improve Payoff Metrics UI (Debit/Credit Clarity & Inversion Guardrail)**:
   - For Net Premium:
     - If `net_premium < 0`: display as **Thu về (Credit): $X.XX** (positive magnitude, styled in green/credit).
     - If `net_premium > 0`: display as **Chi phí ròng (Debit): $X.XX** (styled in standard text).
   - For Max Profit:
     - If `max_profit < 0`: display as **Không có lãi (Lỗ mọi kịch bản)** with a clear warning tag, instead of confusingly stating `Lợi nhuận tối đa $-55.00`.
   - Add a visual alert badge if leg prices violate standard monotonicity (e.g. deep OTM put price > ATM put price).

4. **Add Comprehensive Automated Tests**:
   - Add unit tests verifying `openOpportunityInBuilder` correctly maps all `OpportunityLeg` attributes from scanner signals.
   - Add unit tests for `evaluate_builder_strategy` covering credit iron condors, debit vertical spreads, and inverted pricing edge cases.
   - Add Playwright E2E test verifying clicking "Mở trong Builder" from a Scanner iron condor opportunity populates identical strikes, positive credit, and correct max profit/loss in Strategy Builder.

## Source Context

- Strategy Builder UI logic: `src/options_app/static/app.js` (`renderBuilderLegs`, `openOpportunityInBuilder`, `evaluateBuilder`).
- Strategy Builder Evaluation Engine: `src/options_lib/strategy/builder.py` (`evaluate_builder_strategy`).
- Strategy Builder API Endpoints: `src/options_app/api.py` (`evaluate_builder`, `populate_builder_template`).
- Opportunity Scanner Data Models: `src/options_lib/opportunity_scanner.py` (`Opportunity`, `OpportunityLeg`).
- Test Suite: `tests/test_builder_and_notebook_api.py`, `e2e/options-scanner.spec.js`.

## Acceptance Criteria

- [ ] Changing a leg's strike or option type in the Strategy Builder legs table automatically looks up the live contract from `chainData` and updates `mid_price`, `bid`, `ask`, and `iv`.
- [ ] Clicking "🛠 Mở trong Builder" from any Opportunity card in the Scanner faithfully carries over all leg symbols, strikes, option types, market prices, and IVs.
- [ ] For an Iron Condor matching the Scanner signal (Put K64000/K81000/Call K83000/K84000), Strategy Builder projects positive max profit matching the received net credit (~$2,245), not -$55.00.
- [ ] Net premium clearly differentiates between Credit (thu về) and Debit (chi phí trả).
- [ ] If legs produce a negative max profit (due to inverted pricing), the UI explicitly warns the user instead of displaying `Lợi nhuận tối đa $-55.00`.
- [ ] Automated tests cover contract lookup on leg edit and scanner-to-builder handoff fidelity.
