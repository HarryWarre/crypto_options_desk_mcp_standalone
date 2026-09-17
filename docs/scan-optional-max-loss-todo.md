# SCAN-UX-005 TODO

- [x] Create issue document (`docs/issues/scan-ux-005-optional-max-loss.md`) and update tickets index.
- [ ] Slice 1: Backend API validation relaxation.
  - [ ] Write failing test in `tests/test_options_app_api.py` asserting simple scan accepts omitted/null `max_loss`.
  - [ ] Update `ScanFilters.validate_ranges` in `src/options_app/api.py` to allow `self.max_loss is None`.
  - [ ] Verify focused API tests pass.
- [ ] Slice 2: Frontend UI controls & client-side validation.
  - [ ] Update `src/options_app/static/index.html` to add placeholder `"Không giới hạn"` and update field help for `quick_max_loss`.
  - [ ] Update `src/options_app/static/app.js` to remove client validation requiring `maxLoss` when `!useAdvancedFilters`.
  - [ ] Verify static app tests pass.
- [ ] Slice 3: Playwright E2E browser tests.
  - [ ] Add/update tests in `e2e/options-scanner.spec.js` asserting form submission with empty `quick_max_loss` succeeds and sends `max_loss: null`.
  - [ ] Run Playwright tests.
- [ ] Slice 4: Verification & Standards Review.
  - [ ] Run full Python test suite (`pytest -q`).
  - [ ] Check `git diff --check`.
  - [ ] Two-axis review (Standards and Spec).
