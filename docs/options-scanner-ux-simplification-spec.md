# Options Scanner UX Simplification Specification

Status: local draft, awaiting publication. No issue-tracker guide, configured connection, canonical issue number, or `ready-for-agent` label is present in this repository.

Source context: the current read-only crypto options scanner, its existing normalized market-data and opportunity-scanner contracts, and the current conversation about reducing the amount of unexplained input required to run a scan.

## Problem Statement

The current Scan screen exposes the scanner's internal quantitative controls directly to every user. A first-time user must see and sometimes edit annual risk-free rate, exact DTE bounds, IV edge, delta bounds, spread percentage, open interest, volume, maximum loss, fees, edge after costs, slippage, quantity, contract multiplier, result limits, and eight strategy checkboxes before receiving a result.

These controls are valid for a research or quant workflow, but they are not a usable first step for someone who is asking a simple question such as “I expect BTC to rise; what defined-risk options are worth looking at?” Labels such as `IV edge`, `edge after costs`, `risk_free_rate`, and basis-point slippage do not explain their units or decision meaning. The user can submit a scan without understanding which assumptions determine the candidates.

The result table also foregrounds model terms before the user has a plain-language explanation of what the candidate is for, how much can be lost, or what market view it represents. The application therefore feels more complex than comparable options scanners, despite already having the underlying market-data, valuation, liquidity, rejection, and scenario capabilities.

## Solution

Introduce a progressive-disclosure Scan experience with a simple mode as the default and an Advanced filters section for experienced users.

In simple mode, the user chooses:

- Asset(s), using the existing Bybit asset discovery.
- Market view (`Tăng`, `Giảm`, or `Đi ngang`; API values `up`, `down`, and `sideways`).
- Holding horizon (`0–7 ngày`, `7–30 ngày`, or `30–90 ngày`; API values `0_7`, `7_30`, and `30_90`).
- Maximum acceptable loss in the account/display currency.
- Optional minimum IV edge, displayed as percentage points (for example, `3` means 3%).
- Optional strategy preference, defaulting to a recommendation derived from the market view.

The server translates those choices into the existing typed scan request. It supplies documented defaults for model and execution assumptions, applies a bounded-risk strategy preset, and continues to return the existing timestamped opportunities, rejections, asset failures, data-quality issues, evidence status, and execution status. The response also reports the normalized scan context and applied defaults so the UI can explain what was actually used.

The Advanced filters section is collapsed initially. It can expose exact DTE, delta, bid/ask spread, open interest, volume, edge after costs, fee, slippage, quantity, contract multiplier, risk-free rate, strategy selection, and result limit. Every advanced field must include a unit and a short explanation. Advanced values override the corresponding simple-mode defaults only when the user explicitly changes them; the simple IV-edge field remains available for users who want a single understandable quality threshold.

Results should lead with a readable thesis and bounded risk. For example: “Mua call BTC — phù hợp khi BTC tăng; lỗ tối đa 120 USDT; điểm có lợi từ khoảng 68,500.” Technical fields such as fair value, IV edge, model status, liquidity, Greeks, rejection reasons, and cost assumptions remain available in a details area and in the existing P&L view.

The primary public seams for this work are:

1. **POST scan API:** `POST /api/v1/opportunities/scan` is the canonical request/response seam. It must accept the simple request, preserve support for the current advanced request shape where practical, return structured validation errors, and return a response containing the normalized scan context. The existing streaming endpoint may remain as a transport adapter, but its resulting scan behavior must be equivalent to the canonical POST endpoint.
2. **Playwright browser flow:** a real browser submits the visible Scan form, observes the outgoing POST request, waits for the result state, opens a candidate's P&L detail, and verifies empty, validation, error, responsive, and Advanced-filter states. The flow must assert user-visible behavior and the important request payload, not private JavaScript functions or DOM implementation details.

## User Stories

