# UI-001 — Professional options workspace shell

Status: merged
Branch: `feat/professional-options-workspace`

## Problem

The scanner and historical backtest are currently rendered as one long page. This makes the product read like a form dump instead of a professional options-pricing workstation, and it leaves no clear place for future modules.

## Outcome

Create a durable application shell with a left module navigation and two focused workspaces:

- **Scanner** — discover and inspect current option opportunities.
- **Backtest** — replay historical signals and review trade-level evidence.

Future modules should be visible as intentional, unavailable destinations rather than mixed into the current page.

## Product references

The interaction model is informed by paid options tools that separate research jobs and keep strategy/risk context close to the result:

- [OptionStrat strategy builder](https://optionstrat.com/tutorials/options-builder) keeps strategy construction, payoff visualization, and key risk statistics in one focused workspace.
- [ORATS](https://orats.com/) presents option scanning, backtesting, and trading as separate product capabilities with ranked candidates and validation context.
- [OptionNET Explorer](https://www.optionnetexplorer.com/explorer.aspx) frames design, backtesting, and monitoring as distinct but connected workflows.

These references are direction, not a request to copy branding or proprietary UI.

## Acceptance criteria

- [x] A persistent sidebar identifies the product and exposes Scanner and Backtest as the current modules.
- [x] Scanner is the default route and is addressable as `#scanner`.
- [x] Backtest is addressable as `#backtest`; switching modules updates the URL hash and does not render both primary workspaces at once.
- [x] Future destinations are represented as disabled “Sắp ra mắt” items and do not pretend to work.
- [x] Scanner controls, results, payoff detail, and technical log remain behaviorally compatible with existing tests.
- [x] Backtest controls and result table remain behaviorally compatible with existing tests.
- [x] The layout remains usable at a 1280px desktop viewport and a 390px mobile viewport without horizontal overflow in the app shell.
- [x] Navigation has keyboard-visible focus, `aria-current` for the active module, and an accessible label.
- [x] The product communicates research/paper-trading status without implying execution or validated profitability.

## Public seams under test

1. HTTP-served document: module landmarks and accessible navigation.
2. Browser navigation: click Scanner/Backtest, active state, URL hash, visible workspace.
3. Existing scanner and backtest form seams: submit payloads and visible results.
4. Responsive shell: app-shell and primary workspace bounds at desktop and mobile sizes.

## Non-goals

- No new pricing, scanner, or backtest domain logic.
- No broker connection, order placement, or portfolio-monitoring module.
- No replacement of existing result tables with a visual-only chart.

## QA inventory

- Initial state: sidebar, service status, Scanner active, Scanner visible, Backtest hidden.
- Scanner navigation: click Backtest, verify only Backtest is visible; return to Scanner.
- Deep link: load `#backtest`, verify Backtest is active on first render.
- Responsive shell: inspect 1280×900 and 390×844 for clipping/overflow.
- Existing critical flows: scanner submit/result and backtest submit/result.
- Exploratory checks: browser back/forward after module switching; refresh while on `#backtest`.

## Review outcome

Standards review: no blocking findings in the changed files; `git diff --check` is clean. The repository has no additional documented coding-standard file beyond `CONTEXT.md`.

Spec review: all acceptance criteria are covered by the browser/static tests and visual QA. The full Python suite passes; the full Playwright suite passes after rebasing onto `main`.
