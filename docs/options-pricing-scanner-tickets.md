# Options Pricing Scanner — Local Ticket Drafts

Status: local draft. The configured issue tracker and its `ready-for-agent` label were not available in this workspace, so these tickets have not been published remotely.

Source spec: [options-pricing-scanner-spec.md](options-pricing-scanner-spec.md)

Strategy-specific backlog: [options-scanner-strategy-tickets.md](options-scanner-strategy-tickets.md)

## Dependency order

```text
OPS-001 → OPS-002 → OPS-003 → OPS-004 → OPS-005 → OPS-006 → OPS-007
                         ↘ OPS-008 (validation/backtest evidence)
OPS-005 → OPS-010 (vertical spread scanner; STRAT-003…STRAT-006)
OPS-005 → OPS-011 (iron condor/butterfly; STRAT-009/STRAT-011)
```

## OPS-010 — Add vertical spreads to the opportunity scanner — implemented

Outcome: the read-only scanner finds bull/bear call and put verticals, values both legs from executable bid/ask quotes and the fitted surface, and exposes bounded-risk metrics without creating naked short candidates.

Acceptance criteria:

- `bull_call_vertical`, `bear_call_vertical`, `bull_put_vertical`, and `bear_put_vertical` are accepted by domain, API, and UI.
- Pairing requires the same asset, expiry, and option type, with distinct strikes and a protective long leg.
- Results include both typed legs, executable net entry, fair value, cost-adjusted edge, max loss, max profit, aggregate Greeks, and read-only execution status.
- Missing, invalid, illiquid, or unselected legs produce explicit rejection reasons.
- Scenario requests preserve the existing `call_vertical`/`put_vertical` evaluator identifiers.
- Detailed strategy tickets: [STRAT-003…STRAT-006](options-scanner-strategy-tickets.md).

Checks: vertical baseline `103 passed` Python tests and `5 passed` Playwright tests; current regression `112 passed` Python tests and `6 passed` Playwright tests, targeted Ruff clean.

## OPS-011 — Add Iron Condor and Iron Butterfly to the scanner — implemented

Outcome: the read-only scanner enumerates and values four-leg Iron Condor and Iron Butterfly candidates, and the scenario evaluator reports bounded payoff metrics.

Acceptance criteria:

- Iron Condor requires lower put wing, short put, short call, and upper call wing with strictly ordered strikes.
- Iron Butterfly requires lower put wing, equal-strike short put/call bodies, and upper call wing.
- Results expose all four typed legs, executable net entry, model fair value, costs, max loss, max profit, breakevens, aggregate Greeks, and evidence status.
- Missing wings, malformed legs, unprotected shorts, and invalid structures are rejected explicitly.
- API/UI accept and display `iron_condor` and `iron_butterfly`; scenario requests preserve those identifiers.

Checks: `112 passed` Python tests, `6 passed` Playwright tests, targeted Ruff clean.

## OPS-001 — Normalize multi-asset Bybit option contracts

Outcome: all downstream modules receive validated, chronologically ordered option contracts for every supported public Bybit options asset.

Blocking: none.

Acceptance criteria:

- The public asset catalog can be loaded from the paginated exchange instrument endpoint and returns supported options assets without a hardcoded-only list.
- Instrument discovery handles `baseCoin=All`, follows cursors until completion, deduplicates symbols, and keeps only actively trading instruments.
- Symbols, option type, strike, expiry, spot, IV, Greeks, quote, volume, and open interest are normalized into typed records.
- Expiry ordering uses parsed dates and correctly orders dates such as `25JUN27` after `25SEP26`.
- Invalid, duplicate, stale, and incomplete records are excluded or returned with explicit data-quality reasons.
- Discovery metadata is cached for a scan and requests use bounded concurrency, shared client state, and retry/backoff for transient exchange errors.
- Existing CLI/MCP analytics continue to work for BTC fixtures.

Public test seam: market-data adapter → normalized universe.

