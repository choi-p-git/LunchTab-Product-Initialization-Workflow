# Business Requirements and Development Roadmap

## Summary

Lunchtab Product Initialization is a Windows desktop workflow for building upload-ready
ProductData CSV files from Lunchtab ProductData templates, SAGE recipe-list exports, and optional
inventory exports. Inventory enrichment can come from an Odin workbook or a generic five-column
CSV template. The current refined workflow is operator-guided: parse source rows first, assign
venue categories manually, review and repair row data, steer POS names, review final output, then
export audited artifacts.

The app does not administer Lunchtab restriction policies in this workflow. Product category
assignment is limited to category names the operator enters or loads through a venue profile.

## Current Business Requirements

- Source exports must never be modified.
- Final output must match the selected Lunchtab ProductData template headers.
- ProductData template and recipe list are required to parse; Odin workbook and generic inventory
  CSV inputs are optional enrichment sources.
- Only one inventory source can be selected per run. Operators must choose either the Odin workbook
  or the generic inventory CSV, not both.
- Generic inventory CSV files must contain `Item Name`, `Price`, `Category`, `Barcode`, and
  `Stock` headers.
- Rows enter category assignment when they have usable item name and price.
- Missing barcode, duplicate barcode, missing name, missing price, missing category, invalid POS
  name, and duplicate POS name must block final export.
- Comma-separated barcode fields represent multiple barcodes for one product and must be split for
  duplicate validation.
- Final-row `Handle` should mirror `BaseProductName`.
- Final-row `IsOrderable` is operator-configurable and defaults to `false`.
- `ProductCategories` must contain operator-created Lunchtab category names only.
- Category assignment must be fast enough for bulk operator work: keyword, old category, barcode,
  category status, price, and no-price filters are part of the core workflow.
- Edit review must allow operators to choose which row to edit, delete unneeded rows, undo recent
  edit-review actions, and merge barcodes from source rows into a selected target row.
- POS-name generation must preserve previously reviewed POS names during back edits, validate the
  15-character limit and uniqueness, and learn in-session token/acronym preferences from manual
  overrides.
- Venue profiles persist category names and POS-name preference rules. They do not persist
  restriction policies or row-specific category decisions.
- Back edits must preserve previously touched values and revalidate dependent barcode/POS checks
  without silently recalculating accepted values.
- Every export must emit final CSV, category audit, POS-name audit, session audit, deleted-row
  audit, run manifest, and run summary.

## Current Guided Workflow

1. **Parse Sources**
   - Operator selects ProductData template, recipe list, optional Odin inventory workbook,
     optional generic inventory CSV, optional venue profile, output folder, and `IsOrderable`.
   - Selecting an Odin inventory workbook clears any generic inventory CSV selection, and selecting
     a generic inventory CSV clears any Odin inventory workbook selection.
   - App parses and merges candidate rows into a working session.
   - `old_category` is preserved from source data for filtering.
   - A blank generic inventory CSV template is available from Step 1 for venues without usable
     Odin exports.
   - If a venue has rows from multiple inventory systems, the operator must manually consolidate
     them into the generic inventory CSV before parsing.
   - Category and POS-name decisions remain deferred.

2. **Categories**
   - Operator adds or loads category names.
   - Operator filters rows by keyword, old category, barcode type, category assignment state, price,
     and no-price state.
   - Operator mass-selects, selects highlighted rows, assigns categories, deletes rows, or marks
     rows for edit review.
   - Category assignment refreshes stale edit-review reasons before the operator moves forward.

3. **Edit Review**
   - Operator reviews queued rows and can load any selected row into the edit form.
   - Editable fields are name, price, barcode, and category.
   - Category edit uses the session category catalog as a dropdown while still allowing typed
     corrections.
   - No-barcode filtering, select-all shown, individual toggles, deletion, undo, and row merge are
     supported.
   - Merge transfers source barcode values into the selected target row, comma-separates them, and
     deletes source rows from export.

4. **POS Names**
   - App generates missing POS names after category/edit review.
   - Existing reviewed POS names are preserved during back edits.
   - Operator can filter by reason, select a row, type an override, press Enter to replace, and
     advance through the displayed list.
   - Manual overrides update token and acronym preference rules used for future suggestions.

5. **Final Review**
   - Operator reviews target output fields in a scrollable table.
   - Export remains disabled until active rows pass required-field, barcode, category, POS-name
     length, duplicate barcode, and duplicate POS-name validation.
   - Operator can save the venue profile again before export.

6. **Export Complete**
   - App writes the final import CSV, category audit, POS-name audit, session audit, deleted-row
     audit, manifest, and run summary.
   - Operator can open the output folder and major artifacts from the complete tab.

## Second-Pass Completion Snapshot

