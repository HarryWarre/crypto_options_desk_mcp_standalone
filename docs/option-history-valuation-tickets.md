# Option History–Aware Valuation — Local Follow-up Ticket Split

Status: local drafts only. These follow-ups are not published to a remote issue
tracker. Existing `OPS-*` and `STRAT-*` ticket IDs and content remain unchanged.

Parent context:

- `OPS-008` now provides prospective full-ticker snapshot capture/replay and a
  per-symbol Bybit mark-price-history adapter. It does not yet connect either
  path to live scanner valuation.
- The current scanner builds its fair-value input from the current option
  ticker snapshot and the current observed/interpolated volatility surface.
- The public client already has a historical-volatility endpoint seam, but the
  scanner does not request or carry that context.

## Dependency order

```text
OPS-001 + OPS-002 + OPS-003 + OPS-005 ──> HIST-001 ──> HIST-002
OPS-005 + OPS-008 ────────────────────────────────> HIST-003
```

`HIST-003` is intentionally not blocked by `HIST-001`: Bybit mark-price
history is a separate, lower-fidelity backtest input and must not become a
live-valuation dependency. `HIST-003` may reuse the metadata vocabulary from
`HIST-002` when both are available.

## HIST-001 — Add 30d historical-volatility context to valuation

Outcome: each selected asset can carry an optional 30-day Bybit historical
volatility context into a live scan, while the current option surface remains
the source of fair IV and fair price.

Blocking: `OPS-001`, `OPS-002`, `OPS-003`, and `OPS-005`.

Implementation notes:

- Use the existing Bybit public historical-volatility seam
  (`/v5/market/historical-volatility`) with `period=30`.
- Fetch once per selected base coin per valuation/cache window, not once per
  option contract or candidate. A cache freshness target of 30–60 minutes is
  appropriate for the first implementation and must be explicit/configurable.
- For a fixed `valuation_time`, only use a historical-volatility observation at
  or before that time. A live request may use the newest available observation
  and must retain its source timestamp.

Acceptance criteria:

- A typed, optional per-asset context records the 30d value, source endpoint,
  source timestamp, retrieval/cache timestamp, lookback/period, and freshness
  status.
- The context is an anchor/quality signal: it may support a comparison,
  warning, or surface-quality classification, but it does not replace the
  current surface IV and does not directly overwrite `fair_iv`, `fair_price`,
  or `iv_edge`.
- Current option ticker quotes and the current observed/interpolated surface
  remain the live pricing inputs. Changing or removing the historical-volatility
  value alone must not silently change the priced IV source.
- Missing, stale, malformed, or unavailable historical volatility produces an
  explicit quality issue/status and does not make the otherwise usable current
  surface fall back to mark-price history or an invented IV.
- A multi-asset scan isolates one asset's historical-volatility failure from
  other assets, following the existing partial-asset failure behavior.
- A live valuation does not call `/v5/market/mark-price-kline`; mark-price
  history is reserved for the later backtesting ticket.

Public test seam: selected assets + current normalized universe/surface →
valuation context and unchanged fair-value input source.

Checks:

- 30d request parameters and per-asset call de-duplication.
- Cache hit within the configured freshness window and refresh after expiry.
- Latest-at-or-before selection for a fixed valuation time.
- Missing/stale/invalid history leaves current-surface pricing usable while
  exposing a warning.
- A historical-volatility endpoint failure for one asset does not erase
  successful assets.
- A spy request proves live valuation never requests mark-price candles.

Out of scope: replacing the observed/interpolated surface, calibrating an
arbitrage-free surface, fetching mark-price history on every scan, or claiming
historical profitability.

## HIST-002 — Surface explicit valuation provenance and quality metadata

Outcome: programmatic and user-facing scan consumers can tell exactly which
data powered a valuation and whether the historical context is usable, stale,
missing, or only a quality signal.

Blocking: `HIST-001`, `OPS-003`, `OPS-005`, and `OPS-006`.

Acceptance criteria:

- The valuation/scan contract exposes a typed or equivalently structured
  metadata object containing, at minimum:
  - valuation time and current option quote/data timestamps;
  - current surface source and status (`observed`, `interpolated`, or
    `extrapolated` where applicable);
  - the pricing IV source, explicitly identifying current surface IV;
  - 30d historical-volatility value (when present), source timestamp, age/cache
    status, and role `anchor_quality_only`;
  - machine-readable quality status and issues/warnings.
- Metadata is present for successful valuations and for degraded valuations;
  missing history is represented explicitly rather than as a zero, default IV,
  or silent omission.
