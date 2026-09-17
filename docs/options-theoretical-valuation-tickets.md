# Theoretical Option Valuation — Local Implementation Tickets

Status: implemented in this branch. No issue-tracker guide, remote connection, canonical
issue number, or `ready-for-agent` label is available in this repository.
The identifiers below are provisional local issue IDs.

Source spec: [options-theoretical-valuation-spec.md](options-theoretical-valuation-spec.md)

## Dependency order

```text
OPS-013 → OPS-012 → OPS-014 → OPS-015
```

`OPS-013` fixes the historical context boundary independently. `OPS-012`
implements theoretical valuation and the public scan contract. `OPS-014`
adds the browser opt-in and user-facing quality explanation after the API
contract is stable.

## OPS-013 — Make historical-volatility timestamps resilient

**Outcome:** A live or replay scan does not fail when the existing repository
clock supplies a naive UTC datetime.

**Source spec:** The timestamp normalization solution and user stories 11–13.

**Blocking:** None.

**Acceptance criteria:**

- Naive datetimes from the existing UTC clock are interpreted as UTC and
  normalized consistently with aware UTC inputs.
- Historical-volatility context creation, cache freshness, latest-at-or-before
  selection, and API serialization continue to work for both timestamp forms.
- A historical context fetch failure remains an explicit per-asset degraded
  status and does not escape the scan stream as an unhandled `ValueError`.
- Existing aware-datetime behavior remains unchanged.

**Public test seam:** Historical-volatility context loader and scan stream/API
with deterministic fake fetchers.

**Checks:** Regression for the reported naive-clock traceback; aware/naive
equivalence; stale and fetch-error contexts; full stream completion.

**Out of scope:** A repository-wide datetime convention migration and changes
to Bybit history endpoint semantics.

## OPS-012 — Add explicit theoretical valuation mode

**Outcome:** Researchers can request fair values for valid Bybit option model
inputs even when bid/ask is missing, while executable opportunities remain
conservative and clearly separate.

**Source spec:** The valuation-mode solution and user stories 1–10 and 14–15.

**Blocking:** OPS-013 for the shared scan integration path.

**Acceptance criteria:**

- `executable` remains the default mode and preserves current positive bid/ask
  validation and edge semantics.
- `theoretical` is accepted only as an explicit mode and permits missing or
  non-positive bid/ask when all required model inputs remain valid.
- Theoretical output exposes fair value, fair IV, Greeks, reference mark data,
  model/surface status, expiry payoff, and model-estimated EV, probability,
  risk/reward, and payoff bounds where the strategy has a single expiry.
- Theoretical output is explicitly non-executable and cannot expose a fake
  executable entry, edge-after-costs, slippage-adjusted edge, or tradable
  maximum-loss claim.
- Theoretical mode reports `max_spread_pct`, `min_edge_after_costs`,
  `max_loss`, and `min_expected_value` as ignored filters and does not
  require a max-loss input in the simple scan form.
- Existing response fields remain backward-compatible for executable scans.
- The live scan does not call mark-price history in either mode.
- One asset's missing/invalid quotes do not remove another asset's results.

**Public test seam:** Canonical POST scan API with deterministic normalized
universe fixtures and an injected market-data boundary.

**Checks:** Default compatibility; missing bid; missing ask; zero bid/ask;
valid mark IV; invalid mark IV; mixed assets; no mark-price-history call;
unchanged executable result with complete quotes.

**UI QA:** API payload contains the selected mode; result labels model-only
values; executable results retain the current presentation; empty and partial
asset states remain understandable.

**Out of scope:** Historical quote reconstruction, mark-price candle replay,
order placement, and changes to fair-value math.

## OPS-014 — Add theoretical-mode control and quality explanation

**Outcome:** A user can opt into theoretical valuation from the default scan
form and understand that missing bid/ask means the result is for model
reference only.

**Source spec:** The browser decisions and user stories 2, 4, 5, 8, 14, and
16.

**Blocking:** OPS-012.

**Acceptance criteria:**

- The default form contains an opt-in theoretical valuation control that is
  off by default and has clear Vietnamese explanatory text.
- The control changes only the public valuation mode and does not silently
  relax other filters or enable order execution.
- Results visibly distinguish executable opportunities from theoretical
  valuations, including a non-executable warning when bid/ask is unavailable.
- The existing historical-volatility quality context remains visible without
  causing a scan failure.
- Desktop and 390px-wide Playwright flows have no clipped required control or
  misleading result state.

**Public test seam:** Playwright browser flow through asset selection, mode
selection, scan submission, and result rendering with mocked API responses.

**Checks:** Default-off state; opt-in payload; theoretical warning; executable
backward compatibility; empty state; partial asset state; keyboard access;
responsive viewport.

**Out of scope:** A new frontend framework, redesign of P&L scenarios, and
remote issue publication.

## OPS-015 — Add synthetic bid/ask fallback

**Outcome:** Researchers can calculate quote-dependent scan metrics for thin
markets using a visible, configurable spread assumption without treating the
result as executable.

**Acceptance criteria:**

- `synthetic` is accepted as an explicit valuation mode while `executable`
  remains the default and `theoretical` keeps fair-value-only semantics.
- `assumed_spread_bps` defaults to 100 bps and is shown in the scan context.
- Synthetic mode uses mark price as midpoint, falls back to fair value, and
  calculates estimated entry, edge, payoff, EV, probability, RR, and payoff
  bounds with the existing formulas.
- Synthetic output exposes `quote_source`, keeps `execution_allowed` false,
  and remains visibly labeled as estimated in the browser.
- Synthetic quote-dependent filters are applied to the estimated values and
  do not alter executable-mode behavior.

**Checks:** Scanner regression with missing bid/ask; API round trip for mode
and spread; browser payload/result labeling; full Python and Playwright suites.

## Recommended implementation order

1. OPS-013 — timestamp boundary regression.
2. OPS-012 — domain/adapter/API theoretical mode.
3. OPS-014 — browser control and UI QA.
4. OPS-015 — synthetic quote fallback and metric parity.
5. Full review, test suite, commit, and merge.
