# PM-010 — Fix Expiry Date Retrieval in Options Strategy Builder

Status: in-progress  
Branch: `fix/builder-expiry-retrieval`  
Target: `main`  

Remote publication is pending because this repository has no configured issue tracker connection.

## Problem

When navigating to the **Options Strategy Builder** (`#builder`) in the application, the strategy builder fails to populate available expiration dates in the expiry selector dropdown (`#builder-expiry-select`) and displays an error state (`Không tải được: Failed to fetch chain for BTC`):

1. **Option Chain API 500 Internal Server Error**:
   - Calling `/api/v1/options/chain/{asset}` (e.g. `GET /api/v1/options/chain/BTC`) raises an unhandled exception:
     `AttributeError: 'OptionContract' object has no attribute 'expiry'`
   - The endpoint fails and returns HTTP 500 with error code `chain_fetch_failed`.

2. **Domain Model Property Mismatch**:
   - In `src/options_app/api.py`, `get_options_chain()` and `populate_builder_template()` assume `OptionContract` has fields `expiry`, `bid`, `ask`, and `underlying_price`, and that `universe` has `spot_prices`.
   - However, the actual canonical domain model `OptionContract` (defined in `src/bybit_api/options_market_data.py`) defines:
     - `expiry_at: datetime` (instead of `expiry`)
     - `bid_price: float | None` (instead of `bid`)
     - `ask_price: float | None` (instead of `ask`)
     - `spot_price: float` (instead of `underlying_price` or `universe.spot_prices`)
     - `mark_price: float`
     - `mark_iv: float`
   - Accessing `c.expiry` directly throws an `AttributeError`, completely breaking option chain retrieval and strategy auto-population.

3. **Masked by Outdated Unit Test Mocks**:
   - The test suite in `tests/test_builder_and_notebook_api.py` defined a `FakeOptionContract` and `FakeUniverse` with non-canonical attributes (`expiry`, `bid`, `ask`, `underlying_price`, `spot_prices`), allowing unit tests to pass while live runtime fails against `BybitOptionMarketDataAdapter`.

4. **Frontend Cascade**:
   - Because `/api/v1/options/chain/{asset}` returns 500, `loadBuilderOptionChain()` in `src/options_app/static/app.js` catches the error.
   - The expiry dropdown (`builder-expiry-select`) is left empty or cleared, preventing users from selecting any expiry dates or viewing strike ladders in the strategy builder.

## Root Cause Analysis

In `src/options_app/api.py`:
- `get_options_chain` (lines 1300–1338):
  ```python
  spot = float(universe.spot_prices.get(asset_norm, 0.0) if hasattr(universe, "spot_prices") else 0.0)
  ...
  for c in contracts:
      exp = c.expiry.isoformat() if hasattr(c.expiry, "isoformat") else str(c.expiry)
      bid = float(c.bid or 0.0)
      ask = float(c.ask or 0.0)
  ```
- `populate_builder_template` (lines 1350–1375):
  ```python
  "expiry": c.expiry.isoformat() if hasattr(c.expiry, "isoformat") else str(c.expiry),
  "bid": float(c.bid or 0.0),
  "ask": float(c.ask or 0.0),
  ```

In `OptionContract`:
- The expiration field is `expiry_at` (or `getattr(c, "expiry_at", getattr(c, "expiry", None))`).
- The bid/ask quote fields are `bid_price` and `ask_price`.
- The spot price is stored on each contract as `spot_price` (or fallback to `spot_prices` dict if present on custom mocks).

## Proposed Solution

1. **Normalize Contract Attribute Extraction in `api.py`**:
   - Update `get_options_chain()` and `populate_builder_template()` to safely access canonical `OptionContract` attributes with backwards-compatible fallbacks:
     - Expiry: `getattr(c, "expiry_at", getattr(c, "expiry", None))`
     - Bid: `getattr(c, "bid_price", getattr(c, "bid", 0.0)) or 0.0`
     - Ask: `getattr(c, "ask_price", getattr(c, "ask", 0.0)) or 0.0`
     - Spot: `getattr(c, "spot_price", getattr(c, "underlying_price", 0.0)) or 0.0`
   - Ensure spot price extraction correctly resolves from `contracts[0].spot_price` when `universe.spot_prices` does not exist.

2. **Update Unit & Integration Tests**:
   - Update `FakeOptionContract` in `tests/test_builder_and_notebook_api.py` to match real `OptionContract` attributes (`expiry_at`, `bid_price`, `ask_price`, `spot_price`).
   - Add regression tests verifying `get_options_chain` and `populate_builder_template` work with canonical `OptionContract` instances as well as mocks.

3. **Frontend Resilience**:
   - In `src/options_app/static/app.js`, ensure graceful fallback handling and clear error messaging if an asset returns zero expiries.

## Source Context

- Option Chain & Builder API endpoints: `src/options_app/api.py` (`get_options_chain`, `populate_builder_template`).
- Domain models: `src/bybit_api/options_market_data.py` (`OptionContract`, `NormalizedOptionUniverse`).
- Strategy Builder logic: `src/options_lib/strategy/builder.py`.
- Frontend Strategy Builder controller: `src/options_app/static/app.js`.
- Test suite: `tests/test_builder_and_notebook_api.py`.

## Acceptance Criteria

- [ ] `/api/v1/options/chain/{asset}` successfully extracts expiration dates, strike ladders, spot price, and bid/ask quotes from canonical `OptionContract` objects without `AttributeError`.
- [ ] `/api/v1/builder/populate` correctly populates strategy legs from live option contracts without `AttributeError`.
- [ ] The Strategy Builder UI successfully populates `#builder-expiry-select` with sorted expiration dates (e.g. `2026-09-25`, `2026-10-02`, etc.) when an asset is selected.
- [ ] Unit and integration tests verify contract normalization and pass against both canonical `OptionContract` and mocked adapters.
