# Multi-Asset Crypto Options Valuation & Opportunity Scanner

Status: local draft, ready for review. Issue-tracker publication is pending because no configured tracker or tracker guide is available in this workspace.

## Problem Statement

The current repository exposes useful Bybit options analytics through CLI and MCP tools, including GEX, vanna, skew, flow, IV–RV comparison, and portfolio Greeks. It does not yet provide a durable valuation workflow or a user-facing interface that scans the currently supported Bybit option universe across multiple assets.

The user needs to move from reading market indicators to evaluating concrete option opportunities: fair implied volatility, theoretical value, Greeks, scenario P&L, liquidity, transaction costs, and evidence that a strategy has positive expected value after costs. The system must make it explicit when no opportunity passes the quality gates; it must not turn heuristic labels into automatic trade recommendations.

## Solution

Build a read-only, source-backed options valuation and opportunity scanner with:

- A normalized multi-asset Bybit options universe.
- A cleaned observed volatility surface indexed by asset, expiry, and strike/delta.
- A fitted fair-volatility surface used to estimate theoretical option value.
- A valuation result containing market price, fair value, IV edge, Greeks, liquidity, and data quality.
- Scenario analysis for underlying moves, IV moves, and time decay.
- A conservative opportunity scorer that includes fees, bid/ask spread, slippage, max loss, and out-of-sample evidence.
- A web interface that lets a user scan supported assets, filter candidates, inspect why a candidate passed or failed, and open a detailed scenario view.

The first production-shaped version is a research and paper-trading tool. It is read-only and must never place orders.

## User Stories

1. As a crypto options researcher, I want to see every supported Bybit options asset, so that I can scan beyond BTC.
2. As a researcher, I want the asset list to refresh from the exchange rather than be hardcoded, so that newly supported assets are not silently omitted.
3. As a researcher, I want to select one or many assets, so that I can compare opportunity quality across the universe.
4. As a researcher, I want to see the spot price and data timestamp for every scan, so that I know how fresh the inputs are.
5. As a researcher, I want invalid, stale, duplicated, or illiquid option quotes excluded or flagged, so that bad data does not become a false opportunity.
6. As a researcher, I want expiry strings normalized into real dates, so that front and back expiries are ordered chronologically.
7. As a researcher, I want to inspect the observed IV surface by expiry and strike or delta, so that I can see the market's volatility shape.
8. As a researcher, I want a fitted fair IV surface, so that I can compare each option with nearby and comparable options.
9. As a researcher, I want the surface to expose its interpolation range and missing-data warnings, so that I know when a fair-value estimate is extrapolated.
10. As a researcher, I want a theoretical option price and Greeks, so that I can understand directional, curvature, time, and volatility exposure.
11. As a researcher, I want market mid, bid, ask, theoretical price, and IV edge shown together, so that “cheap” and “expensive” are defined relative to a model rather than premium alone.
12. As a researcher, I want transaction costs, spread, and slippage included in the edge, so that a paper opportunity is not created by an untradeable quote.
13. As a researcher, I want to filter by days to expiry, delta, open interest, volume, spread, IV edge, and maximum loss, so that the scan matches my capital and holding period.
14. As a researcher, I want to define a directional scenario, such as rejection from resistance, so that the scanner evaluates options against a concrete thesis.
15. As a researcher, I want the scanner to support volatility-only scenarios, so that I can study buying or selling movement without relying only on direction.
16. As a researcher, I want to see P&L under multiple BTC/asset moves, IV changes, and elapsed days, so that I understand path and time risk before entering a paper trade.
17. As a researcher, I want to compare a single option with defined-risk spreads, so that I can choose an instrument appropriate for low capital.
18. As a researcher, I want maximum loss, maximum profit, breakeven, and position Greeks for each candidate, so that risk is visible before selection.
19. As a researcher, I want positive expected value to be based on historical out-of-sample tests after costs, so that a “win rate” label is not mistaken for an edge.
20. As a researcher, I want the system to return “no qualified opportunity” when evidence is insufficient, so that it does not force a trade.
21. As a researcher, I want every opportunity to explain which filters passed and failed, so that I can audit the decision.
22. As a researcher, I want scan results reproducible from a timestamped snapshot, so that I can compare later outcomes with the original thesis.
23. As a researcher, I want to export a scan and scenario report, so that I can maintain a paper-trading journal.
24. As a researcher, I want the UI to remain usable on a laptop and a narrow viewport, so that I can review candidates without hidden or clipped controls.
25. As a researcher, I want all outputs to state that they are research signals rather than execution instructions, so that the tool's scope is clear.

## Implementation Decisions

