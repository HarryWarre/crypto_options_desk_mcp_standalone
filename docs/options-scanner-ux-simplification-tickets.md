# Options Scanner UX Simplification — Local Ticket Drafts

Status: local drafts awaiting publication. No issue-tracker guide, configured connection, canonical issue numbers, or `ready-for-agent` label is present in this repository.

Source spec: [options-scanner-ux-simplification-spec.md](options-scanner-ux-simplification-spec.md)

These provisional ticket identifiers are for local dependency tracking only. They are not published issue numbers.

## Dependency order

```text
SCAN-UX-001 → SCAN-UX-002 → SCAN-UX-003 → SCAN-UX-004
```

The agreed public test seams for the whole change are:

- **POST scan API:** `POST /api/v1/opportunities/scan`, using deterministic fixtures and an injected/fake market-data boundary.
- **Playwright browser flow:** the visible Scan form through result, empty/error states, and P&L detail, with network assertions at the public API boundary.

## SCAN-UX-001 — Add a simple scan request mode and resolved scan context

**Outcome:** A user can submit a minimal, understandable scan request to the canonical POST scan API, and the server deterministically resolves it into the existing bounded-risk scanner behavior without requiring quant-only fields.

**Source spec:** [Options Scanner UX Simplification Specification](options-scanner-ux-simplification-spec.md), especially “Solution,” “Implementation Decisions,” and the POST scan API seam.

**Blocking:** None.

**Acceptance criteria:**

- `POST /api/v1/opportunities/scan` accepts a simple payload containing selected assets, `market_view`, `time_horizon`, and `max_loss`, plus an optional human-facing strategy preference if the implementation exposes one.
- `market_view` accepts exactly the documented `up`, `down`, and `sideways` values; `time_horizon` accepts exactly `0_7`, `7_30`, and `30_90`.
- The server translates `up`, `down`, and `sideways` into deterministic bounded-risk strategy presets. No simple request can produce a naked short or execution-enabled strategy.
- Each time-horizon value resolves to documented DTE bounds, and `max_loss` reaches the existing risk filter without unit conversion ambiguity.
- Model and execution defaults are supplied server-side for risk-free rate, liquidity, fees, slippage, quantity, contract multiplier, minimum edge, and result count. Their values are deterministic in tests and are not required in a simple request.
- The response preserves existing scan result fields and adds a backward-compatible scan context containing the user's choices, resolved strategy identifiers, applied filters/defaults, and a readable summary.
- Advanced request fields remain accepted where they are currently supported; explicitly provided advanced values override corresponding defaults.
- Missing fields, invalid enum values, invalid numeric ranges, and unsupported overrides return structured validation errors identifying the public field.
- The current streaming scan endpoint, if retained, delegates to the same simple-request translation and produces equivalent scan behavior.

**Public test seam:** Submit JSON to the POST scan API and assert the serialized response and normalized scan context. Use deterministic fake data; do not inspect private translation helpers.

**Checks expected at the seam:**

- Minimal up, down, and sideways payloads resolve to the expected strategy sets and DTE ranges.
- Maximum-loss boundary values and explicit no-limit behavior, if supported, are represented correctly.
- Advanced override payloads change only the intended resolved fields.
- Invalid simple and advanced payloads return structured 422 responses.
- Existing opportunity, rejection, issue, timestamp, evidence, and execution metadata remains serializable.

**Out of scope:** Browser layout, copywriting beyond API-readable summaries, new pricing/surface logic, new strategy families, historical EV validation, and remote issue publication.

## SCAN-UX-002 — Replace the first-run form with progressive disclosure

**Outcome:** A user can run the scanner from a small primary form while researchers retain access to the full quantitative filter set under an Advanced disclosure.

**Source spec:** [Options Scanner UX Simplification Specification](options-scanner-ux-simplification-spec.md), especially “Solution,” user stories 1–19 and 33–35, and the UI implementation decisions.

**Blocking:** SCAN-UX-001.

**Acceptance criteria:**

- The default Scan view presents asset selection, market view, holding horizon, maximum loss, and a simple strategy preference/recommendation without requiring risk-free rate, exact DTE, delta, IV edge, spread, OI, volume, fee, slippage, quantity, multiplier, or result-limit inputs.
- Primary labels are understandable to a Vietnamese-facing user, including `Kỳ vọng tăng`, `Kỳ vọng giảm`, `Đi ngang`, `Thời hạn`, and `Lỗ tối đa`, with concise help text where a unit or assumption matters.
- The form submits the simple API payload defined by SCAN-UX-001 and does not send blank or invented advanced values as if the user entered them.
- `Bộ lọc nâng cao` is collapsed initially and is operable by keyboard and assistive technology. Opening it reveals the existing advanced controls with explicit units and explanations.
- Editing an Advanced field makes it appear in the outgoing request and in the applied-assumptions summary; untouched Advanced fields remain server defaults.
- At least one asset is required, maximum loss cannot be negative, and invalid user input produces inline or adjacent actionable feedback without a network request.
- Submitting disables or guards the scan action until completion and preserves the existing progress/status behavior in user-facing language.
- The existing result and P&L regions remain reachable from the new form, and the UI remains usable at desktop and 390px-wide viewports without horizontal body overflow.

**Public test seam:** Playwright browser flow from page load through form submission, with an intercepted public POST request and observable loading/validation states.

**UI QA cases:**