1. As a new options user, I want to run a scan after choosing only an asset, market view, horizon, and maximum loss, so that I can get useful ideas without learning option-pricing terminology first.
2. As a Vietnamese-speaking user, I want the primary controls and explanations to use familiar labels such as `Kỳ vọng tăng`, `Kỳ vọng giảm`, `Đi ngang`, and `Lỗ tối đa`, so that the scanner is understandable at a glance.
3. As a user who expects the underlying to rise, I want the scanner to suggest bounded-risk bullish strategies, so that I do not need to understand internal strategy identifiers.
4. As a user who expects the underlying to fall, I want the scanner to suggest bounded-risk bearish strategies, so that I can express my thesis without selecting several legs manually.
5. As a user who expects the underlying to move sideways, I want the scanner to suggest bounded-risk range or volatility strategies, so that “sideways” is a meaningful scan choice rather than an empty label.
6. As a cautious user, I want maximum loss to be a prominent simple-mode input, so that the scanner respects my risk budget before ranking candidates.
7. As a user, I want a short holding-horizon choice instead of exact DTE fields by default, so that I can communicate timing without guessing precise expiry boundaries.
8. As a user, I want to select one or more assets from the live Bybit catalog, so that the scan remains aligned with the contracts currently available.
9. As a user, I want the default asset selection to be visible and explicit, so that I know which instruments are being scanned.
10. As a user, I want the simple scan to have sensible model, liquidity, and cost defaults, so that I am not forced to invent a risk-free rate, slippage assumption, or contract multiplier.
11. As a user, I want to see what defaults were applied after I scan, so that the result is transparent even when I did not edit advanced filters.
12. As a user, I want technical filters to remain available under `Bộ lọc nâng cao`, so that the simple experience does not remove research capability.
13. As an experienced researcher, I want Advanced filters to override simple-mode defaults only when I edit them, so that my explicit assumptions are respected without making every user configure them.
14. As an experienced researcher, I want exact DTE, delta, IV edge, spread, OI, volume, and edge-after-costs controls, so that I can reproduce a stricter scan.
15. As an experienced researcher, I want fees, slippage, quantity, and contract multiplier to remain configurable, so that the cost-adjusted edge reflects my execution assumptions.
16. As an experienced researcher, I want to choose individual supported strategy families in Advanced mode, so that I can reproduce the existing long-option, vertical, iron condor, and iron butterfly workflows.
17. As a user, I want an explanation beside each technical Advanced field, so that I can understand what changing it does and what unit to enter.
18. As a user, I want the form to prevent invalid values and explain the error in plain language, so that I can correct a scan without inspecting an API response.
19. As a user, I want the scan button to show progress and prevent duplicate submissions while a scan is running, so that I know whether the request is still working.
20. As a user, I want the results to explain the market thesis first, so that I understand why an opportunity may fit my selected view.
21. As a user, I want each result to show maximum loss prominently, so that risk is visible before I inspect fair value or Greeks.
22. As a user, I want each result to show the relevant expiry, entry price, and approximate benefit or breakeven in readable terms, so that I can compare candidates without decoding raw fields.
23. As a user, I want to know whether a candidate is a call, put, spread, condor, or butterfly and which legs are bought or sold, so that multi-leg results are not misleading.
24. As a user, I want technical valuation details to be available on demand, so that I can learn more without making the first results screen dense.
25. As a user, I want an explicit explanation that `IV edge` is a model-versus-market comparison and not a probability of profit, so that I do not misread a model output.
26. As a user, I want an explicit explanation that `edge after costs` is a model price difference after fees and slippage and not guaranteed profit, so that I do not treat the scanner as an execution recommendation.
27. As a user, I want liquidity warnings for wide spreads, low volume, or low open interest, so that an apparently attractive result is not presented as easy to trade.
28. As a user, I want a useful empty state when no candidate meets the chosen conditions, so that I know the scan completed and which controls I could relax.
29. As a user, I want partial asset failures to be visible while successful assets still render, so that one unavailable market does not hide all results.
30. As a user, I want API and market-data errors translated into an actionable message, so that I know whether to retry or adjust filters.
31. As a user, I want to open the existing P&L/scenario detail from a result, so that I can inspect price, IV, time, Greeks, breakevens, and bounded-risk metrics before making a paper-trading decision.
32. As a user, I want the P&L detail to repeat the scan assumptions that produced the candidate, so that the scenario is not detached from the original search.
33. As a user, I want the simple form and result cards to fit on a laptop and narrow viewport, so that required controls are not clipped or hidden.
34. As a keyboard or assistive-technology user, I want the form, Advanced disclosure, validation messages, progress log, results, and P&L controls to have usable labels and focus order, so that the scanner is operable without a mouse.
35. As a returning user, I want changing the market view, horizon, or maximum loss to produce a new scan rather than silently reuse stale results, so that the displayed candidates match my current intent.
36. As a researcher, I want the canonical POST scan contract to remain deterministic for a fixed market snapshot and request, so that I can test and compare UI behavior reliably.
37. As an API consumer, I want existing advanced request fields and response fields to remain compatible where they are not explicitly superseded, so that the CLI, MCP, and existing clients do not break during the UX change.
38. As a product owner, I want the UI to remain read-only and to state that results are research signals, so that simplification does not imply order placement or personalized investment advice.