- Preserve the existing options, Bybit, indicators, portfolio, CLI, and MCP modules as the analytics foundation. Add a deeper valuation module rather than duplicating existing GEX/flow calculations.
- Establish one high-level valuation interface that accepts a normalized option contract, market snapshot, fitted volatility surface, and valuation configuration, then returns a valuation result. Keep data adapters and model implementations behind this seam.
- Establish one high-level scan interface that accepts an asset universe, normalized chains, scan filters, scenario configuration, and cost assumptions, then returns ranked candidates plus explicit rejection reasons.
- Normalize all option symbols and expiry values into typed contracts before analysis. Chronological expiry ordering must use parsed dates, never lexical string ordering.
- Treat exchange-provided IV and Greeks as observed market inputs. The system must label whether a result is observed, interpolated, or extrapolated.
- Build the MVP surface in two layers: an observed surface from valid market quotes and a fitted fair surface using a documented, deterministic interpolation method. Advanced SVI/SSVI calibration is deferred until the simple surface has tests and historical evidence.
- Make the pricing implementation replaceable. The initial adapter may reuse the existing Black–Scholes implementation for compatibility, but production valuation must not silently rely on a hardcoded IV or risk-free rate. The interface must accept carry/forward assumptions so a crypto-specific forward-based adapter can be added.
- Separate “market context” from “valuation.” GEX, flow, vanna, skew, and OHLC can supply context and scenario triggers, but they must not be treated as proof that an option is mispriced.
- Define “cheap/expensive” as model fair value versus executable market price after bid/ask, fees, and slippage. A low premium alone is not cheap.
- Define “positive EV” as a backtest result after costs with a held-out time period and documented assumptions. The system must not promise live profitability or emit a trade when the backtest sample is insufficient.
- Provide a read-only HTTP JSON interface for the web UI. Keep the existing MCP/CLI interfaces working while the web layer consumes the same application modules.
- Implement the HTTP layer with FastAPI/Uvicorn and the first UI with same-origin HTML, CSS, and JavaScript modules. Do not introduce a second frontend framework before the scanner contract is stable.
- Build the first UI as a focused scanner: asset selector, filters, scan action, ranked results table, candidate detail drawer/page, scenario chart/table, and data-quality/rejection explanations.
- Discover the public option universe through Bybit's paginated instrument catalog, keep only actively trading instruments, cache instrument metadata within a scan, and use a shared public HTTP client with bounded concurrency and retry/backoff.
- Expose one application-level multi-asset scan seam. HTTP and MCP/CLI adapters must call the same scanner rather than reimplementing per-asset orchestration.
- Use deterministic fixtures for unit and integration tests, with a small recorded Bybit-shaped payload. Live Bybit calls are smoke checks only and must not be required for the core test suite.
- Keep API keys out of the browser and never expose private Bybit endpoints through the scanner MVP.
- The system is research/paper-trading only. Order placement, account mutation, automated execution, and personalized investment advice are out of scope.

## Testing Decisions

- Test observable behavior at the highest seam possible: normalized market snapshot → valuation result and scan request → ranked scan response. Avoid tests that assert private helper structure.
- Add deterministic fixtures covering multiple assets, multiple expiries, calls and puts, missing fields, duplicate quotes, stale timestamps, wide spreads, and malformed symbols.
- Test expiry ordering with dates that fail lexical ordering, including `25JUN27` versus `25SEP26`.
- Test pricing invariants: non-negative value, intrinsic-value lower bounds, put/call type behavior, expiration behavior, and monotonic response to IV where applicable.
- Test surface behavior: no silent extrapolation, stable interpolation, explicit missing-data status, and fair-value output changing when neighboring quotes change.
- Test opportunity behavior: candidates must pass all configured liquidity and edge gates; rejected candidates must include actionable reasons; insufficient backtest evidence must produce no-qualified-opportunity.
- Test scenario behavior across underlying moves, IV moves, and elapsed days, including capped-risk spreads and zero/near-zero liquidity.
- Reuse the existing pytest suite and add module-level tests next to the new application seams. Add API integration tests using a fake market-data adapter.
- Add Playwright functional tests for: initial loading, asset selection, multi-asset scan, filters, empty state, error state, candidate detail, scenario changes, and export/report action if implemented.
- Add Playwright visual checks for desktop and narrow viewport states, including the densest results table and the candidate detail state. Verify no required control or result is clipped.
- Include at least two exploratory UI cases: a scan with no qualifying opportunities and a scan where one asset has malformed or unavailable data while other assets succeed.
- Full signoff requires unit tests, API/integration tests, type/lint checks, Playwright functional QA, separate Playwright visual QA, and a defect-first review of the final diff.

## Out of Scope

- Live order placement, account access, withdrawals, or exchange mutation.
- A guarantee of profitability or a claim that historical positive EV will persist.
- Portfolio optimization across user holdings in the first release.
- Automated delta hedging or continuous market making.
- Full stochastic-volatility or machine-learning pricing models before the baseline surface is validated.
- Calendar strategies based on the currently known expiry-sort bug until chronological normalization is shipped and tested.
- Real-time websocket streaming in the MVP; polling and timestamped snapshots are sufficient initially.
- Mobile-native applications.

## Further Notes

- The existing CLI currently reports heuristic labels such as `SELL_VOL` and `breakout_probability`. The new scanner must display their definitions and must not present them as statistical probabilities without validation.
- A positive-EV gate is a research quality gate, not a promise. If the data does not support an edge after costs, the correct output is no trade.
- The first implementation should prioritize BTC, ETH, and every additional asset returned by the Bybit public options catalog, rather than hardcoding a fixed list.
- The primary application seam is `MultiAssetOptionScanner.scan(request)` over an `OptionMarketDataProvider`; tests use a fake provider and do not depend on the network.
- The web UI should show the timestamp and source status prominently because option IV, liquidity, and Greeks can change quickly.