Checks: fixture normalization, malformed symbol, duplicate quote, stale quote, expiry ordering, supported asset discovery.

Out of scope: live websocket streaming and private account data.

## OPS-002 — Build observed and fitted volatility surface

Outcome: the system produces a timestamped surface for each asset with observed points, fitted values, interpolation status, and quality warnings.

Blocking: OPS-001.

Acceptance criteria:

- Surface points can be grouped by asset, expiry, and strike/delta coordinate.
- Invalid IVs, zero quotes, and insufficient liquidity do not silently become surface points.
- The output distinguishes observed, interpolated, and extrapolated values.
- Front/back expiry metrics and calendar comparisons use chronological dates.
- A sparse or malformed chain returns a usable warning and no false fair-value claim.

Public test seam: normalized chain → surface result.

Checks: smooth interpolation fixture, sparse chain, missing expiry, non-monotonic input order, extreme IV, duplicate points.

Out of scope: SVI/SSVI and machine-learning calibration.

## OPS-003 — Add fair-value pricing and Greeks interface

Outcome: callers can value one option or a strategy using a fair IV surface and receive auditable price/Greeks output.

Blocking: OPS-002.

Acceptance criteria:

- The valuation interface accepts contract, market snapshot, fair IV/carry configuration, and returns price, intrinsic value, time value, delta, gamma, theta, vega, time-to-expiry, and model status.
- Production calls cannot silently use a hardcoded IV or risk-free rate.
- Pricing invariants and expiry behavior are enforced.
- Market mid, theoretical price, fair IV, and IV edge are kept distinct.
- The existing standalone pricing behavior is covered by regression tests.

Public test seam: valuation request → valuation result.

Checks: call/put parity fixtures where applicable, IV sensitivity, expiration, negative/zero inputs, carry configuration, model status.

Out of scope: automated calibration to every exchange-specific settlement nuance.

## OPS-004 — Add scenario P&L and strategy evaluator — implemented

Outcome: a researcher can evaluate a candidate under price, IV, and time changes with capped-risk metrics.

Blocking: OPS-003.

Acceptance criteria:

- Scenarios support underlying move, IV move, elapsed days, and configurable exit assumptions.
- Single legs and defined-risk verticals return max loss, max profit, breakevens, P&L table, and position Greeks.
- The output clearly states when a scenario is outside the surface/model range.
- The evaluator includes fees, bid/ask, and slippage assumptions.

Public test seam: strategy definition + scenario set → scenario report.

Checks: debit put spread, debit call spread, flat price with time decay, IV crush, large move, wide spread, max-loss bound.

Out of scope: naked short options and live hedging.

## OPS-005 — Implement opportunity scanner and evidence gate

Outcome: the system ranks only opportunities that pass data, liquidity, model-edge, risk, and evidence gates.

Blocking: OPS-001, OPS-002, OPS-003, OPS-004; OPS-008 is required before claiming validated positive EV.

Acceptance criteria:

- Scan accepts multiple assets and filters for expiry, delta, liquidity, spread, IV edge, max loss, and strategy type.
- Each candidate includes pass/fail reasons and a data timestamp.
- “No qualified opportunity” is a valid result.
- The scanner distinguishes heuristic market context from model edge.
- Positive-EV status is withheld when the out-of-sample sample is insufficient or costs erase the edge.

Public test seam: scan request → ranked opportunities/rejections.

Checks: multi-asset scan, one asset failure with other assets succeeding, no candidates, edge below threshold, edge after costs, insufficient backtest evidence.

Out of scope: order creation and execution.

## OPS-006 — Add read-only scanner API — implemented

Outcome: the UI and other clients can request assets, scans, surface summaries, opportunity details, and scenario reports through a stable JSON interface.

Blocking: OPS-005.

Acceptance criteria:

- Endpoints expose asset catalog, scan request, scan result, candidate detail, and scenario report.
- Requests validate filters and return structured errors.
- API keys remain server-side; no private endpoint is exposed.
- Responses include timestamps, source status, model version, and data-quality warnings.
- API integration tests use a fake adapter and do not require Bybit network access.

