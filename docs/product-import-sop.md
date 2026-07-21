# Product Import SOP

## Purpose

Use this SOP to create and upload a Lunchtab product import CSV for a venue during initial
inventory/menu setup or a seasonal menu update.

Testing confirmed the ProductData upload updates matching existing items when uploaded values
change, leaves existing items in place when they are omitted from the CSV, and appends new items
that do not already exist. Before upload, confirm the final CSV contains the rows intended for this
upload.

## Scope

This SOP is for internal use by Food Service Directors (FSDs) or the person responsible for the
venue's menu and pricing.

## Roles

| Role | Responsibility |
| --- | --- |
| FSD or menu/pricing owner | Prepare source files, run the app, review corrections, and upload the final CSV. |
| On-Location General Manager | May approve the final CSV when responsible for menu and pricing. |
| General Manager or District Manager | Escalation point when the FSD is uncertain. |

## Required Files

Use the final live version of each source file before starting.

| File | Required | Owner | Source |
| --- | --- | --- | --- |
| ProductData template | Yes | FSD or menu/pricing owner | Lunchtab Admin Portal -> venue cafeteria/location -> Base Products -> Actions -> Upload Product Data -> Download CSV Template |
| SAGE recipe list CSV | Yes | FSD or menu/pricing owner | Current live SAGE recipe list export |
| Odin inventory workbook | Optional | FSD or menu/pricing owner | Store Manager Reports -> Inventory Reports -> Select Sales Area -> Report Type `Stocks and Prices` -> Sort Order `Department` -> Report Option `Export` |
| Generic inventory CSV | Optional | FSD or menu/pricing owner | Created from the app's generic inventory template |
| Venue profile JSON | Optional | FSD or menu/pricing owner | Saved from a previous app run |
| Live sales items report | Seasonal updates | FSD or menu/pricing owner | Lunchtab Admin Portal -> venue cafeteria/location -> Reporting -> Product Sales / Sales Items -> Actions -> Export as CSV |

Only use one inventory source per run: Odin inventory or generic inventory CSV. If the venue has
inventory from Odin and another system, copy the needed rows into the generic inventory CSV and use
that file.

The generic inventory CSV must use these headers:

```text
Item Name,Price,Category,Barcode,Stock
```

## Pre-Import Checklist

Complete this checklist before running the app.

- [ ] Confirm the ProductData template is from the correct Lunchtab venue/location.
- [ ] Confirm source files are the final live version for the menu cycle.
- [ ] For seasonal updates, export the current live sales items report from Lunchtab.
- [ ] Create all needed product categories in Lunchtab before import.
- [ ] Confirm category names to be entered in the app exactly match Lunchtab category names.
- [ ] Confirm whether `IsPublished` should stay false or be set true for this run.
- [ ] Confirm whether `IsOrderable` should stay false. Normal setting is false.
- [ ] Confirm whether any rows should be included in the Core Catalogue export.
- [ ] Confirm whether Odin inventory or generic inventory will be used, not both.

## Create Product Categories in Lunchtab

Before running the app, create every product category needed for the upload.

1. Open Lunchtab Admin Portal.
2. Go to `Categories`.
3. Go to `Product Categories`.
4. Select `Actions`.
5. Select `Add Product Category Type`.
6. Open the created category type submenu.
7. Select `Actions`.
8. Select `Add Product Category`.
9. Add the needed product categories.

Category names entered in the app must exactly match the names created in Lunchtab.

## Run the Product Initialization App

1. Launch the Lunchtab Product Initialization app.
2. Select the ProductData template.
3. Select the SAGE recipe list CSV.
4. Optionally select one inventory file:
   - Odin inventory workbook, or
   - generic inventory CSV.
5. Optionally load a venue profile JSON.
6. Confirm the output folder.
7. Leave `IsPublished` false unless the FSD or menu/pricing owner decides otherwise.
8. Leave `IsOrderable` false unless the FSD or menu/pricing owner decides otherwise.
9. Click `Parse sources`.

## Assign Categories

1. Add category names or use categories loaded from the venue profile.
2. Use filters to find rows by keyword, old category, barcode type, category status, price, or
   inventory stock.
3. Assign categories to rows.
4. Delete rows that should not be imported.
5. Mark rows for edit review when they need correction or confirmation.
6. Click `Next: Edit review` when available.

### Category Assignment Tips

- If the inventory report has useful stock levels, use the inventory stock filter. A stock value of
  `0` may help find inactive items, legacy items, or miscellaneous database rows.
