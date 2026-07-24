# Operator Quick Start

Use this guide to create a Lunchtab product import CSV from the files provided for a venue.
The app does not change the files you select.

## Before You Start

Prepare these files:

- Lunchtab `ProductData...csv` template or prepopulated ProductData CSV.
- SAGE recipe list CSV.
- Optional inventory file: choose either Odin inventory or generic inventory, not both.
- Optional venue profile JSON.

If you need a generic inventory file, use the `Template` button in Step 1. Fill in the template
with these columns:

```text
Item Name,Price,Category,Barcode,Stock
```

If a venue has inventory from more than one system, put the needed rows into the generic inventory
CSV and use that one file.

## Start the App

Launch the Lunchtab Product Initialization app.

The default output folder is `Documents\Lunchtab Product Initialization`; each export creates a
new folder for that run.

## Step 1: Parse Sources

1. Select the ProductData CSV.
2. Choose the ProductData mode:
   - Use `Blank template` for a freshly downloaded template.
   - Use `Prepopulated ProductData` when the CSV already contains real Lunchtab products.
3. Select the SAGE recipe list.
4. Optionally select one inventory file.
5. Optionally load a venue profile.
6. Confirm the output folder.
7. Confirm whether new rows should default to `IsPublished` or `IsOrderable`.
8. Click `Parse sources`.

Normal starting setting: leave `IsOrderable` false unless the venue owner decides otherwise.

In `Prepopulated ProductData` mode, the app removes the demo row, stages existing product rows for
review, and keeps them in the final CSV unless you delete them.

## Step 2: Categories

1. Add category names or use categories loaded from the venue profile.
2. Use filters to narrow the table by keyword, duplicate name, old category, barcode type,
   assigned category state, price, or inventory stock.
3. Click column headers to sort what is shown.
4. Select rows with checkboxes, highlighted rows, or `Select all shown`.
5. Assign a category, delete rows that should not be imported, or mark rows for edit review.
6. Click `Next: Edit review` when the category step is complete.

Use `Clear filters` if rows appear hidden by active filters.

## Step 3: Edit Review

Use this step to fix rows that need review.

Common actions:

- Use `No barcode` to find rows that may need fast deletion.
- Use `Duplicate names` to group likely merge or rename work.
- Select a row to load it into the edit form.
- Edit name, price, barcode, and category.
- Press Enter or click `Save row edit` to save the loaded row and advance to the next displayed
  row.
- Use `Merge selected...` to combine barcodes into one row.
- Use `Undo` for recent edit-review actions.

If the save button is disabled, check the row fields for missing or conflicting information.

## Step 4: POS Names

1. Review the POS names.
2. Use the reason filter to focus rows that need attention.
3. Select a row, type an override, and press Enter or click `Replace`.
4. Use a suggestion if it matches the venue's preferred naming style.

Rules:

- POS names must be 15 characters or fewer.
- POS names must be unique within the active import.

Click `Next: Final review` when the button is available.

## Step 5: Final Review

Review the final upload before export.

- The initial final table is grouped by category and then item name.
- Click column headers to sort the displayed preview temporarily.
- Select a row and click `Edit selected row...` for a final correction.
- Confirm `IsPublished`, `IsOrderable`, and Core Catalogue values.
- Save the venue profile again if category names or POS-name preferences should be reused.
- Click `Confirm and export` when the file is ready.

## Step 6: Export Complete

Use the buttons on the complete tab to open:

- Output folder.
- Final import CSV.
- Core Catalogue CSV.
- Category audit.
- POS-name audit.
- Deleted-row audit.
- Run summary.

## Output Checks

Before uploading to Lunchtab, check:

- The final import CSV has the expected rows.
- Product categories are correct.
- POS names look correct and are short enough.
- `IsPublished` matches the intended run setting.
- `IsOrderable` matches the intended run setting.
- Core Catalogue rows are expected if that output is used for the venue.
- Deleted and merged rows are expected.