Public test seam: HTTP request → JSON response.

Checks: valid scan, invalid filter, empty result, partial asset failure, timeout/error mapping, deterministic fixture response.

Out of scope: authentication and order mutation.

## OPS-007 — Build multi-asset opportunity scanner UI — implemented; browser QA pending

Outcome: a researcher can scan and inspect opportunities from a browser without reading raw JSON or terminal output.

Blocking: OPS-006.

Acceptance criteria:

- Initial view shows asset selector, scan controls, data timestamp/source status, and a clear empty/loading/error state.
- User can select multiple assets and submit a scan.
- Results show asset, expiry, strategy, direction, market/fair value, IV edge, max loss, expected value status, liquidity, and reasons.
- User can filter/sort results and open a candidate detail view with scenario P&L and Greeks.
- The UI makes clear that outputs are research/paper-trading signals.
- Desktop and narrow viewports have no clipped required controls or results.

Public test seam: browser user flow → visible scan results and detail state.

Checks: initial load, multi-asset scan, filters, sorting, detail open/close, no-result state, partial-error state, narrow viewport, densest table state.

Out of scope: trading buttons, account login, and mobile-native app.

## OPS-008 — Validate edge and positive expected value — historical data foundation implemented

Outcome: the project can persist/replay timestamped option snapshots and state whether a strategy has evidence of positive expected value after costs, or explicitly state that evidence is insufficient. Snapshot capture/replay is implemented here; completed trade-outcome generation and the held-out backtest remain follow-up work.

Blocking: OPS-001 through OPS-005 for the required data and strategy outputs.

Acceptance criteria:

- Historical option snapshots can be captured prospectively and stored in a reproducible, versioned JSONL format; Bybit mark-price history can be downloaded per option symbol.
- Bybit does not expose complete historical ticker snapshots through the public V5 REST API, so historical full-chain backfill is not claimed.
- Replayed snapshots select the latest source timestamp at or before `as_of` with an explicit maximum-age tolerance and never fall back to current data.
- Historical snapshots and option outcomes are separate inputs: snapshots enable signal replay, while outcomes are still required for EV validation.
- Backtests separate training/development periods from a held-out test period.
- Fees, spread, slippage, expiry handling, and missed fills are modeled.
- Reports include trade count, win/loss distribution, average win, average loss, expected value, drawdown, and sensitivity to costs.
- The scanner cannot label a strategy “validated positive EV” without minimum sample and held-out criteria.

Public test seam: historical fixture set → backtest report.

Checks: known profitable fixture, known unprofitable fixture, cost sensitivity, no-trade sample, look-ahead prevention.

Out of scope: a guarantee of future profitability and live deployment approval.

## OPS-009 — Full QA, Playwright, documentation, and review

Outcome: the release is reproducible, documented, and reviewed across backend and UI behavior.

Blocking: OPS-007 and OPS-008.

Acceptance criteria:

- Unit, integration, type/lint, and full-suite checks pass.
- Playwright functional checks cover the shared QA inventory and at least two off-happy-path cases.
- Playwright visual checks cover desktop, narrow viewport, empty/error state, and densest result state.
- A defect-first review reports no unresolved release-blocking findings.
- README documents setup, read-only safety model, model limitations, data-quality rules, and how to interpret positive-EV status.

Public test seam: repository test command and browser user flow.

Checks: full suite, API startup, UI startup, Playwright functional pass, visual pass, viewport fit, review-agent report.

Out of scope: deployment infrastructure and exchange order execution.

## Recommended implementation order

1. OPS-001 — Helmholtz / data normalization.
2. OPS-002 — pricing/surface worker.
3. OPS-003 — pricing/Greeks worker.
4. OPS-004 — scenario worker.
5. OPS-005 — scanner/orchestrator worker.
6. OPS-006 — API worker.
7. OPS-007 — UI worker.
8. OPS-008 — validation/backtest worker.
9. OPS-009 — review and QA owner.
