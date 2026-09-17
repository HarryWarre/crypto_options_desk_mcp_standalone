# Live position monitoring stream and SQLite history

Status: accepted

## Context

The monitoring module currently reads a point-in-time REST snapshot. A user
who manually creates an order needs low-latency position, order, and execution
updates without exposing Bybit credentials to the browser. The application
also needs durable evidence of what was observed and what decision was shown.

## Decision

- The server owns the authenticated Bybit private WebSocket connection and
  subscribes to `position`, `order`, and `execution` topics. The browser only
  connects to the app's own read-only WebSocket.
- REST is the bootstrap and reconciliation source after connection or
  reconnect. A stream update is not treated as a complete snapshot until the
  reducer has a valid baseline.
- The reducer keeps position identity by category, symbol, and position index;
  an empty Bybit position update removes the exposure. Order and execution
  events update the observable order set and append bounded history.
- SQLite is the default append-only monitoring store. Each persisted record is
  a complete immutable snapshot JSON document inside a transaction, with a
  unique snapshot identifier and capture sequence. JSONL remains available as
  a compatibility adapter for existing callers and tests.
- `CLOSE`, `HOLD`, and `REVIEW` remain read-only decisions. No WebSocket topic
  or UI action may submit, amend, or cancel an order.

## Consequences

- API keys never enter the browser or the frontend WebSocket protocol.
- Reconnects can temporarily show `REVIEW`/stale status until REST
  reconciliation completes; this is safer than showing a clean `HOLD`.
- SQLite adds a local file that must be backed up or removed deliberately in
  deployments; it does not become a broker source of truth.
- A future close-order adapter remains a separate, explicitly confirmed seam.
