# UI-006 — Consolidate Scanner Opportunity Cards & Remove Rejection Logs

Status: merged
Branch: `main`

## Problem

In the Options Scanner workspace, results are currently presented in two duplicate formats simultaneously:
1. A legacy HTML table (`#results-table-wrap`, `tbody#results-body`) with columns like *Tài sản / mã / strikes*, *Hạn*, *Chiến lược*, *Giá vào/ra*, *Thanh khoản*, etc.
2. A modern, explanatory card format (`#opportunity-explanations`, `.explanation-card`) showing strategy takeaways, structured leg details, Greeks, win probability, EV, and break-evens.

This duplication causes several usability and functional problems:
- **Visual Clutter & Redundancy**: Users see the exact same opportunity listed twice in different styles right next to each other.
- **Ambiguous Action Buttons**: Both the table and the card include action buttons like *"Xem payoff / P&L"* and *"📈 Xem Payoff chi tiết"*, confusing the user and breaking automated test locators (such as Playwright strict-mode violations for `getByRole('button', { name: 'Xem payoff' })`).
- **Noisy Rejection Logs**: Every candidate rejected by validation rules (e.g. `Loại long_strangle:BTC-19SEP26-...: invalid_market_data · leg_1_leg_invalid_market_data...`) is dumped into `#secondary-results` in bright red error text, pushing actual valid opportunities down and overwhelming users with internal engine validation failures.

## Outcome

- **Eliminate Rejection Logs**: Stop rendering candidate filter rejection logs to the DOM in `#secondary-results`. Rejections remain available in internal backend telemetry/terminal logs if needed.
- **Consolidate on Modern Cards**: Retire the legacy `#results-table-wrap` and promote the explanatory card format as the single authoritative representation for scanned opportunities.
- **Feature & Data Parity**: Ensure all data and functionality from the legacy table are preserved and prominently displayed in the cards:
  - Contract symbols for all legs and underlying asset.
  - Expiration date and remaining days (DTE: "Còn X ngày").
  - Liquidity statistics (Open Interest & 24h Volume).
  - Mode-specific quote indicators (*"Tham khảo"* in Theoretical mode, *"Giả định"* in Synthetic mode).
  - Action buttons: *"📈 Xem payoff / P&L"*, *"🛠 Mở trong Strategy Builder"*, and *"➕ Lưu Sổ tay"*.
- **Clean Empty & Error States**: Scanner cleanly displays empty state messages without orphan table headers or borders.

## Scope of Changes

1. **`src/options_app/static/app.js`**:
   - Update `renderOpportunityExplanation(item, index)` to display leg contract symbols, DTE, liquidity facts, and mode-aware payoff button labels.
   - Update `renderResults(payload)` to only populate `#opportunity-explanations`, removing legacy table row generation and `renderScanRejections(payload.rejections)`.
2. **`src/options_app/static/index.html`**:
   - Remove redundant `#results-table-wrap`.
3. **`src/options_app/static/styles.css`**:
   - Adjust styling for cards and action buttons as needed for optimal spacing and responsiveness.
4. **`e2e/options-scanner.spec.js` & `tests/`**:
   - Update test locators targeting `#results-body` to verify `#opportunity-explanations`.
   - Ensure all automated unit and e2e tests pass cleanly.

## Acceptance Criteria

- [x] Filtered candidate rejection logs (`Loại <symbol>: ...`) are no longer rendered in the UI.
- [x] Only the modern card view is rendered for opportunities; legacy duplicate table is removed.
- [x] Each card contains full leg symbols, DTE ("Còn X ngày"), liquidity (OI & Volume), valuation hints, and all 3 action buttons.
- [x] Playwright e2e test suite and pytest pass with 100% success rate.
- [x] Changes are committed on a dedicated worktree branch and rebase-merged into `main`.