## Implementation Decisions

- Keep the existing normalized Bybit option universe, volatility surface, fair-value pricing, opportunity scanner, rejection model, and scenario evaluator as the domain foundation.
- Add a user-facing simple scan request model at the HTTP application boundary. It maps `market_view`, `time_horizon`, `max_loss`, optional `min_iv_edge`, selected assets, and an optional strategy preference to the existing internal `ScanRequest` rather than duplicating scan logic.
- Use explicit API enums: `market_view` is `up`, `down`, or `sideways`; `time_horizon` is `0_7`, `7_30`, or `30_90`. The browser may display Vietnamese labels while submitting stable English values.
- Require a simple request to include at least one asset, one market view, one horizon, and a non-negative maximum-loss value. If product copy supports “no limit,” represent that explicitly as null rather than silently sending a very large number.
- Map default strategy presets as follows: `up` prioritizes long call and bullish defined-risk call structures; `down` prioritizes long put and bearish defined-risk put structures; `sideways` prioritizes defined-risk iron condor and iron butterfly structures. If a selected preset has no valid candidate, the result must explain that outcome instead of silently switching to an unrelated strategy.
- Keep strategy identifiers and all quantitative filter fields in the API/domain vocabulary, but do not require them in the default browser form.
- Define server-side defaults for risk-free rate, fee, slippage, quantity, contract multiplier, liquidity thresholds, minimum model edge, and result count in one documented application configuration. The exact defaults must be deterministic in tests and visible through normalized scan context.
- Make simple-mode defaults conservative and bounded-risk. Do not introduce naked short strategies, order placement, account mutation, or execution permissions as part of this change.
- Extend the scan response with a backward-compatible `scan_context` or equivalent metadata object containing the simple choices, resolved strategies, applied filter values, model/cost assumption summary, and a human-readable summary. Existing opportunity, rejection, issue, timestamp, evidence, and execution fields remain available.
- Preserve structured validation errors from the POST endpoint. Errors must identify the invalid public field and use language the UI can map to an inline message.
- Treat `POST /api/v1/opportunities/scan` as the canonical public API seam. The existing NDJSON progress endpoint may call the same application-level scan operation, but it must not develop a separate translation or ranking path.
- Keep the API read-only and source-backed. API keys must not reach the browser.
- Rework the Scan form into a small primary field group and a collapsed Advanced disclosure. Advanced controls should be rendered in a stable, accessible region so browser tests can open it by its label rather than by CSS internals.
- Default the strategy control to a human-readable recommendation. If a manual strategy selector remains in simple mode, it must be a small set of understandable presets rather than a list of internal identifiers.
- Use plain-language result summaries and compact risk-first cards/table columns. Keep fair value, IV edge, edge after costs, Greeks, OI, volume, spread, and model status in a details area or existing P&L detail.
- Explain technical units at the field or detail level: IV values and edges are decimal percentages displayed as percentages; spread is a percentage; fees are currency per contract; slippage is basis points; edge after costs is currency; risk-free rate is an annual decimal rate.
- Keep the existing P&L/scenario flow as the detailed inspection path. It should receive the normalized opportunity data and the resolved execution assumptions without requiring the user to re-enter them.
- Keep terminal/progress output available for transparency, but do not make debugging-style log text the main explanation of a scan. The primary state should be loading, success, empty, partial failure, or error in user-facing language.
- Preserve the current secure DOM rendering approach and same-origin static UI. User-controlled or API-controlled strings must continue to be inserted as text, not executable HTML.
- Treat the UI as Vietnamese-facing where it improves comprehension, while keeping API names, code identifiers, and durable documentation in English.
- Do not add a feature flag unless implementation uncovers a deployment need. This is a local read-only UI/API change with backward-compatible request handling.