- API serialization is deterministic and backward-compatible: existing
  opportunity, rejection, evidence, execution, timestamp, and cost fields
  remain available and retain their meanings.
- The UI/API wording makes clear that 30d historical volatility is context for
  quality/anchoring, not a replacement for current surface IV. It also makes
  clear that mark-price history is not fetched for every live valuation.
- Historical context metadata cannot upgrade `evidence_status` or
  `expected_value_status` to validated positive EV; that still requires the
  separate held-out outcome/backtest gate.

Public test seam: valuation/scan result → serialized metadata and visible
quality state.

Checks:

- Snapshot fixture with fresh 30d history exposes source, age, period, and
  `anchor_quality_only` role.
- Missing, stale, invalid, and endpoint-error fixtures expose distinct,
  deterministic quality states without changing the current-surface IV source.
- Surface `observed`/`interpolated`/`extrapolated` status survives serialization.
- Existing API clients can still read all pre-existing result fields.
- API/browser fixtures show degraded-data explanations and preserve the
  unvalidated-evidence gate.

Out of scope: a UI redesign, new strategy ranking logic, changing fair-value
math, or a positive-EV claim from historical-volatility context alone.

## HIST-003 — Add later mark-price-history backtesting

Outcome: the project can replay bounded historical mark-price candles for
candidate option symbols as a clearly labeled backtest/scenario input without
pretending that those candles are executable historical quotes.

Blocking: `OPS-005` and `OPS-008`.

Non-blocking relationship: this ticket does not depend on `HIST-001` because
historical volatility and mark-price candles are separate data paths. Reuse
`HIST-002` metadata fields when available, but do not make the 30d historical-
volatility fetch a prerequisite for mark-price replay.

Acceptance criteria:

- The backtest accepts a bounded date range and option symbols and uses the
  existing `get_option_mark_price_history()` seam. A 30-day, 4-hour bar set is
  a suitable default for the first implementation, with the range and
  interval explicit in the report.
- Replay aligns bars to signal entry/exit times without look-ahead and records
  missing-bar, expiry, and symbol-availability issues.
- The report labels mark prices as a non-executable proxy and states that the
  source does not contain historical bid/ask, IV, Greeks, open interest, or
  volume. Any fill, spread, slippage, and cost assumptions are explicit rather
  than inferred from OHLC candles.
- Mark-price history is never fetched during ordinary live valuation/scanning;
  it is invoked only by the explicitly requested backtest/replay path.
- Mark-price replay alone cannot set `evidence_status` or
  `expected_value_status` to validated positive EV. A positive-EV conclusion
  requires the existing chronological train/holdout, cost, and outcome gates,
  with the mark-price proxy limitation visible in the report.
- Existing snapshot replay remains available for complete historical ticker
  inputs; the two historical sources are not merged into a fabricated full
  historical quote.

Public test seam: mark-price-history fixture + strategy signal timeline →
mark-based backtest report and evidence status.

Checks:

- Range/interval propagation, pagination, ordering, and duplicate-bar handling
  through the existing adapter.
- Signal timestamps exactly on, between, before, and after available bars.
- Expired option, missing candle, partial range, and API failure behavior.
- Conservative fill/cost assumptions are visible and affect results.
- A live-scan spy proves no mark-price-history request is made.
- Insufficient samples, non-positive held-out EV, and proxy-only data retain the
  unvalidated evidence state.

Out of scope: historical bid/ask reconstruction, historical IV/Greeks/OI/
volume reconstruction, live cache warming for every valuation, order execution,
or a guarantee of future profitability.

## Narrow contract and test-plan note

Keep the implementation seams separated:

```text
current ticker snapshot ──> current surface ──> fair-value pricing
                                      │
30d historical volatility ────────────┘
             (context / anchor / quality only)

mark-price candles ──> explicit replay/backtest only
```

The preferred deterministic tests inject the public request function or a fake
market-data adapter; they must not require Bybit credentials or live network
responses. The minimum cross-ticket regression should assert all of the
following in one controlled fixture:

1. current surface IV remains the reported pricing source;
2. fresh 30d historical volatility is present as context with source and age;
3. stale/missing historical volatility degrades quality explicitly but does
   not invent an IV or block otherwise valid current-surface pricing;
4. ordinary live valuation makes zero mark-price-history calls; and
5. evidence remains unvalidated until the existing outcome/held-out backtest
   gate passes.

Implementation workers should add tests at the highest existing seam and leave
the current dirty scanner changes outside this documentation write-set intact.
