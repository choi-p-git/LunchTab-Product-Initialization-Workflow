# Business Requirements and Development Roadmap

## Summary

Lunchtab Product Initialization is a Windows desktop workflow for building upload-ready
ProductData CSV files from Lunchtab, recipe-list, and Odin inventory exports. The current refined
workflow is operator-guided: parse source rows first, assign venue categories manually, review and
repair row data, steer POS names, review final output, then export audited artifacts.

The app does not administer Lunchtab restriction policies in this workflow. Product category
assignment is limited to category names the operator enters or loads through a venue profile.

## Current Business Requirements

- Source exports must never be modified.
- Final output must match the selected Lunchtab ProductData template headers.
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
   - Operator selects ProductData template, recipe list, Odin inventory, optional venue profile,
     output folder, and `IsOrderable`.
   - App parses and merges candidate rows into a working session.
   - `old_category` is preserved from source data for filtering.
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

## Roadmap

1. **Final-review metadata expansion**
   - Show source filenames and source hashes from the manifest.
   - Show active duplicate-check status for barcodes and POS names.
   - Show category counts by category.
   - Show edit count, POS override count, deleted count, merge count, and `IsOrderable`.
   - Keep the table focused on upload columns while metadata is displayed in a separate summary
     area.

2. **Merge and deleted-row audit refinement**
   - Add explicit merge audit details: target row, source row, transferred barcodes, target barcode
     before merge, target barcode after merge, operator action timestamp, and source-row deletion
     reason.
   - Expand deleted-row audit columns so deletion and merge outcomes are readable without comparing
     multiple files.
   - Preserve source row name, price, category, barcode, old category, and final deletion reason.

3. **Targeted workflow tests**
   - Controller-level coverage now protects Step 2 checked-row selection, highlighted-row fallback,
     highlighted-delete confirmation, select shown, and deselect shown behavior.
   - Add remaining widget-level coverage for Step 2 delete shortcut, inline category dropdown, and
     filter event behavior.
   - Controller-level coverage now protects Step 4 displayed-row advance after replacement,
     including filtered lists and rows that leave the current filter.
   - Add remaining Step 4 GUI-focused coverage for reason filters, Enter-to-replace, and preserved
     widget selection/focus state.
   - Add end-to-end session tests for back edits from final review through category, edit, merge,
     POS review, and final validation.

4. **Operator UX hardening**
   - Review button layout at 1366x768 with Windows scaling.
   - Improve final-review metadata density without crowding the export action.
   - Consider richer undo history labels so operators can see what will be reverted.

5. **Packaging and release readiness**
   - Build and smoke test a Windows desktop bundle.
   - Confirm Tcl/Tk packaging, default output folder behavior, and artifact open actions.
   - Add release notes and operator quick-start documentation once the first manual workflow is
     accepted.

## Out of Scope for Current Refined Workflow

- Automatic category inference from restriction policy, category-policy metadata, or confidence
  scoring.
- Writing restriction-policy metadata into `ProductCategories`.
- Persisting row-specific category assignment decisions in the venue profile.
- Administering Lunchtab spending restrictions or exemption settings.
