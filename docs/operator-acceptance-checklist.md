# Operator Acceptance Checklist

Use this checklist to validate the v0.4.0 internal proof-of-concept build before using it for a
live venue import.

## Release Package

Record the package under test:

| Item | Value |
| --- | --- |
| Tester |  |
| Date |  |
| Venue or data set |  |
| App version | v0.4.0 |
| Installer file tested |  |
| Portable zip tested |  |
| Pass or fail |  |
| Blockers |  |

Check the release folder contains:

- `Lunchtab-Product-Initialization-Setup-v0.4.0.exe`
- `Lunchtab-Product-Initialization-Portable-v0.4.0.zip`
- `SHA256SUMS.txt`
- `RELEASE_NOTES-v0.4.0.md`

## Install and Launch

Installer checks:

- Installer opens without requiring administrator approval.
- Start Menu shortcut opens the app.
- Desktop shortcut opens the app if that option was selected.
- App shows the guided six-step workflow.
- Uninstall removes the installed app shortcuts.

Portable checks:

- Portable zip extracts normally.
- App opens from the extracted folder.
- App shows the guided six-step workflow.

## Source Files

Confirm the test run has:

- Lunchtab ProductData template CSV.
- SAGE recipe-list CSV.
- Optional Odin inventory workbook or optional generic inventory CSV.
- Only one inventory source selected if inventory enrichment is used.
- Optional saved venue profile JSON if profile loading is part of the test.
- Output folder selected or default output folder accepted.

## Workflow Checks

### Step 1 - Parse Sources

- ProductData template plus recipe list is enough to parse.
- Odin inventory workbook can be selected by itself as the inventory source.
- Generic inventory CSV can be selected by itself as the inventory source.
- Selecting one inventory source clears the other inventory source.
- Generic inventory template button opens or creates the blank CSV template.
- Saved venue profile loads category names and POS-name preferences.
- Parse completes and moves to category assignment.

### Step 2 - Categories

- Pressing Enter after typing a category adds it and focuses the category field again.
- Category list is sorted ascending.
- Keyword filter auto-applies after typing.
- Barcode, old category, category status, price, no-price, duplicate-name, and inventory-stock
  filters work as expected.
- Clear all filters returns the table to the unfiltered view.
- Rows can be selected by checkbox, double-click, single-click highlight, Shift-click range, and
  Ctrl-click multi-select.
- Delete key deletes highlighted rows when appropriate.
- Categories can be assigned from the action control and from the row category dropdown.
- Rows can be deleted or marked for edit review.
- Save venue profile writes a reusable profile when needed.
- Next is enabled only when category requirements are satisfied.

### Step 3 - Edit Review

- Missing barcode, duplicate barcode, name mismatch, missing price, missing category, and
  duplicate-name rows are queued for review.
- Manually marked review rows from Step 2 remain in the queue.
- No-barcode filter and select-all shown support fast deletion of invalid no-barcode rows.
- Duplicate-name filter groups rows by duplicated name for review or merge work.
- Operator can select any queued row to load it into the edit form.
- Category field supports dropdown selection.
- Save Row Edit saves only the currently loaded edited row.
- Save from mouse click and Enter key advances to the next displayed row.
- Invalid edits cannot be saved.
- Valid but unchanged rows require confirmation before approval.
- Merge popup shows a scrollable preview, transfers barcode values to the selected target row, and
  deletes the source row from export.
- Name mismatch rows cannot be approved unchanged; the operator must edit the surviving row,
  delete the row, or merge related rows so one barcode exports on one item only.
- Undo reverses the most recent supported edit-review action.
- Next remains disabled until all non-deleted queued rows are complete.

### Step 4 - POS Names

- Reason filter surfaces rows needing immediate POS-name attention.
- Suggestions never show values that violate the 15-character or duplicate-name rules.
- Selecting a row focuses and highlights the override field.
- Pressing Enter replaces a valid override and advances to the next displayed row.
- Clicking Replace also advances to the next displayed row.
- Manual overrides update later suggestions without silently changing already overridden rows.
- All active rows must have unique `BaseProductPosName` values of 15 characters or fewer before
  the workflow can continue.

### Step 5 - Final Review

- Table initially groups rows by category and sorts item names ascending within category.
- Header-click sorting works for inspection without changing audit row order.
- Metadata shows parsed rows, active rows, deleted rows, edited rows, category counts, POS-name
  overrides, duplicate checks, source filenames or hashes, and import flags.
- Selected-row edit dialog shows the full row and editable fields.
- Invalid final-review edits keep Save disabled.
- Valid final-review edits require confirmation before saving.
- Save venue profile is available before export.
- Export is enabled only when all active rows pass final validation.

### Step 6 - Export Complete

- Export creates the final import folder.
- Buttons open the output folder and major generated files.
- POS profile proposal can be created and opened when needed.

## Output Files

Confirm the export folder contains:

- `Lunchtab Product Import.csv`
- `Core Catalogue.csv`
- `Product Category Audit.csv`
- `BaseProductPosName Audit.csv`
- `POS Preference Profile.csv`
- `Session Review Audit.csv`
- `Deleted Product Audit.csv`
- `run-manifest.json`
- `run-summary.md`

Review the final import CSV:

- Headers match the Lunchtab ProductData template.
- `ProductCategories` values contain only valid Lunchtab product category names.
- A trailing semicolon after category names is acceptable for Lunchtab upload.
- `IsPublished` and `IsOrderable` match the run setting or row-level edits.
- Barcodes are present for every exported row.
- Comma-separated barcode values have no duplicate individual barcode collisions.
- `BaseProductPosName` values are unique and 15 characters or fewer.
- Rows expected to be deleted are absent from the final CSV and present in the deleted-row audit.

## Timing Notes

Capture timing during manual validation:

| Step | Start | End | Duration | Notes |
| --- | --- | --- | --- | --- |
| Step 1 - Parse Sources |  |  |  |  |
| Step 2 - Categories |  |  |  |  |
| Step 3 - Edit Review |  |  |  |  |
| Step 4 - POS Names |  |  |  |  |
| Step 5 - Final Review |  |  |  |  |
| Step 6 - Export Complete |  |  |  |  |

Record useful counts:

- Rows parsed:
- Rows exported:
- Rows deleted:
- Rows edited:
- Rows merged:
- POS-name overrides:
- Light POS edits:
- Moderate POS edits:
- Heavy POS edits:

## Sign-Off

| Decision | Name | Date | Notes |
| --- | --- | --- | --- |
| Accepted for internal testing |  |  |  |
| Blocked pending fixes |  |  |  |
| Ready for next packaged build |  |  |  |

Known limitation: v0.4.0 is still an internal proof of concept. Operators must manually review the
final CSV before upload.