## Testing Decisions

- Test observable behavior at the two agreed public seams only: the canonical POST scan API and the Playwright browser flow. Do not test private helper functions, CSS selectors as an implementation contract, or internal request translation by reaching into object state.
- API tests should submit a minimal simple request and assert the scanner receives the resolved behavior through the response: selected assets, strategy preset, DTE range, maximum loss, deterministic defaults, and scan context. Use an injected fake market-data adapter/scanner or deterministic fixtures at the existing application boundary.
- API tests should verify advanced overrides, backward-compatible advanced payloads, invalid enum/value errors, missing required simple inputs, `max_loss: null` if supported, unsupported strategies, and preservation of existing response metadata.
- API tests should verify that a simple request never enables an unbounded short strategy and that the simple mode's strategy mapping is deterministic.
- API tests should continue to cover structured upstream errors, empty opportunities, partial asset failures, and the existing non-API scenario contract where the UX change could affect serialization.
- Use existing pytest and HTTPX/ASGI API-test patterns in the repository. The tests should use known-good literal fixtures and independently reasoned expected values, not recompute the implementation's mapping algorithm in the assertion.
- Playwright tests should mock the public assets and scan API at the network boundary, then exercise the visible browser flow. A test should select an asset, choose a market view and horizon, enter maximum loss, submit, and assert the outgoing POST payload and rendered plain-language result.
- Playwright should verify that advanced fields are not required or visible in the default state, that opening `Bộ lọc nâng cao` reveals them, and that an edited advanced value appears in the request and the displayed applied-assumptions summary.
- Playwright should cover upward, downward, and sideways presets, at least one multi-leg result, a candidate P&L detail, no-result state, invalid input state, API error state, partial asset failure, loading/duplicate-submit protection, and narrow viewport fit.
- Playwright assertions should prefer roles, accessible names, labels, and user-visible text. Request assertions may inspect the public JSON payload, but tests should not depend on function names, element order, generated class names, or private state variables.
- Visual/interaction QA must confirm that primary controls are understandable without opening Advanced filters, the Advanced area is visually subordinate but discoverable, result risk is prominent, technical details are available on demand, and no required content overflows a 390px-wide viewport.
- The existing scanner, API, and browser tests are prior art. New tests should extend their current deterministic fixtures and preserve the current P&L/scenario regression coverage.

## Out of Scope

- Replacing the pricing model, volatility-surface methodology, opportunity ranking, or scenario evaluator.
- Adding live order placement, broker/exchange mutation, account access, authentication, or personalized investment advice.
- Claiming that a model edge is a probability of profit or a guaranteed return.
- Building a new mobile-native application or introducing a frontend framework.
- Removing the existing quantitative capabilities from the backend, CLI, MCP, or Advanced UI.
- Adding a new historical positive-EV/backtesting system.
- Adding streaming market data or websocket behavior; the current timestamped scan model is sufficient.
- Redesigning the full P&L chart beyond the assumptions and navigation needed to preserve the scan-to-detail flow.
- Persisting user profiles, saved scans, sharing, exports, or a trading journal.
- Changing supported strategy families beyond the preset mapping needed to express up, down, and sideways views.
- Publishing issues remotely. The accompanying ticket document is a local draft because no issue-tracker guide or connection is present.

## Further Notes

- The current implementation already has useful explanation helpers and a scenario detail view; the simplification should build on those behaviors rather than replace them with raw model output.
- The current form includes fields whose values are easy to misread: an API IV edge of `0.03` represents three percentage points, a spread value of `0.2` represents twenty percent, and edge-after-costs is a currency amount. The simple UI accepts IV edge as `3` and displays the meaning directly; Advanced retains the normalized API units.
- The current API requires `risk_free_rate` even though most users cannot provide a meaningful value. Simple mode should make this a server-side documented assumption while Advanced mode may expose it for researchers.
- The canonical POST seam is intentionally separate from the browser's progress transport. This keeps the product contract testable and lets the existing streaming experience remain compatible while the UI becomes simpler.
- The ticket draft is ordered so API contract/defaults land before the browser form depends on them, followed by result explanations and cross-flow Playwright verification.
