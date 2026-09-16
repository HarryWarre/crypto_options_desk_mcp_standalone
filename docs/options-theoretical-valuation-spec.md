# Theoretical Option Valuation and Historical Timestamp Resilience

Status: implemented on `feat/theoretical-option-scan`. The repository has no
configured issue-tracker guide,
remote issue connection, `gh` CLI, or available `ready-for-agent` label, so
this spec is not published remotely.

## Problem Statement

The live Bybit option scanner currently treats a contract without a positive
bid and ask as unusable. This is conservative for executable trade ideas, but
it prevents users from obtaining a theoretical valuation for thin markets such
as MNT, HYPE, XAUT, and some XRP contracts even when the underlying price,
strike, expiry, mark price, mark IV, and other model inputs are available.

The scanner also fails during the historical-volatility loading step when the
repository's existing naive-UTC clock is passed into a context that expects an
aware UTC timestamp. The failure escapes the stream endpoint and the user
receives no scan result.

## Solution

Add an explicit valuation mode to the scan contract. `executable` remains the
default and keeps the current bid/ask requirements. `theoretical` is an
explicit user choice that allows missing or zero bid/ask quotes when the
remaining model inputs are valid.

Theoretical results are clearly marked as non-executable. They may expose
mark-price reference data, current-surface fair IV, fair price, Greeks, expiry
payoff, model EV, win probability, risk/reward, and model payoff bounds when
fair value is used as the model entry. They must not claim an executable entry,
edge after costs, maximum tradable loss, or positive trading opportunity when
no bid/ask quote exists. The UI and API must keep theoretical valuations
separate from executable opportunities or make the distinction impossible to
miss.

Normalize timestamps at the historical-volatility boundary. A naive datetime
from the existing repository convention is interpreted as UTC and normalized
to an aware UTC datetime for historical-volatility context objects. Already
aware timestamps continue to be converted to UTC. A malformed timestamp still
produces an explicit degraded context rather than crashing the scan stream.

## User Stories

1. As a scanner user, I want executable valuation to remain the default, so
   that existing results retain conservative trading semantics.
2. As a researcher, I want to opt into theoretical valuation, so that thin
   Bybit option markets can still be analyzed when bid/ask is absent.
3. As a researcher, I want the theoretical mode to use only valid model
   inputs, so that missing prices do not become invented quotes.
4. As a user, I want theoretical results labeled as non-executable, so that I
   do not mistake a model value for a fillable market opportunity.
5. As a user, I want the UI to explain why bid/ask was bypassed, so that I can
   understand the limitation of the result.
6. As an API consumer, I want the requested valuation mode echoed in the scan
   context and result metadata, so that downstream consumers can enforce the
   same safety distinction.
7. As an API consumer, I want existing executable request and response fields
   to remain compatible, so that current clients do not break.
8. As a researcher, I want theoretical values to retain fair IV, fair price,
   model status, and Greeks, so that the result remains useful for comparison.
9. As a researcher, I want missing bid/ask to prevent executable edge metrics
   rather than producing zero or fabricated values, so that ranking remains
   honest.
10. As a user, I want one asset's malformed or missing quotes to degrade only
    that asset, so that other assets can still be scanned.
11. As a user, I want a scan to complete when the historical-volatility API
    receives a naive UTC timestamp, so that timezone representation does not
    break the live scanner.
12. As a user, I want aware and naive UTC timestamps to produce equivalent
    historical context, so that replay and live paths agree.
13. As a user, I want historical-volatility fetch errors shown as quality
    status rather than an unhandled stream exception, so that I can distinguish
    degraded context from a failed market-data scan.
14. As a user, I want the result count to distinguish theoretical valuations
    from executable trade ideas, so that a large model-only list is not read as
    a large set of tradable opportunities.
15. As a product owner, I want the live scan never to fetch mark-price history
    merely because theoretical mode is enabled, so that live valuation remains
    bounded and source limitations remain explicit.
16. As a maintainer, I want deterministic API, unit, and browser tests for both
    modes and timestamp forms, so that future refactors cannot reintroduce the
    failure.

## Implementation Decisions

- Add a typed valuation mode with `executable` and `theoretical` values. The
  default is `executable` for backward compatibility and safety.