- Use the barcode filter `No barcode` to find possible placeholders and non-essential rows. Board
  account items may still be valid and should be checked before deletion.
- Use the price filter `No price` to find rows that may be non-critical or need review.
- Use `Old Category` when available to group similar rows and speed up scanning. Previous category
  assignments may be wrong, so still review the rows before assigning.
- Use exact price, price conditions, or price range filters to find similar item groups.
- Combine `Old Category` and price filters to narrow the list to a specific category faster.
- Use the category status filter `No category` to keep the table focused on rows still pending
  category assignment.
- Add categories quickly by typing the category name and pressing Enter.
- Double-click a row to select it. Single-click highlighting can also be used for workflow
  actions.
- Use Shift-click to highlight a range of rows, or Ctrl-click to highlight rows that are not next
  to each other.
- Use the Delete key as a shortcut to delete highlighted rows when appropriate.
- Use the Up and Down arrow keys to move through rows.
- Use `Save venue profile...` to save category names for future imports.

## Review and Edit Rows

Use edit review to resolve missing or questionable information.

### No Barcode Rows

1. Use the `No barcode` filter.
2. Check whether each item is valid.
3. Retail account items are highly unlikely to be valid.
4. Board account items may be valid.
5. Delete invalid rows.
6. If the item is valid, add the barcode in edit review.

### Duplicate Names

1. Use the `Duplicate names` filter.
2. Reference the recipe ID where needed.
3. Proceed carefully: recipes with the same name can have different ingredients or allergen tags.
4. Choose the correct action:
   - merge rows,
   - delete unneeded rows, or
   - rename rows that represent different items.

### Duplicate Barcodes

1. Check item details for accuracy.
2. Use best judgment to merge, delete, or correct the row.
3. Escalate if ownership of the barcode is unclear.

### Missing Price

Enter the live or planned price.

### Save Edits

1. Select a row to load it into the edit form.
2. Edit name, price, barcode, or category as needed.
3. Press Enter or click `Save row edit`.
4. Continue until all required rows are complete.
5. Use `Undo` if a recent edit-review action needs to be reversed.

## Review POS Names

1. Review the POS names.
2. Use the reason filter to find rows that need attention.
3. Select a row and enter a replacement when needed.
4. Use FSD best judgment for venue naming style.
5. Keep POS names 15 characters or fewer.
6. Confirm POS names are unique.
7. Click `Next: Final review` when available.

## Final Review and Approval

The FSD or menu/pricing owner must manually review the final CSV before upload.

1. Review the final table in the app.
2. Confirm all items that should exist after upload are included.
3. Confirm existing items that should reappear in the new cycle are included.
4. Confirm item-to-category assignment.
5. Confirm prices.
6. Confirm barcodes.
7. Confirm POS button names are visible and understandable.
8. Confirm `IsPublished`.
9. Confirm `IsOrderable`.
10. Confirm Core Catalogue selections if the venue uses that output.
11. Use `Edit selected row...` for final corrections if needed.
12. Save the venue profile again if the categories or POS-name preferences should be reused.
13. Click `Confirm and export`.

## Upload to Lunchtab

1. Open Lunchtab Admin Portal.
2. Go to the venue cafeteria/location.
3. Go to `Base Products`.
4. Select `Actions`.
5. Select `Upload Product Data`.
6. Upload the final import CSV from the app output folder.

Important: tested upload behavior updates matching existing items, keeps omitted existing items in
place, and appends new items that do not already exist.

The Core Catalogue CSV is a separate app output. Do not upload it as the ProductData import file.

## Post-Upload Checks

After upload, check:

- item-to-category assignment,
- pricing,
- barcode accuracy,
- POS button name visibility,
- published/orderable status where applicable.

## If Upload Fails

1. Read the Lunchtab error message.
2. Manually check the final CSV.
3. Correct the issue in the app or CSV as appropriate.
4. Re-export or retry upload after correction.
5. Escalate to the General Manager or District Manager if uncertain.

## Escalation

Escalate when the FSD is uncertain.

Examples:

- unclear duplicate recipe,
- ingredient or allergen uncertainty,
- barcode ownership is unclear,
- price conflict,
- category is missing or unclear,
- uncertainty about whether an item should remain in the new cycle.

Escalate to the General Manager or District Manager, whichever is the FSD's direct oversight.

## Output Retention

Keep the full app output folder until the next Lunchtab product update is successful.

The final export CSV can be used as backup or rollback reference material.
