# UI-004 — Simplify UI & Remove Redundant AI Warnings

Status: in-progress
Branch: `feat/simplify-ui-clean-warnings`

## Problem

The Flowsurface interface currently contains numerous defensive disclaimers, caution banners, and redundant advisory notices generated during earlier AI iterations (such as *"Biến động lịch sử 30 ngày chỉ dùng làm ngữ cảnh/kiểm tra chất lượng; định giá vẫn dùng IV hiện tại. Khi quét live không tải lịch sử mark-price"*, *"không phải lợi nhuận đảm bảo"*, *"không tự gửi lệnh"*, *"không phải giá khớp"*).

These elements:
1. Clutter the screen and reduce information density.
2. Distract users from core pricing, greeks, and payoff analytics.
3. Make the tool look like an experimental AI prototype rather than a professional trading/research terminal.

## Outcome

Eliminate unnecessary cautionary disclaimers and defensive callout boxes across all workspace views (Scanner, Backtest, Monitoring), leaving a sleek, focused, professional interface.

## Scope of Changes

1. **Scanner View**:
   - Remove the `.quality-note` banner regarding 30-day historical volatility context.
   - Remove the `.results-guide` banner advising how to read results.
   - Remove `.chart-assumptions` under the payoff chart.
   - Streamline `.valuation-mode-notice` into a clean, minimal status indicator without defensive paragraphs.
   - Remove legal/defensive disclaimers from header and form field help texts (`research-note`, `không phải lợi nhuận đảm bảo`, `không phải lợi nhuận kỳ vọng`, `không phải giá khớp`).
   - Shorten scan result state messages and remove redundant `item.risk_note` banners inside opportunity cards.

2. **Position Monitoring View**:
   - Remove the `.monitoring-safety-note` banner (*"Không tự gửi lệnh..."*).
   - Simplify preset labels (e.g. replace *"Chỉ quan sát · an toàn nhất"* with *"Chỉ quan sát (Review)"*).
   - Clean up placeholder text and state messages.

3. **Backtest View**:
   - Clean up subheader disclaimers and scan notes to focus on parameters and execution facts.

4. **Automated Tests**:
   - Update `tests/test_options_app_ui.py` to assert the absence of redundant disclaimers while ensuring core functionality remains intact.
   - Update Playwright e2e test expectations in `e2e/options-scanner.spec.js`.

## Acceptance Criteria

- [ ] Redundant defensive banners (`.quality-note`, `.monitoring-safety-note`, `.results-guide`, `.chart-assumptions`) are removed.
- [ ] Field descriptions are concise and informative without legalistic disclaimers.
- [ ] Payoff chart renders cleanly without redundant assumption disclaimers.
- [ ] State messages and table labels are professional and compact.
- [ ] All unit and integration tests pass.