- Load the page with assets available: only the simple controls are prominent and the Advanced section is closed.
- Choose BTC, `Kỳ vọng tăng`, `7–30 ngày`, and a maximum loss; submit and verify the request payload contains those choices.
- Repeat for `Kỳ vọng giảm` and `Đi ngang` to verify the visible labels map to stable API values.
- Open Advanced, change exact DTE and maximum spread, submit, and verify those values are sent.
- Enter a negative maximum loss or submit with no asset and verify a readable validation message without a scan request.
- Submit twice quickly and verify only one active scan is started.
- Set a 390px viewport and verify no required control is clipped or causes body overflow.

**Out of scope:** Reworking result columns or P&L copy, changing server ranking behavior, adding saved preferences, and removing Advanced capability.

## SCAN-UX-003 — Present scan results in plain language with technical details on demand

**Outcome:** After a scan, the user can understand the thesis, risk, and reason for a candidate before opening technical valuation details or P&L scenarios.

**Source spec:** [Options Scanner UX Simplification Specification](options-scanner-ux-simplification-spec.md), especially user stories 20–32 and the result presentation decisions.

**Blocking:** SCAN-UX-002.

**Acceptance criteria:**

- Result state distinguishes loading, success, empty, partial asset failure, and API error in readable user-facing language.
- Each opportunity leads with asset, strategy in plain language, market-view takeaway, expiry/horizon, entry or market price, and maximum loss.
- Multi-leg results identify bought and sold legs clearly, without exposing only internal strategy identifiers.
- Technical values including fair price, IV edge, edge after costs, Greeks, liquidity, surface/model status, evidence status, and cost assumptions remain available in a details area or existing P&L view.
- Technical copy explains that IV edge is a model-versus-market comparison and that edge after costs is a currency model difference after fees/slippage, not probability of profit or guaranteed profit.
- Applied scan context from SCAN-UX-001 is visible or discoverable after results render, including the selected view, horizon, maximum loss, resolved strategy preset, and important defaults.
- Empty results explain that no opportunity met the current conditions and point the user toward changing a simple control or Advanced filter; the UI does not imply that a trade should be forced.
- Partial asset failures remain visible while successful opportunities render.
- The existing `Xem P&L`/P&L detail flow remains available and receives the selected opportunity without requiring the user to manually re-enter scan assumptions.
- Results retain the read-only research-signal disclaimer and never add an order-placement action.

**Public test seam:** Playwright browser flow using mocked POST scan and scenario responses, asserting accessible result text, risk-first rendering, applied assumptions, empty/error states, multi-leg explanation, and P&L navigation.

**UI QA cases:**

- Render one long-call result and verify the first explanation is understandable without reading IV or Greeks.
- Render a vertical and a four-leg result and verify each leg's action, type, strike, and bounded risk are readable.
- Render a result with technical values and verify details are available without crowding the primary result.
- Render no opportunities and verify the empty-state guidance.
- Render one successful asset and one failed asset and verify both the result and failure message are visible.
- Open P&L detail and verify the scenario chart/table and assumptions still render.

**Out of scope:** Changing candidate ranking, recalibrating the volatility surface, redesigning the scenario engine, adding historical profitability claims, and redesigning the full application shell.

## SCAN-UX-004 — Add end-to-end Playwright coverage and release verification

**Outcome:** The simplified scanner is protected by a stable browser contract covering the main user journey and failure states at the agreed public seams.

**Source spec:** [Options Scanner UX Simplification Specification](options-scanner-ux-simplification-spec.md), “Testing Decisions.”

**Blocking:** SCAN-UX-003.

**Acceptance criteria:**

- Playwright covers page load, asset discovery, simple up/down/sideways scans, outgoing POST payload, applied assumptions, result explanation, and P&L detail.
- Playwright covers Advanced disclosure and override behavior without asserting private JavaScript implementation details.
- Playwright covers client validation, API validation/error, empty results, partial asset failure, progress/duplicate-submit protection, and a 390px-wide viewport.
- Network mocks use the public assets, POST scan, and scenario contracts, and at least one test asserts the browser sends the canonical simple request shape.
- Tests use accessible roles, labels, and user-visible copy wherever possible. CSS classes and DOM ordering are not treated as the product contract.
- The Python API test suite continues to pass, and the Playwright suite passes against the same static application entrypoint used by the app.
- The final verification records the commands and test counts in the implementation handoff or ticket comment once a tracker is available.

**Public test seam:** Playwright browser flow plus the POST scan API contract; no private helper seam is introduced.

**UI QA cases:**

- Fresh page load with a mocked asset catalog.
- One successful simple scan per market-view preset.
- Advanced override round trip.
- No-result, API-error, and partial-failure states.
- Candidate detail/P&L flow for single-leg and multi-leg data.
- Keyboard access to the Advanced disclosure and primary scan action.
- Desktop and narrow viewport overflow check.

**Out of scope:** Performance benchmarking under live Bybit load, visual pixel-perfect baselines for unrelated screens, real-money exchange calls, and remote issue publication.

## Recommended implementation order

1. Implement SCAN-UX-001 and make the POST API contract/defaults deterministic.
2. Implement SCAN-UX-002 against that contract; keep the existing advanced capability available.
3. Implement SCAN-UX-003 so results explain the resolved request rather than exposing raw model output.
4. Implement SCAN-UX-004, run the API suite and Playwright suite, and record the final verification.

Publication note: create these as small implementation issues in the configured tracker when a tracker guide and connection become available, apply the repository's `ready-for-agent` triage label, and replace the provisional identifiers with canonical issue URLs/numbers in this document and the source spec.
