# UI-003 — Fix scanner empty-state borders and guide display

Status: done  
Branch: `fix/scanner-empty-state-borders`  
Worktree: `/Users/hoangviet/Flowsurface/.worktrees/scanner-empty-state-borders`  
Target: `main`

## Problem

In the Scanner results panel (`Bước 2 — Kết quả`), several containers with borders and background styling are rendered on initial load or during empty scan results, even when there is no content to display:

1. **`#valuation-mode-notice`**: Declared with `hidden` attribute in HTML, but `.valuation-mode-notice` in `styles.css` has `display: grid;`, overriding the browser user-agent's `[hidden] { display: none; }`. Because it specifies `border: 1px solid #9a683b` and padding `12px 14px`, it renders as a hollow orange rectangular border on initial load.
2. **`#results-guide`** ("Cách đọc nhanh"): Has `hidden` in HTML and `app.js` sets `resultsGuide.hidden = !opportunities.length`, but `.results-guide` has `display: grid;`, causing "Cách đọc nhanh" to always be rendered with its green border and background before any scan has taken place.
3. **`#historical-context`**: Declared with `hidden` in HTML, but `.historical-context` has `display: grid;`, rendering as a hollow dark green box with `border: 1px solid #486957;` and `background: #202b26;`.
4. **`#results-table-wrap` (Results table container)**: The results table header with 10 column titles and a bottom border line is visible when `tbody#results-body` is completely empty on initial load or after an empty scan.

## Outcome

Eliminate all orphan and hollow borders from the Scanner results panel when there are no results:

- Add universal `[hidden] { display: none !important; }` reset rule in `styles.css` to prevent any CSS class from overriding HTML5 `hidden` attribute.
- Add `:empty` display guards for notice and context elements so unpopulated elements never display borders or padding.
- Wrap the results table in a container (`#results-table-wrap`) that is hidden initially and stays hidden when a scan returns zero opportunities.
- Unhide `#results-table-wrap` and `#results-guide` only when valid opportunity candidates are returned.
- Preserve accessibility (`aria-live="polite"`, `role="status"`), responsive layout, and domain semantics (`CONTEXT.md`).

## Acceptance criteria

- [x] On initial page load, no empty orange border (`#valuation-mode-notice`), no hollow green border (`#historical-context`), no "Cách đọc nhanh" guide (`#results-guide`), and no empty table headers (`#results-table-wrap`) are visible in the Scanner results panel.
- [x] On initial load, the results panel cleanly displays only the step heading (`Bước 2 — Kết quả`), the initial state message (`Chọn điều kiện rồi bấm “Quét cơ hội”.`), and the historical volatility quality note.
- [x] When a scan produces zero opportunities, `#result-state` displays the explanation message ("Không có cơ hội đạt đủ điều kiện hiện tại."), while `#valuation-mode-notice`, `#results-guide`, and `#results-table-wrap` remain cleanly hidden without orphan borders.
- [x] When a scan produces opportunities, the results table headers, data rows, explanations, and `#results-guide` are displayed as expected.
- [x] Playwright E2E tests verify visibility transitions across initial, empty, and populated states.
- [x] Layout remains responsive and passes full test suite without regressions.

## Public seams under test

1. **Browser user flow — initial state:**
   Navigate to `#scanner`. Verify `#valuation-mode-notice`, `#results-guide`, `#historical-context`, and `#results-table-wrap` are hidden (`toBeHidden()`).
2. **Browser user flow — empty scan:**
   Submit an unmatchable scan filter. Verify `#result-state` is visible with empty explanation, while `#results-table-wrap` and `#results-guide` are hidden.
3. **Browser user flow — successful scan:**
   Submit a valid scan. Verify `#results-table-wrap` and `#results-body tr` are visible with expected columns and data.

## Non-goals

- No changes to pricing, valuation, or scanner domain logic.
- No modifications to the Backtest or Position Monitoring workspaces.
- No changes to API endpoints or contract schemas.

## QA inventory

- Initial render at 1280px desktop: verified clean results panel without empty borders (`test-results/screenshots/scanner-initial.png`).
- Initial render at 390px mobile: verified no horizontal overflow and clean results panel (`test-results/screenshots/scanner-mobile-empty.png`).
- Empty scan trigger: verified no ghost borders or empty table header (`test-results/screenshots/scanner-empty.png`).
- Successful scan: verified results table and guide render properly.

## Review outcome

- Standards review: `git diff --check` is clean. No whitespace errors or trailing blank lines.
- Safety & contract: domain semantics in `CONTEXT.md` are completely preserved. Read-only presentation surface behavior remains intact.
- Test verification: 23 Playwright tests pass in 36.2s; 298 Python tests pass in 15.9s.

