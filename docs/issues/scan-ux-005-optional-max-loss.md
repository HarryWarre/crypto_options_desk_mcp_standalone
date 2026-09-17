# SCAN-UX-005 — Optional unconstrained maximum loss in options scanner

Status: ready for implementation, local draft  
Branch: `feat/scanner-optional-max-loss`  
Target: `main`

Remote publication is pending because this repository has no configured issue
tracker connection or `ready-for-agent` label.

## Problem

Currently, both the web interface and the backend API require the user to input
an explicit maximum loss threshold (`max_loss` / `quick_max_loss`) whenever
submitting a scan in simple/quick mode:

1. In `src/options_app/static/app.js` (lines 1254–1256):
   The client-side form validation blocks submission with:
   `"Hãy nhập mức lỗ tối đa cho mỗi ý tưởng."` if `quick_max_loss` is empty and
   valuation mode is not theoretical.
2. In `src/options_app/api.py` (lines 260–261):
   `ScanFilters.validate_ranges` raises `ValueError("max_loss is required for a simple scan")`
   when `market_view` is present and `max_loss is None` in executable or synthetic mode.
3. In `src/options_app/static/index.html` (lines 270–273):
   The `quick_max_loss` input lacks an explicit placeholder and explanation that
   scans can be unconstrained.

This forces users exploring the options universe to invent an arbitrary risk
budget number on every single scan, even when their goal is simply to explore all
valid market opportunities without an artificial loss cap.

## Outcome

Make maximum loss completely optional in the scanner:

- Users can run a scan immediately without entering any loss limit.
- Leaving `quick_max_loss` empty defaults to unconstrained loss (`max_loss = None`),
  returning all opportunities that meet the strategy, liquidity, and pricing criteria.
- Users who still want a risk ceiling can optionally enter a non-negative number.
- The UI copy and placeholder reflect `"Không giới hạn"` by default.
- Scan context and summary transparently state `"Lỗ tối đa: không giới hạn"` when omitted.
- Product safety and risk semantics (`CONTEXT.md`) remain intact: each individual
  opportunity still computes and displays its actual bounded or model-estimated
  maximum loss; only the search filter constraint becomes optional.

## Source context

- Specification: [Options Scanner UX Simplification Specification](../options-scanner-ux-simplification-spec.md) (notably lines 85: *"If product copy supports 'no limit,' represent that explicitly as null rather than silently sending a very large number"*).
- Preceding tickets: [Options Scanner UX Simplification Tickets](../options-scanner-ux-simplification-tickets.md) (`SCAN-UX-001` through `SCAN-UX-004`).
- Operating rules: [Agent Operating Rules](../../AGENTS.md) and `docs/agent-rules/`.
- Domain glossary: [CONTEXT.md](../../CONTEXT.md) (Option opportunity metrics, maximum loss as bounded-payoff field).

## Acceptance criteria

- [ ] `POST /api/v1/opportunities/scan` accepts simple scan requests with `max_loss` omitted or `null` across all valuation modes (`executable`, `theoretical`, `synthetic`).
- [ ] `ScanFilters.validate_ranges` in `src/options_app/api.py` no longer raises `ValueError("max_loss is required for a simple scan")`.
- [ ] When `max_loss` is `None`, the underlying `opportunity_scanner.py` does not filter out opportunities based on maximum loss.
- [ ] When `max_loss` is provided as a positive number, the scanner continues to filter out candidates where `opportunity.max_loss > request.max_loss`.
- [ ] Negative `max_loss` values continue to be rejected by schema validation (`ge=0`).
- [ ] In `src/options_app/static/app.js`, `scanPayloadFromForm` allows `quick_max_loss` to be empty without returning a client-side validation error, sending `max_loss: null`.
- [ ] In `src/options_app/static/index.html`, `quick_max_loss` input has placeholder `"Không giới hạn"` and updated field help explaining that leaving the field blank means no loss limit is applied.
- [ ] The scan summary and scan context display `"không giới hạn"` when `max_loss` is omitted or null.
- [ ] Live WebSocket streaming endpoint (`WS /api/v1/opportunities/stream`) accepts requests without `max_loss` and functions identically.
- [ ] Each opportunity card, table row, and payoff detail continues to report the candidate's actual maximum loss according to `CONTEXT.md`.
- [ ] Backend API tests (`tests/test_options_app_api.py`) verify acceptance of simple scan requests without `max_loss`.
- [ ] Playwright browser tests (`e2e/options-scanner.spec.js`) verify scanning with empty `quick_max_loss` succeeds and sends `max_loss: null`.

## Public seams under test

1. **HTTP scan API seam:**
   `POST /api/v1/opportunities/scan` with payload `{"assets": ["BTC"], "market_view": "up", "time_horizon": "7_30"}`
   returns status 200 with `scan_context.max_loss: null` and serialized opportunities.
2. **WebSocket stream seam:**
   `WS /api/v1/opportunities/stream` with same payload emits snapshot with `scan_context.max_loss: null`.
3. **Browser user flow seam:**
   Playwright opens scanner workspace, selects asset and strategy, leaves `Lỗ tối đa mỗi ý tưởng` blank,
   clicks "Quét cơ hội", observes outgoing payload with `max_loss: null`, and verifies results render.

## Non-goals

- No changes to how individual candidate maximum loss or payoff curves are calculated.
- No removal of the `max_loss` input field entirely (it remains as an optional filter).
- No automated trading or order execution paths.
- No relaxation of non-negative validation (`max_loss < 0` remains invalid).

## Implementation slices

1. **Slice 1 (API & Models):**
   Remove mandatory `max_loss` check in `ScanFilters.validate_ranges` in `src/options_app/api.py`.
   Update API test `test_scan_rejects_simple_request_without_max_loss` to `test_scan_accepts_simple_request_without_max_loss`.
2. **Slice 2 (UI & Static App):**
   Remove client-side validation block in `scanPayloadFromForm` in `src/options_app/static/app.js`.
   Add placeholder `"Không giới hạn"` and update field help in `src/options_app/static/index.html`.
3. **Slice 3 (E2E & Playwright):**
   Add or update Playwright tests in `e2e/options-scanner.spec.js` to cover scanning without entering `quick_max_loss`.
4. **Slice 4 (Verification & Standards Review):**
   Run full Python test suite (`pytest -q`), Playwright suite, and verify `git diff --check`.
