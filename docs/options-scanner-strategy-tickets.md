# Options Scanner — Strategy Ticket Backlog

Status: local tickets. The repository has no configured issue-tracker CLI or connection, so these are ready-to-publish drafts.

Scope: extend the read-only opportunity scanner. Every strategy must use normalized market data, executable bid/ask prices, fees/slippage, explicit rejection reasons, bounded risk where applicable, and `execution_allowed=false`. A strategy is not considered validated positive EV unless it passes the existing evidence gate.

Overlay note: `protective_put` and `covered_call` require an existing spot/perpetual holding. The scanner prices the option overlay and marks that requirement; it does not invent the underlying entry price or full combined-position P&L.

## Strategy inventory

| Ticket | Strategy | Current state | Initial owner |
| --- | --- | --- | --- |
| STRAT-001 | Long call | Implemented; regression coverage | Core scanner |
| STRAT-002 | Long put | Implemented; regression coverage | Core scanner |
| STRAT-003 | Bull call vertical | Implemented; integrated | Jason — domain; Averroes — API; Euler — UI |
| STRAT-004 | Bear call vertical | Implemented; integrated | Jason — domain; Averroes — API; Euler — UI |
| STRAT-005 | Bull put vertical | Implemented; integrated | Jason — domain; Averroes — API; Euler — UI |
| STRAT-006 | Bear put vertical | Implemented; integrated | Jason — domain; Averroes — API; Euler — UI |
| STRAT-007 | Long straddle | Implemented; integrated | Core structured scanner |
| STRAT-008 | Long strangle | Implemented; integrated | Core structured scanner |
| STRAT-009 | Iron condor | Implemented; integrated | Core multi-leg scanner |
| STRAT-010 | Covered call | Implemented as underlying-position overlay | Core overlay scanner |
| STRAT-011 | Iron butterfly | Implemented; integrated | Core multi-leg scanner |
| STRAT-012 | Protective put | Implemented as underlying-position overlay | Core overlay scanner |
| STRAT-013 | Calendar spread | Implemented; integrated | Core structured scanner |
| STRAT-014 | Long/broken-wing butterfly | Implemented; integrated | Core structured scanner |

The four vertical tickets share one implementation seam and may ship together, but remain separate tickets so each direction has its own acceptance and test coverage.

### Corrected core-10 taxonomy

The previous table counted the four vertical directions as four separate strategies, which is why butterfly was missing. The intended core ten strategy families are:

1. Long call — STRAT-001
2. Long put — STRAT-002
3. Vertical spread — STRAT-003…STRAT-006 (four directional variants)
4. Long straddle — STRAT-007
5. Long strangle — STRAT-008
6. Iron condor — STRAT-009
7. Covered call — STRAT-010
8. Iron butterfly — STRAT-011
9. Protective put — STRAT-012
10. Calendar spread — STRAT-013

`StrategyType` also contains ratio spreads and synthetic positions. They remain explicitly outside this core ten until their risk/underlying-position contracts are defined. Plain long/broken-wing butterfly is tracked separately as STRAT-014; the current enum exposes `iron_butterfly`, not a generic `butterfly`.

## STRAT-001 — Keep long call scanner strategy stable

Outcome: existing long-call scans remain backward compatible while the scanner gains multi-leg candidates.

Acceptance criteria:

- Existing request, response, ranking, rejection, and UI behavior remains unchanged.
- Single-call opportunities retain their current cost, edge, max-loss, and evidence semantics.
- Regression tests prove single-leg candidates are not accidentally paired with another contract.

Blocking: none.

## STRAT-002 — Keep long put scanner strategy stable

Outcome: existing long-put scans remain backward compatible while the scanner gains multi-leg candidates.

Acceptance criteria:

- Existing request, response, ranking, rejection, and UI behavior remains unchanged.
- Single-put opportunities retain their current cost, edge, max-loss, and evidence semantics.
- Regression tests prove put candidates are not treated as call verticals.

Blocking: none.

## STRAT-003 — Add bull call vertical

Outcome: the scanner finds a long lower-strike call plus short higher-strike call with one expiry and returns defined-risk metrics.

Acceptance criteria:

- Request validation accepts `bull_call_vertical`.
- Pairing requires same asset, expiry, and call type, with long strike below short strike.
- Entry uses long ask minus short bid; exit/fair value uses the corresponding executable/model leg values.
- Response includes both legs, width, net debit, max loss, max profit, breakeven, aggregate Greeks, and cost-adjusted edge.
- Missing pairs, invalid quotes, and selected-strategy mismatches produce auditable rejections.

Blocking: OPS-005; shared vertical implementation.

## STRAT-004 — Add bear call vertical

Outcome: the scanner finds a short lower-strike call plus long higher-strike call and reports the bounded-risk credit structure.

Acceptance criteria:

- Request validation accepts `bear_call_vertical`.
- Pairing requires same asset, expiry, and call type, with short strike below long strike.
- Net credit, max profit, max loss, breakeven, costs, and edge are calculated from the correct bid/ask sides.
- The scanner never emits a naked short call when the long protective leg is absent.
- API/UI show both legs and the direction label.

Blocking: OPS-005; shared vertical implementation.

## STRAT-005 — Add bull put vertical

Outcome: the scanner finds a short higher-strike put plus long lower-strike put and reports the bounded-risk credit structure.

Acceptance criteria:

- Request validation accepts `bull_put_vertical`.
- Pairing requires same asset, expiry, and put type, with short strike above long strike.
- Net credit, max profit, max loss, breakeven, costs, and edge use executable prices.
- The short put is never emitted without its lower protective long put.
- API/UI show both legs and the direction label.