1. **Final-review metadata expansion**
   - Final review now shows selected source filenames with short SHA-256 hashes.
   - Final review shows active duplicate-check status for barcodes and POS names.
   - Final review shows category counts by category.
   - Final review shows edit count, POS override count, deleted count, merge count, and
     `IsOrderable`.
   - Keep the table focused on upload columns while metadata is displayed in a separate summary
     area.

2. **Merge and deleted-row audit refinement**
   - Merge audit details now include target row, source row, transferred barcodes, target barcode
     before merge, target barcode after merge, operator action timestamp, and source-row deletion
     reason.
   - Deleted-row audit columns preserve source row name, price, category, barcode, old category,
     final deletion reason, and merge-specific transfer details.

3. **Targeted workflow tests**
   - Controller-level coverage now protects Step 2 checked-row selection, highlighted-row fallback,
     highlighted-delete confirmation, select shown, and deselect shown behavior.
   - Controller-level coverage now protects Step 4 displayed-row advance after replacement,
     including filtered lists and rows that leave the current filter.
   - End-to-end session coverage now includes back edits from final review through category, edit,
     merge, POS review, and final validation, plus a local raw-data/profile integration test that
     parses real ignored source exports, applies the saved venue profile, completes a deterministic
     export subset, and verifies final CSV/audit/manifest outputs.

4. **Operator UX hardening**
   - Undo buttons now show the next action to be reverted for category and edit-review workflows.
   - Step 1 now enforces a single inventory source per run: Odin workbook or generic inventory CSV.

## Third-Pass Roadmap

1. **Widget-Level GUI Coverage**
   - Add display-safe Tk widget tests that skip cleanly when Tcl/Tk or a display server is
     unavailable.
   - Step 2 Delete-key behavior, inline category dropdown behavior, and keyword filter debounce
     behavior are covered through a real `ProductInitializationApp` instance.
   - Cover Step 4 reason filter changes, Enter-to-replace, displayed-row advance, and entry focus
     or selection state through widget-level tests.

2. **Layout and UX Refinement**
   - Review all tabs at 1366x768 with Windows display scaling and confirm primary actions remain
     visible and reachable.
   - Reduce unnecessary clicks in high-volume work paths: category assignment, edit review,
     no-barcode deletion, row merge, and POS-name override.
   - Improve final-review metadata density without crowding the export and profile-save actions.
   - Preserve the controller/session separation while moving any repeated widget-state rules into
     testable helpers.

3. **Operator Documentation**
   - Build an operator quick-start for running the app from source or packaged builds.
   - Build a formal SOP for the full import workflow, including source export prerequisites,
     Lunchtab admin setup, category/profile preparation, import execution, validation, and
     post-import checks.
   - Interview the operator before finalizing SOP sections that depend on off-app Lunchtab
     configuration or local administrative policy.

4. **Business Analysis Package**
   - After the SOP interview, run a full BA analysis package in the private untracked
     `business analysis/` folder.
   - Capture current-state workflow, future-state workflow, actors, systems, business rules,
     exception paths, time trial estimates, risks, requirements, assumptions, and decision log.
   - Keep observed facts separate from inferred recommendations, and gate future-state proposals
     on explicit operator confirmation.

5. **Packaging and Release Readiness**
   - Build and smoke test a Windows desktop bundle.
   - Confirm Tcl/Tk packaging, default output folder behavior, and artifact open actions.
   - Add release notes once the operator workflow, quick-start, SOP, and BA review are accepted.

## Interview Topics for SOP and BA Pass

- Exact Lunchtab admin screens used before exporting `ProductData`.
- Required source export names, filters, and timing for ProductData, recipe list, and Odin
  inventory or generic inventory CSV.
- SOP should instruct operators to manually transfer Odin rows into the generic inventory CSV when
  a venue needs consolidated data from Odin and another inventory source in the same run.
- Whether repeat ProductData uploads should preserve existing product-library rows, since Lunchtab
  upload behavior may replace rather than append the product library.
- Venue category creation rules and whether category names differ by location.
- How barcodes are assigned, combined, or retired in Lunchtab before and after import.
- How `IsOrderable`, product publication, tax categories, requirement categories, and restriction
  categories are configured outside this app.
- Expected operator role, approval checkpoints, and escalation path for ambiguous rows.
- Current manual workflow duration by step, error rate, and target time savings.
- Post-import validation steps in Lunchtab POS/admin screens.

## Out of Scope for Current Refined Workflow

- Automatic category inference from restriction policy, category-policy metadata, or confidence
  scoring.
- Writing restriction-policy metadata into `ProductCategories`.
- Persisting row-specific category assignment decisions in the venue profile.
- Administering Lunchtab spending restrictions or exemption settings.
