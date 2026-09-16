# Valuation remediation QA

Date: 2026-09-16  
Scope: read-only QA; this agent created only this report. Existing code and option strategies were treated as protected.

## Commands and results

| Command | Result | Evidence |
|---|---|---|
| `./.venv/bin/pytest -q` | PASS | `160 passed, 1 warning in 6.03s` |
| `npm run test:e2e -- --reporter=line` | PASS | Playwright started Uvicorn locally and completed `10 passed (11.3s)` |
| `git diff --check` | PASS | No whitespace errors reported |
| `rg --files -g 'package.json' -g 'playwright.config.js' -g 'e2e/**'` | PASS | E2E entrypoint is `e2e/options-scanner.spec.js`; config uses local `127.0.0.1:8002` |

The Playwright tests route `/api/v1/assets`, `/api/v1/opportunities/scan/stream`, and `/api/v1/scenarios` to fixtures in `e2e/options-scanner.spec.js`; no exchange credential or live network result is exercised. The local app server itself started successfully.

## Static inspection

### Legacy pricing fallback — not ready

`src/options_lib/pricing/black_scholes.py` still contains:

- default risk-free rate `0.05` in `OptionSpec` and `ProfessionalOptionsEngine` (lines 23 and 44);
- implied-volatility fallback `0.5` and floor `0.001` when IV is absent/falsey (lines 127–131);
- broad exception handling that returns intrinsic value with all Greeks set to zero (lines 198–211).

This can produce a numerically safe-looking result while hiding missing inputs or calculation failures. The full pytest run also emits the `py_vollib is deprecated` warning from line 4. The newer `price_fair_value` seam documents and enforces explicit IV/rate inputs, but the legacy engine remains a separate unsafe path.

### EV evidence — not ready for a positive-EV claim

The scanner keeps `expected_value_status="not_validated"` and `evidence_status="insufficient_evidence"` on opportunities (`src/options_lib/opportunity_scanner.py`, lines 168–182 and 376–390). Its gate is explicit: `include_unvalidated=False` produces `blocked_unvalidated` and rejection reason `evidence_not_validated` (lines 354–356 and 465).

`src/options_lib/ev_validation.py` provides a separate chronological train/holdout evaluator with fees, slippage, cost sensitivity, and a look-ahead flag (lines 100–148). The tests cover insufficient samples, non-positive held-out EV, and cost sensitivity. Static search found no production call that feeds scanner opportunities into `validate_backtest`; therefore this QA found no strategy-level historical evidence and makes no positive-EV claim.

### Volatility surface — caveats / not production-ready

The current surface is an observed/interpolated surface using linear interpolation in log-moneyness and total variance (`src/options_lib/volatility_surface.py`, lines 1–7 and 153–158). It has useful basic controls:

- invalid IV/price/quote/liquidity and expired observations become warnings;
- `is_valuation_ready` requires at least two valid points per expiry;
- out-of-range strike/expiry queries raise by default and only return `status="extrapolated"` when explicitly allowed (lines 161–179 and 208–225).

Static inspection found no SVI/SSVI fitter and no surface-level arbitrage, fit-error/RMSE, or calibration diagnostics. A quote can therefore be marked `observed`, `interpolated`, or `extrapolated`, but those statuses do not establish arbitrage-free calibration or market-fit quality.

### Protected strategy check — preserved

The existing strategy identifiers remain present in the scanner/UI/API paths, including `long_call`, `long_put`, verticals, `iron_condor`, `iron_butterfly`, `long_straddle`, `long_strangle`, `protective_put`, `covered_call`, `calendar_spread`, `butterfly`, and `broken_wing_butterfly`. This agent made no edits to strategy code or existing files.

## Readiness

- Automated regression: **ready with caveat** — pytest and mocked Playwright suites pass; the `py_vollib` deprecation warning remains.
- Explicit fair-value/surface status plumbing: **caveats** — statuses and sparse/extrapolation guards are observable, but the baseline surface lacks SVI/SSVI and arbitrage/fit diagnostics.
- Legacy pricing path: **not ready** — silent defaults and broad intrinsic-value fallback remain.
- EV/trading decision readiness: **not ready** — scanner signals are explicitly unvalidated and no integrated out-of-sample evidence was found.

Overall readiness: **not ready for production trading or a positive-EV claim**. The blockers are the legacy fallback path, absent integrated out-of-sample EV evidence, and incomplete surface calibration diagnostics. Browser QA should be repeated against a controlled live-data or recorded-data environment before release.
