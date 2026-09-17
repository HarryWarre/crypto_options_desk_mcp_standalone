# UI-003 — Comprehensive backend terminal system monitoring

Status: in progress  
Branch: `feat/terminal-backend-monitoring`  
Worktree: `/Users/hoangviet/Flowsurface/.worktrees/terminal-backend-monitoring`  
Target: `main`

## Problem

The current web application features a "scan-terminal" component (`#scan-terminal`), but it is tucked away inside a collapsed `<details class="technical-log">` element and only emits coarse, sporadic log messages for a subset of actions. Specifically:
1. It is hidden by default and framed merely as "Chi tiết kỹ thuật của lần quét" instead of functioning as a live operational console for the entire backend system.
2. During the opportunity scan flow, backend execution spans multiple critical phases (parameter validation, Bybit instrument discovery, market data loading, data quality checks, 30-day historical volatility fetching, volatility surface calibration, strategy candidate pricing, Greeks evaluation, EV/risk-reward computation, candidate filtering, and final ranking), but only coarse lines are streamed.
3. Other vital backend flows—such as asset catalog initialization, WebSocket live desk cycles, historical backtest replay, and read-only position monitoring—do not comprehensively log their operational steps to the terminal.
4. Terminal lines lack formatted timestamps, step indicators, and status classifications (info, success, warn, error).

## Outcome

Transform the terminal into a real-time, comprehensive monitoring console for the entire backend:
- Expose the terminal prominently (open by default, labeled as "Hệ thống theo dõi backend" / Backend System Monitor).
- Stream fine-grained, step-by-step progress from backend endpoints (`/api/v1/opportunities/scan/stream`, `/api/v1/opportunities/stream`, `/api/v1/backtests`, and `/api/v1/positions/stream`).
- Prepend timestamps `[HH:MM:SS]` and clear phase tags to every log message, with auto-scroll and visual status styling.
- Provide complete operational transparency into every step of market data ingestion, quantitative pricing, risk gating, and stream management.
- Preserve paper-trading and research safety constraints per `CONTEXT.md` (no automated trading or order execution).

## Acceptance criteria

- [ ] `<details class="technical-log">` is open by default and labeled as the backend monitoring system.
- [ ] `appendTerminal` prepends timestamps (`[HH:MM:SS]`), supports status styling (`success`, `error`, `info`), and auto-scrolls to the latest entry.
- [ ] Asset discovery flow logs initiation, discovered instruments, and completion status.
- [ ] Scan stream (`POST /api/v1/opportunities/scan/stream`) emits structured step logs through `_execute_scan` covering:
  - Step 1: Scan parameters, filters, and valuation mode (`executable`/`theoretical`/`synthetic`).
  - Step 2: Bybit market data loading (assets, active option count, issues).
  - Step 3: 30-day historical volatility context loading and status.
  - Step 4: Volatility surface calibration and valuation readiness.
  - Step 5: Strategy evaluation, pricing, Greeks, and EV/RR calculations.
  - Step 6: Scan completion with summary of valid opportunities, rejections, and elapsed time.
- [ ] Live desk WebSocket stream (`WS /api/v1/opportunities/stream`) logs connection states, cycle iterations, snapshot emissions, and interval countdowns to the terminal.
- [ ] Historical backtest flow logs start parameters, data replay progress, and final summary to the terminal.
- [ ] Position monitoring flow logs WebSocket connection events, reconciliation, and snapshot decisions (CLOSE, HOLD, REVIEW) to the terminal.
- [ ] "Xóa log" button clears the terminal without breaking subsequent logging.
- [ ] Python unit/UI tests pass.
- [ ] Playwright E2E suite passes and verifies terminal step logging and clear behavior.

## Public seams under test

1. **Terminal component rendering**:
   `#scan-terminal` inside `<details class="technical-log" open>` with accessibility attributes `role="log"` and `aria-live="polite"`.
2. **Progress streaming contract**:
   `POST /api/v1/opportunities/scan/stream` emitting NDJSON log events with step indicators.
3. **Browser user flow**:
   Scanning, live stream toggling, and backtesting visibly append step logs with timestamps into `#scan-terminal`.

## Non-goals

- No order placement or live account mutation.
- No alteration of core mathematical pricing formulas (SVI, Black-Scholes, Greeks).
- No removal of research and paper-trading disclaimers.

## Implementation slices

1. **Slice 1 (Documentation & Worktree)**: Create issue ticket and worktree `terminal-backend-monitoring`.
2. **Slice 2 (Backend Logging)**: Enhance `_execute_scan` and live stream in `src/options_app/api.py` with granular step progress messages.
3. **Slice 3 (Frontend Console)**: Update `index.html`, `app.js`, and `styles.css` with open-by-default terminal, timestamped log format, status classes, and comprehensive flow listeners.
4. **Slice 4 (Automated Tests & QA)**: Add E2E tests in `e2e/options-scanner.spec.js`, run Python tests, verify with Playwright, and review code standards.
5. **Slice 5 (Merge to Main)**: Commit, rebase, and merge into `main`.
