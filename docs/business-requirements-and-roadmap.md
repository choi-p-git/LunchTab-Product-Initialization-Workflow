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
- Missing barcode, duplicate barcode, barcode-matched source name mismatch, duplicate item name
  before edit approval, missing name, missing price, missing category, invalid POS name, and
  duplicate POS name must block final export.
- Comma-separated barcode fields represent multiple barcodes for one product and must be split for
  duplicate validation.
- Final-row `Handle` should mirror `BaseProductName`.
- Final-row `IsPublished` and `IsOrderable` are operator-configurable and default to `false`.
- `IsPublished`, `IsOrderable`, and Core Catalogue flags can be corrected by row during final
  review.
- `ProductCategories` must contain operator-created Lunchtab category names only.
- Category assignment must be fast enough for bulk operator work: keyword, old category, barcode,
  category status, price/no-price, and inventory-stock filters are part of the core workflow.
- Inventory-stock filters apply only to Odin or generic inventory rows, including recipe rows
  enriched by inventory matches. Recipe-only rows must not appear in stock-filtered views.
- Edit review must allow operators to choose which row to edit, delete unneeded rows, undo recent
  edit-review actions, and merge barcodes from source rows into a selected target row.
- POS-name generation must preserve previously reviewed POS names during back edits, validate the
  15-character limit and uniqueness, and learn in-session token/acronym preferences from manual
  overrides.
- Venue profiles persist category names and POS-name preference rules. They do not persist
  restriction policies or row-specific category decisions.
- Back edits must preserve previously touched values and revalidate dependent barcode/POS checks
  without silently recalculating accepted values.
- Operator viewport tables support header-click sorting without mutating session row order.
- Final import CSV rows are grouped by `ProductCategories` and sorted by `BaseProductName`
  ascending within each category.
- Audit artifacts preserve session/row-id order for traceability.
- Every export must emit final CSV, Core Catalogue CSV, category audit, POS-name audit, session
  audit, deleted-row audit, run manifest, and run summary.

## Current Guided Workflow

1. **Parse Sources**
   - Operator selects ProductData template, recipe list, optional Odin inventory workbook,
     optional generic inventory CSV, optional venue profile, output folder, `IsPublished`, and
     `IsOrderable`.
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
   - Operator filters rows by keyword, old category, barcode type, category assignment state,
     price/no-price state, and inventory stock state or quantity.
   - Operator mass-selects, selects highlighted rows, assigns categories, deletes rows, or marks
     rows for edit review.
   - Category assignment refreshes stale edit-review reasons before the operator moves forward.

3. **Edit Review**
   - Operator reviews queued rows and can load any selected row into the edit form.
   - Editable fields are name, price, barcode, and category.
   - Duplicate item names are automatically queued for manual review when the operator leaves
     category assignment; the operator must edit or approve each duplicate-name row before POS
     generation.
   - Barcode-matched recipe/inventory rows with mismatched source names are queued as
     `Name Mismatch` and require an edit, delete, or merge-style resolution before POS generation.
   - Save actions from mouse click or Enter key advance to the next displayed review row and
     focus the edit form for fast queue processing.
   - Saving a row re-runs required-field, barcode, category, and duplicate-name review checks so
     resolved duplicate pairs leave the queue and new name collisions are immediately flagged.
   - Edited item names are pre-validated for uniqueness before save; unchanged duplicate-name
     review rows can still be approved intentionally.
   - Category edit uses the session category catalog as a dropdown while still allowing typed
     corrections.
   - No-barcode filtering, duplicate-name grouping for merge work, select-all shown, individual
     toggles, deletion, undo, and row merge are supported.
   - Merge transfers source barcode values into the selected target row, comma-separates them, and
     deletes source rows from export.

4. **POS Names**
   - App generates missing POS names after category/edit review.
   - Existing reviewed POS names are preserved during back edits.
   - Operator can filter by reason, select a row, type an override, press Enter to replace, and
     advance through the displayed list.
   - Manual overrides update token and acronym preference rules used for future suggestions.
   - Learned token preferences keep ranked replacement options. Same-context overrides decay stale
     lower-confidence associations, while context-specific variants remain available for different
     item-name lengths.
   - Suggestion ranking reserves early slots for the top learned pattern and a later slot for a
     second-ranked pattern when it produces a valid POS name.
   - Export writes `POS Preference Profile.csv` so learned abbreviation rules, acronym patterns,
     examples, rank, counts, and spacing style can be reviewed before a future profile editor.
   - Step 4 includes an in-session POS profile rules dialog so operators can inspect learned token
     replacement rules and acronym patterns, promote or delete learned rules, and redirect token
     replacements without changing already overridden rows.
   - Accepted final import CSVs can be used with an optional existing venue profile to infer a
     proposed POS-name preference profile. This offline inference writes a proposal JSON plus audit
     files, flags competing token rules for review, and does not overwrite the active venue profile.
   - The Export Complete tab can create and open the proposed POS-name preference profile artifacts
     from the just-written final import CSV.
   - Step 4 remains the largest measured operator-effort stage because the operator must compare
     full item-name shape to POS-name readability, choose which letters or spaces to keep, and fit
     recognizable names within the 15-character rule.
   - POS-name replacement now records both edit amount and edit effort: characters changed, spaces
     changed, token/acronym changes, active edit actions, and light/moderate/heavy effort band.
     Row-level elapsed time should not be used as a primary effort metric because operators may be
     interrupted by calls or other duties.