Blocking: OPS-005; shared vertical implementation.

## STRAT-006 — Add bear put vertical

Outcome: the scanner finds a long higher-strike put plus short lower-strike put with one expiry and returns defined-risk metrics.

Acceptance criteria:

- Request validation accepts `bear_put_vertical`.
- Pairing requires same asset, expiry, and put type, with long strike above short strike.
- Entry uses long ask minus short bid; max loss, max profit, breakeven, costs, and edge are bounded and auditable.
- Missing pairs and invalid legs are explicit rejections.
- API/UI show both legs and the direction label.

Blocking: OPS-005; shared vertical implementation.

## STRAT-007 — Add long straddle

Outcome: the scanner ranks same-strike, same-expiry long call + long put candidates for volatility expansion.

Acceptance criteria:

- Pairing requires one call and one put with the same asset, expiry, and strike.
- Entry, total cost, breakevens, IV/edge, Greeks, liquidity, and scenario fields are derived from both legs.
- The result states that max loss is the paid premium and max profit is unbounded.
- Sparse chains and missing counterpart legs are explicit rejections.

Blocking: STRAT-001, STRAT-002, OPS-005.

## STRAT-008 — Add long strangle

Outcome: the scanner ranks out-of-the-money long put + long call candidates at one expiry.

Acceptance criteria:

- Pairing requires one put and one call with the same asset and expiry and distinct strikes.
- Strike ordering, two-leg pricing, breakevens, costs, Greeks, and liquidity are exposed.
- The scanner rejects same-strike pairs as straddles and does not mix expiries.
- Candidate reasons identify missing leg, invalid quote, and insufficient liquidity separately.

Blocking: STRAT-001, STRAT-002, OPS-005.

## STRAT-009 — Add iron condor

Outcome: the scanner ranks four-leg defined-risk range strategies with two protective wings.

Acceptance criteria:

- Pairing requires put wing/short put/short call/call wing with one asset and expiry and strictly increasing strikes.
- Entry credit/debit, max profit, max loss, two breakevens, costs, aggregate Greeks, and all four legs are returned.
- No unprotected short option is ever emitted.
- Partial chains and crossed/invalid quotes produce auditable rejections.

Blocking: STRAT-003 through STRAT-006, OPS-005.

## STRAT-010 — Add covered call

Outcome: the scanner reports a long-underlying plus short-call income candidate without pretending the underlying leg is an option quote.

Acceptance criteria:

- The scan contract explicitly represents the underlying position and short call separately.
- Required spot/underlying quantity, call quote, premium, capped upside, downside risk, yield, fees, and IV context are shown.
- The result is labeled as a covered position and never as a naked short call.
- The evidence gate and read-only safety contract remain enforced.

Blocking: OPS-001, OPS-005; underlying-position data contract.

## STRAT-011 — Add iron butterfly

Outcome: the scanner ranks a four-leg, same-expiry, centered short straddle protected by long call and put wings.

Acceptance criteria:

- Pairing requires a long lower put wing, short put body, short call body, and long upper call wing.
- The two short body strikes must be equal; wing strikes must be strictly outside the body.
- Response includes all four legs, net credit/debit, two breakevens, max profit, max loss, aggregate Greeks, costs, and explicit rejection reasons.
- No unprotected short call/put is emitted when either wing is missing.

Blocking: STRAT-003…STRAT-006, OPS-005.

## STRAT-012 — Add protective put

Outcome: the scanner reports an underlying position paired with a long put hedge.

Acceptance criteria:

- The contract distinguishes the underlying quantity from the option leg.
- Premium, hedge cost, downside floor, upside participation, fees, and IV context are shown.
- The result is never mislabeled as a naked long put or an execution instruction.

Blocking: OPS-001, OPS-005; underlying-position data contract.

## STRAT-013 — Add calendar spread

Outcome: the scanner ranks same-strike, same-option-type calendars across two expiries.

Acceptance criteria:

- Pairing requires one short front-expiry leg and one long back-expiry leg with the same asset, type, and strike.
- Term-structure/model status, net debit/credit, costs, Greeks, and expiry-specific liquidity are returned.
- The scanner rejects same-expiry pairs and any unprotected/malformed leg.

Blocking: OPS-001, OPS-002, OPS-005.

## STRAT-014 — Add long and broken-wing butterfly extension

Outcome: the scanner supports non-iron butterfly structures after the core ten is stable.

Acceptance criteria:

- The contract distinguishes long butterfly from iron butterfly and represents wing ratios explicitly.
- Max loss, max profit, breakevens, all legs, costs, and quantity ratios are auditable.
- Broken-wing variants cannot silently become an undefined-risk ratio spread.

Blocking: STRAT-011; quantity-ratio risk contract.

## Delivery plan and agent allocation

```text
STRAT-001/002 (regression) ─┐
                             ├─ STRAT-003/004/005/006 (vertical shared seam)
OPS-005 ─────────────────────┘             ├─ API contract
                                           └─ UI labels + multi-leg display

verticals ──> STRAT-009 (iron condor)
single legs ─> STRAT-007/008 (volatility combos)
verticals ──> STRAT-011 (iron butterfly)
OPS-001 + underlying contract ─> STRAT-010/012
OPS-001 + OPS-002 ─> STRAT-013
```

Completed delegation for the vertical milestone:

- Jason: core pairing, valuation, costs, bounded-risk metrics, and domain tests.
- Averroes: HTTP request validation, serialization compatibility, and API tests.
- Euler: strategy controls, multi-leg rendering, and browser/static tests.

The parent agent owns ticket maintenance, integration, full-suite verification, and resolving cross-slice naming/contract mismatches.
