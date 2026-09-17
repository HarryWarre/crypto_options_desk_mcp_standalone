# UI-002 — Live options desk workspace

Status: done  
Branch: `feat/live-options-desk`  
Worktree: `/Users/hoangviet/Flowsurface/.worktrees/live-options-desk`

## Problem

The current web experience is centered on a one-shot scanner form. It makes a
user wait for a scan, then navigate a large result table, even though the
underlying options desk needs a compact market view with continuously refreshed
quotes and signal context.

## Outcome

Turn Scanner into a live, read-only options desk inspired by the supplied
reference image:

- keep the existing scanner as the initial snapshot and filter control;
- add a server-owned WebSocket stream that periodically rescans the selected
  universe and emits timestamped snapshots;
- show connection state, last update, market summary cards, asset ticker cards,
  a compact opportunity board, and a focused opportunity detail panel;
- retain the existing evidence notes, payoff view, advanced filters, and
  paper-trading safety language;
- keep credentials server-side and keep the stream free of order-entry paths.

## Acceptance criteria

- [x] `WS /api/v1/opportunities/stream` accepts a validated scan request and
      emits `stream_status`, progress, `snapshot`, and error envelopes.
- [x] The server refreshes snapshots on a bounded interval, stops the refresh
      loop when the client disconnects, and does not expose exchange secrets.
- [x] The scanner UI has a dashboard-style live header with connection state,
      last update, selected assets, spot/signal/edge summary, and ticker cards.
- [x] The live opportunity board updates without a full page reload and has a
      visible stale/disconnected state.
- [x] The existing one-shot scan, backtest, monitoring, payoff, and safety
      flows remain behaviorally compatible.
- [x] The layout remains usable at desktop and 390px mobile widths without
      horizontal page overflow.
- [x] Backend, static contract, and browser tests cover the new stream and
      the live UI state transitions.

## Non-goals

- No order placement, close-order mutation, or credentials in browser code.
- No replacement of the existing scanner domain/ranking logic.
- No claim that a live model edge is a guaranteed return or validated outcome.

## Implementation slices

1. Add a reusable scan snapshot serializer and browser WebSocket endpoint.
2. Add a live desk shell and progressive dashboard components around the
   existing scanner result model.
3. Add client reconnect/stop behavior and stale-data safety messaging.
4. Extend deterministic API/static/browser coverage and run the full suite.
