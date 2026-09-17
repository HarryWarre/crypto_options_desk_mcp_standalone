# Read-only position monitoring before close execution

Status: accepted

The new position-monitoring module starts after the user's manual execution,
reads exchange state, and emits deterministic `CLOSE`, `HOLD`, or `REVIEW`
decisions plus an optional manual close instruction. It does not place or
modify orders in the first phase: exchange acknowledgements and fills are
asynchronous, so state reconciliation and human confirmation must be proven
before adding a closing adapter.

## Consequences

- The exchange position is operational truth; signal intent and local policy
  are context, not proof of a fill.
- A missing exit policy or unusable observation yields `REVIEW`, not `HOLD`.
- Any future closing adapter must remain a separate seam with reduce-only and
  terminal-confirmation guards.
