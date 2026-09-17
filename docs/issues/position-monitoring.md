# Position monitoring and manual exit workflow

Status: in progress
Feature branch: `feat/position-monitoring`
Scope: start after manual execution; no automatic order placement in the first release.

## Problem

The existing system can scan signals and read current positions, but it does
not preserve a monitoring contract that explains whether a manually created
position should be closed, held conditionally, or reviewed because its state
is incomplete. PnL alone is not enough to make that decision.

## Target flow

```text
Valuation / Signal
        ↓
Manual Order Execution
        ↓
Position Tracker
        ↓
Risk Monitor
        ↓
Exit Decision Engine
        ↓
Manual Close Instruction
```

## Issue slices

| Issue | Description | Status | Merge target |
| --- | --- | --- | --- |
| PM-001 | Canonical position/policy contracts and deterministic risk/exit engine | done | `feat/position-monitoring` |
| PM-002 | Read-only Bybit snapshot adapter and order/position reconciliation | done | `feat/position-monitoring` |
| PM-003 | MCP `monitor_positions` tool with policy input and serialized decisions | done | `feat/position-monitoring` |
| PM-004 | Timestamped snapshot persistence, history, and monitoring workspace | done | `feat/position-monitoring` → `main` |
| PM-005 | Optional close-order adapter with explicit confirmation and kill switch | deferred | `feat/position-monitoring` → later review |
| PM-006 | SQLite monitoring snapshot/decision persistence | done | `feat/position-monitoring-live` |
| PM-007 | Bybit private WebSocket stream, reducer, reconnect, and REST reconciliation | done | `feat/position-monitoring-live` |
| PM-008 | Low-friction live monitoring workspace with dropdowns and decision queue | done | `feat/position-monitoring-live` |

## PM-001 acceptance criteria

- [x] A position is normalized independently of exchange-specific field names.
- [x] An exit policy requires an explicit risk budget when a percentage loss
      rule is used.
- [x] `CLOSE` is emitted for breached stop loss, take profit, max loss,
      maximum holding time, thesis invalidation, or liquidation-distance rule.
- [x] `HOLD` is emitted only when a policy exists and no rule or warning is
      present.
- [x] Missing policy and unusable observations emit `REVIEW`.
- [x] A close decision contains an opposite-side, current-quantity,
      reduce-only manual instruction and does not submit an order.
- [x] The module is side-effect free and covered by deterministic tests.

## PM-002 acceptance criteria

- [x] Read `option`, `linear`, and `inverse` positions through the existing
      private client without adding new order mutation.
- [x] Read open orders and a bounded order-history window, preserving status,
      fill, remaining quantity, trigger, reduce-only, and timestamps.
- [x] Mark partial/failed snapshots as `REVIEW`-eligible and never as a clean
      `HOLD` observation.
- [x] Preserve broker position quantity and mark-based unrealized PnL as
      observations; do not infer fills from HTTP acknowledgement.

## PM-003 acceptance criteria

- [x] Add a read-only MCP tool that accepts base coin/category and policies.
- [x] Return snapshot timestamp, source, open positions, open orders, and a
      decision per position with reason codes.
- [x] Keep secrets server-side and return a structured error when private
      credentials are unavailable.

## PM-004 acceptance criteria

- [x] Persist immutable snapshots with source timestamp and snapshot identifier.
- [x] Support comparing two snapshots for PnL, size, mark, order, and decision
      changes.
- [x] Expose the latest decision and its evidence through the read-only MCP
      history tool without suggesting that the output is investment advice or
      an executed action.
- [x] Expose a dedicated web workspace with hash navigation, manual policy
      inputs, decision rendering, and a read-only HTTP bridge to the monitor.

## PM-005 acceptance criteria

- [ ] Require an explicit human confirmation token before submission.
- [ ] Re-read broker quantity and position mode immediately before a close.
- [ ] Use reduce-only semantics, idempotency, and terminal order/position
      confirmation; HTTP success alone cannot mark the position closed.
- [ ] Keep the adapter disabled by default until PM-001 through PM-004 pass.

## Decision policy for the first release

| Condition | Decision |
| --- | --- |
| Explicit policy exists, all observations are usable, no rule triggers | `HOLD` |
| Stop, take profit, max loss, max holding time, thesis invalidation, or liquidation buffer triggers | `CLOSE` |
| Missing policy, mismatched symbol, invalid mark, or unavailable required risk data | `REVIEW` |

The thresholds are per-position policy inputs. They are not universal trading
rules and are not inferred from the scanner's signal.

## Live monitoring follow-up

PM-006 through PM-008 keep the same safety contract while reducing manual
interaction: the server authenticates the Bybit private stream, the UI uses
dropdowns populated from observed positions, and SQLite records each complete
monitoring snapshot. The stream is never an order-entry channel.

### PM-006 acceptance criteria

- [x] Store complete monitoring reports in a local SQLite database with a
      unique snapshot identifier and captured-at index.
- [x] Preserve raw private-stream events with stable deduplication keys for
      audit and reconnect diagnostics.
- [x] Keep the existing JSONL history adapter available for compatibility.

### PM-007 acceptance criteria

- [x] Authenticate and subscribe to Bybit private `position`, `order`, and
      `execution` topics over the server-owned WebSocket connection.
- [x] Bootstrap with REST, reduce position/order/execution deltas, and treat
      reconnects as a REST reconciliation boundary.
- [x] Send application heartbeats, reconnect after transport failure, and
      deduplicate execution events by `execId`.
- [x] Keep the stream read-only; it has no close-order or order-entry path.

### PM-008 acceptance criteria

- [x] Expose Position Monitoring in the sidebar and make the primary choices
      dropdowns: asset, category, observed symbol, and policy preset.
- [x] Render live `CLOSE`, `HOLD`, and `REVIEW` decisions with reason and
      evidence while clearly stating that any close remains manual.
- [x] Keep advanced thresholds collapsed so the common path is one action and
      does not require typing symbol/category values.

## Research

The source-backed findings and links used to shape these slices are in
[`docs/order-position-risk-research.md`](../order-position-risk-research.md).
