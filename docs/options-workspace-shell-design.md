# Options workspace shell design

## Layout

```text
app shell
├── sidebar
│   ├── product identity + research status
│   ├── workspace navigation
│   │   ├── Scanner
│   │   ├── Backtest
│   │   └── Position Monitoring
│   └── future modules (disabled)
└── content area
    ├── module header + API/data status
    └── one active workspace
```

The shell should feel like a research terminal: quiet dark canvas, strong hierarchy, compact navigation, and a large task surface. Scanner, Backtest, and Position Monitoring are separate workspaces, not panels in a single scroll sequence.

## Navigation contract

- The canonical initial route is `#scanner`.
- A navigation item is an anchor so it works with keyboard input, browser history, and refresh.
- JavaScript owns only active-state synchronization and visibility; domain requests stay unchanged.
- Position Monitoring is a live, read-only workspace. It uses one primary action,
  dropdowns for the common choices, and a compact decision queue so the user
  can review a manual close/hold/review instruction without entering symbols.
- An unavailable future module has `aria-disabled="true"`, no active route, and a visible “Sắp ra mắt” label.

## Responsive behavior

- Desktop: fixed-width sidebar, scrollable content area.
- Small screens: sidebar becomes a horizontal/stacked module strip above the content; the content remains a single-column workspace.
- The shell must never require horizontal page scrolling to reach the active workspace controls.

## Visual hierarchy

1. Product identity and active module.
2. Primary task controls.
3. Result/evidence state.
4. Technical detail and raw tables.

The existing valuation notices, evidence notes, payoff chart, and backtest quality metadata remain in the result context because they are decision-safety information.
