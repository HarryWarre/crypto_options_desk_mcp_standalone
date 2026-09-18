# SCAN-006 — Fix Scanner Datetime Timezone Mismatch in Market Context & Provenance

Status: verified  
Branch: `fix/scanner-timezone-awareness`  
Worktree: `/Users/hoangviet/Flowsurface/.worktrees/scanner-timezone-awareness`  
Target: `main`  

Remote publication is pending because this repository has no configured issue tracker connection.

## Problem

When running an opportunity scan from the web workspace or API (`POST /api/v1/opportunities/scan/stream` or `POST /api/v1/opportunities/scan`), the scan fails immediately after Step 4/6:

```log
[08:40:40] [OPTIONS] [STEP 3/6] historical volatility ready: 0/1 assets available
[08:40:40] [OPTIONS] [STEP 4/6] calibrating volatility surfaces & valuation models (mode=synthetic)
[08:40:40] LỖI: Opportunity scan failed
```

### Root Cause Analysis

1. **Market Data Universe Valuation Time**:
   In `BybitOptionMarketDataAdapter.load_universe()` (`src/bybit_api/options_market_data.py`), `as_of = fixed_valuation_time or ensure_utc_datetime(self._now_fn())` assigns `valuation_time` to `NormalizedOptionUniverse`. In `src/bybit_api/utils.py`, `ensure_utc_datetime()` normalizes datetimes to naive UTC (`replace(tzinfo=None)`).
2. **Contract Expiry Time**:
   Each `OptionContract.expiry_at` in the loaded universe is explicitly parsed with `tzinfo=UTC`.
3. **Mismatched Timezone Comparison**:
   In `_execute_scan()` (`src/options_app/api.py`), between Step 4 and Step 5:
   - `_market_context_from_universe(universe)` computes DTEs:
     ```python
     dtes = [
         max(0.0, (contract.expiry_at - valuation_time).total_seconds() / 86_400.0)
         for contract in contracts
         if contract.expiry_at.tzinfo is not None and contract.expiry_at > valuation_time
     ]
     ```
     Comparing `contract.expiry_at` (aware UTC) with `valuation_time` (naive) raises:
     `TypeError: can't compare offset-naive and offset-aware datetimes`.
   - `SignalProvenance.manual(..., as_of=universe.valuation_time)` calls `_as_utc()` (`src/options_lib/strategy_head_provenance/models.py`), which raises:
     `ValueError: as_of must be timezone-aware`.
   - `StrategyHeadRuntime.decide(..., now=universe.valuation_time)` also returns `context_invalid` if `observed_at.tzinfo is None` or `checked_at.tzinfo is None`.
4. **Error Masking in SSE Stream**:
   The exception raised between Step 4 and Step 5 is caught by the outer generator `except Exception` in `scan_stream`, which yields `{"type": "error", "code": "scan_failed", "message": "Opportunity scan failed"}`, masking the underlying exception details from the user.

## Outcome

- Ensure `valuation_time` in `NormalizedOptionUniverse`, `_market_context_from_universe`, and `_execute_scan` is consistently normalized to timezone-aware UTC (`UTC`).
- Safely handle mixed naive/aware datetimes defensively so that comparisons between `expiry_at` and `valuation_time` never crash with `TypeError`.
- Ensure `SignalProvenance` and `StrategyHeadRuntime` receive valid timezone-aware `as_of` and `now` datetimes.
- Successfully complete the scan flow through Step 5/6 and Step 6/6 and return ranked opportunities.
- Keep paper-trading and research safety constraints per `CONTEXT.md` intact.

## Source Context

- Domain glossary: [CONTEXT.md](../../CONTEXT.md) (Opportunity decision metrics, evidence states).
- Engineering workflow: `docs/agent-rules/engineering-workflow.md`.
- Testing and QA rules: `docs/agent-rules/testing-and-qa.md`.
- Product safety rules: `docs/agent-rules/product-safety.md`.

## Acceptance Criteria

- [x] `_market_context_from_universe()` handles both timezone-naive and timezone-aware `universe.valuation_time` gracefully without raising `TypeError`.
- [x] `_execute_scan()` normalizes `universe.valuation_time` to timezone-aware UTC before delegating to `StrategyHeadRuntime` and `_provenance_for_runtime_decision`.
- [x] `BybitOptionMarketDataAdapter.load_universe()` provides a timezone-aware UTC `valuation_time` matching contract expiries.
- [x] `POST /api/v1/opportunities/scan/stream` successfully completes all 6 steps with live Bybit market data and returns candidate opportunities.
- [x] `POST /api/v1/opportunities/scan` completes successfully and returns serializable opportunities and provenance.
- [x] Focused unit tests in `tests/test_scanner_timezone_safety.py` pass and cover both naive and aware inputs.
- [x] Existing test suite passes with no regressions.

## Public Seams Under Test

1. **Market context extraction**:
   `_market_context_from_universe(universe)` with both naive and UTC-aware `valuation_time`.
2. **Scanner execution flow**:
   `_execute_scan(...)` completing all 6 steps without uncaught datetime exceptions.
3. **HTTP scan stream endpoint**:
   `POST /api/v1/opportunities/scan/stream` emitting step 1 to step 6 logs and the `result` event.

## Non-Goals

- No changes to core pricing models (Black-Scholes, SVI/SSVI surface calibration, numerical Greeks).
- No changes to user-facing filter contracts.
- No live order placement or exchange mutations.

## Implementation Slices

1. **Slice 1 (Issue & Worktree Setup)**: Create issue ticket and worktree `scanner-timezone-awareness`.
2. **Slice 2 (Failing Test)**: Add failing unit tests reproducing the offset-naive vs offset-aware datetime errors in `tests/test_scanner_timezone_safety.py`.
3. **Slice 3 (Timezone Defensive Normalization)**: Update `options_market_data.py` and `options_app/api.py` to ensure timezone-aware UTC across universe valuation, market context, and signal provenance.
4. **Slice 4 (Verification & QA)**: Run unit tests, verify live scan stream with curl, and check full regression suite.
5. **Slice 5 (Review & Merge)**: Review diff against repo standards, commit slice, and rebase/merge to `main`.