5. **Final Review**
   - Operator reviews target output fields in a scrollable table.
   - Initial final review order matches final export order: category ascending, then item name
     ascending.
   - Operator can select a row, open an edit dialog with a full-row preview, and adjust final
     item name, POS name, price, barcode, category, published flag, orderable flag, or Core
     Catalogue flag before export.
   - Final-review edits are prevalidated before save and require confirmation before updating the
     working session.
   - Export remains disabled until active rows pass required-field, barcode, category, POS-name
     length, duplicate barcode, and duplicate POS-name validation.
   - Operator can save the venue profile again before export.

6. **Export Complete**
   - App writes the category/name-sorted final import CSV, Core Catalogue CSV, category audit,
     POS-name audit, session audit, deleted-row audit, manifest, and run summary.
   - Category, POS-name, session, and deleted-row audits retain session/row-id order.
   - Operator can open the output folder and major artifacts from the complete tab.

## Second-Pass Completion Snapshot

1. **Final-review metadata expansion**
   - Final review now shows selected source filenames with short SHA-256 hashes.
   - Final review shows active duplicate-check status for barcodes and POS names.
   - Final review shows category counts by category.
   - Final review shows edit count, POS override count, deleted count, merge count, published
     rows, orderable rows, and Core Catalogue rows.
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
   - Step 4 reason filter changes, Enter-to-replace, displayed-row advance, and override-entry
     focus or selection state are covered through widget-level tests.

2. **Layout and UX Refinement**
   - Review all tabs at 1366x768 with Windows display scaling and confirm primary actions remain
     visible and reachable.
   - Step 2 category action controls have been split into row-action and workflow-action bands,
     with widget coverage confirming primary controls remain visible at 1366x768.
   - Reduce unnecessary clicks in high-volume work paths: category assignment, edit review,
     no-barcode deletion, row merge, and POS-name override.
   - Step 4 now includes a POS profile rules dialog for observing learned token/acronym behavior
     and steering replacement rules during the active session.
   - Export Complete now provides a one-click POS profile proposal workflow and direct open buttons
     for the proposal, inference audit, and proposal folder.
   - Final-review metadata and edit actions are split into a wrapped summary row and a
     right-aligned action bar, with widget coverage confirming primary actions remain visible at
     1366x768.
   - Preserve the controller/session separation while moving any repeated widget-state rules into
     testable helpers.
   - Dev debug launcher is available for stage-locked workflow testing with sanitized tracked
     fixtures, Step 1-6 complete presets, Step 4 profile editing, and isolated debug output.

3. **Operator Documentation**
   - Operator quick-start is available in `docs/operator-quick-start.md` for running the app,
     preparing source files, completing the six-step workflow, checking upload flags, and checking
     output artifacts.
   - Internal SOP first draft is available in `docs/product-import-sop.md`, including source
     export prerequisites, Lunchtab category setup, category/profile preparation, import
     execution, approval, upload, post-import checks, escalation, and output retention.
   - Operator acceptance checklist is available in `docs/operator-acceptance-checklist.md` for
     validating v0.4.0 installer, portable, workflow, output, timing, and sign-off readiness.
   - Operator acceptance and SOP validation are on hold while the current tester is also the sole
     operator; resume when a second FSD or menu/pricing owner is available for review.

4. **Business Analysis Package**
   - After SOP validation resumes, run a full BA analysis package in the private untracked
     `business analysis/` folder.
   - Capture current-state workflow, future-state workflow, actors, systems, business rules,
     exception paths, time trial estimates, risks, requirements, assumptions, and decision log.
   - Keep observed facts separate from inferred recommendations, and gate future-state proposals
     on explicit operator confirmation.

5. **Packaging and Release Readiness**
   - v0.4.0 internal POC package has been built with PyInstaller and Inno Setup.
   - Release outputs include a per-user installer, portable zip, checksum file, and release notes.
   - Smoke verification covers source entry points, frozen executable, portable zip extract/run,
     and silent installer install/run/uninstall.
   - Operator acceptance checklist is available in `docs/operator-acceptance-checklist.md` for
     manual installer, portable, workflow, output, and sign-off validation.
   - Remaining release-readiness work is completing operator acceptance when manual validation
     resumes, not package creation.

## Interview Topics for SOP and BA Pass

- Exact Lunchtab admin screens used before exporting `ProductData`.
- Required source export names, filters, and timing for ProductData, recipe list, and Odin
  inventory or generic inventory CSV.
- SOP should instruct operators to manually transfer Odin rows into the generic inventory CSV when
  a venue needs consolidated data from Odin and another inventory source in the same run.
- Tested ProductData upload behavior updates matching existing items, keeps omitted existing items
  in place, and appends new items; seasonal-update planning should focus on match/update,
  duplicate, and new-item handling.
- Venue category creation rules and whether category names differ by location.
- How barcodes are assigned, combined, or retired in Lunchtab before and after import.
- How `IsPublished`, `IsOrderable`, Core Catalogue usage, tax categories, requirement categories,
  and restriction categories are configured outside this app.
- Expected operator role, approval checkpoints, and escalation path for ambiguous rows.
- Current manual workflow duration by step, error rate, and target time savings.
- Step 4 POS-name refinement now distinguishes light edits, moderate edits, and heavy overrides,
  and records edit amount so future algorithm work can target the actual effort driver rather than
  only counting overrides.
- Post-import validation steps in Lunchtab POS/admin screens.

## Out of Scope for Current Refined Workflow

- Automatic category inference from restriction policy, category-policy metadata, or confidence
  scoring.
- Writing restriction-policy metadata into `ProductCategories`.
- Persisting row-specific category assignment decisions in the venue profile.
- Administering Lunchtab spending restrictions or exemption settings.