- Keep the mode in the public scan request and normalized scan context. The
  browser exposes it as an explicit opt-in control in the default form, with
  Vietnamese copy explaining that it is model-only and may lack executable
  quotes.
- Extend normalized option quote data so missing bid/ask can be represented
  without losing valid mark price, mark IV, underlying, Greeks, volume, open
  interest, strike, or expiry. The executable path continues to reject
  non-positive or inverted bid/ask.
- Permit surface construction and fair-value pricing in theoretical mode when
  the model has a valid underlying, expiry, positive IV, and sufficient
  surface/liquidity data. Do not use historical volatility as a replacement
  for current surface IV.
- Define a theoretical result as non-executable whenever bid or ask is absent
  or non-positive. Do not calculate executable entry, exit, spread-adjusted
  edge, fee/slippage edge, or a tradable max-loss claim from a mark price.
  Expiry payoff, EV, win probability, risk/reward, and model max-loss/max-profit
  may still be calculated using fair value as a clearly labeled model entry.
  If a reference mark price is shown, label it as a non-executable reference.
- In theoretical mode, report `max_spread_pct`, `min_edge_after_costs`,
  `max_loss`, and `min_expected_value` as ignored execution filters. The
  browser disables those inputs; the API may accept them for compatibility but
  must expose the ignored list. The default EV gate must never remove a
  theoretical candidate; any displayed EV is a model estimate from fair-value
  entry, not an executable edge or historical result.
- Preserve a separate executable opportunity collection and expose theoretical
  valuations through an explicit collection or an equivalently typed status;
  consumers must not need to infer the distinction from null numeric fields.
- Keep strategy and structural validation active in theoretical mode. Bypassing
  bid/ask must not bypass expiry, strike, IV, surface, liquidity-quality, or
  defined-risk structure checks.
- Normalize historical-volatility timestamps at the context boundary. Treat a
  naive datetime as UTC, convert aware values to UTC, and preserve the source
  observation timestamp separately from retrieval/request timestamps.
- Do not change the repository-wide `now_utc()` convention as part of this
  feature; the narrow boundary adapter prevents an unrelated regression in
  legacy callers.
- Isolate per-asset quote and historical-context failures. A missing quote or
  history record for one asset must not erase successful results for another.
- Keep mark-price-history replay separate from both executable and theoretical
  live valuation. Theoretical mode may use the latest ticker mark reference,
  not historical candles.

## Testing Decisions

- Test the canonical scan API as the highest seam for request validation,
  mode selection, result metadata, backward compatibility, and per-asset
  degradation. Use injected deterministic adapters and scanners.
- Test the normalized market-data adapter at its public load-universe seam for
  positive bid/ask, missing bid/ask, zero bid/ask, and invalid mark inputs.
- Test the pricing/scanner result contract with independent expected values:
  executable mode keeps current edge semantics; theoretical mode returns fair
  value/Greeks but no executable edge claim.
- Test the browser flow through the visible form and result state. Verify the
  opt-in control, warning copy, outgoing mode, and separate theoretical label.
- Test both aware and naive `now_fn`/request timestamps through the historical
  context loader and the stream API. The original naive-clock traceback must
  be a regression case.
- Test an asset with missing quotes next to an asset with valid quotes to prove
  failure isolation.
- Test that enabling theoretical mode does not call mark-price history and
  does not change the executable result path when all quotes are present.
- Run the existing full Python suite, focused API/UI tests, targeted lint, and
  Playwright E2E tests before integration.

## Out of Scope

- Treating mark price as an executable bid or ask.
- Claiming positive expected value, probability of profit, or order-fill
  feasibility from theoretical valuations.
- Reconstructing historical bid/ask, historical IV, or historical Greeks.
- Fetching mark-price candles during a live scan.
- Changing the volatility-surface methodology or fair-value model.
- Adding order placement, account mutation, authentication, or execution.
- Changing the global datetime convention for unrelated modules.
- Publishing issues to a remote tracker unavailable in this workspace.

## Further Notes

The expected result is deliberately asymmetric: an illiquid asset may show
more theoretical values than executable opportunities, but only the latter
may be ranked as tradeable candidates. A theoretical list is useful for model
comparison and market coverage, not for execution decisions.
