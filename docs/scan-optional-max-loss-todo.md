# SCAN-UX-005 TODO

- [x] Create issue document (`docs/issues/scan-ux-005-optional-max-loss.md`) and update tickets index.
- [x] Slice 1: Backend API validation relaxation.
  - [x] Write failing test in `tests/test_options_app_api.py` asserting simple scan accepts omitted/null `max_loss`.
  - [x] Update `ScanFilters.validate_ranges` in `src/options_app/api.py` to allow `self.max_loss is None`.
  - [x] Verify focused API tests pass.
- [x] Slice 2: Frontend UI controls & client-side validation.
  - [x] Update `src/options_app/static/index.html` to add placeholder `"Không giới hạn"` and update field help for `quick_max_loss`.
  - [x] Update `src/options_app/static/app.js` to remove client validation requiring `maxLoss` when `!useAdvancedFilters`.
  - [x] Verify static app tests pass.
- [x] Slice 3: Playwright E2E browser tests.
  - [x] Add/update tests in `e2e/options-scanner.spec.js` asserting form submission with empty `quick_max_loss` succeeds and sends `max_loss: null`.
  - [x] Run Playwright tests.
- [x] Slice 4: Verification & Standards Review.
  - [x] Run full Python test suite (`pytest -q`).
  - [x] Check `git diff --check`.
  - [x] Two-axis review (Standards and Spec).
