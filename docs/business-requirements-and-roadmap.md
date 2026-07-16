# Business Requirements and Development Roadmap

## Summary

Lunchtab Product Initialization is a Windows desktop workflow for building upload-ready
ProductData CSV files from Lunchtab, recipe-list, and Odin inventory exports. The workflow is
venue-specific: operators define or import their valid Lunchtab product categories, then the app
uses conservative, auditable rules to assign categories, generate POS names, and route uncertain
rows to review.

## Business Requirements

- Source exports must never be modified.
- Final output must match the Lunchtab ProductData template.
- Each final row must have valid item name, price, barcode, `BaseProductPosName`, and
  `ProductCategories`.
- `ProductCategories` may contain multiple semicolon-separated values so a product can carry both
  food/reporting categories and spending-policy categories.
- Category rules must distinguish descriptive food categories from policy categories used for
  spending restriction behavior.
- The current starter profile assumes packaged items are restrictable when funds are insufficient
  and prepared/plated/trayed items are exempt from that policy.
- Operators must be able to tune the venue category catalog and category rules through import,
  export, GUI review, and manual correction workflows.
- Every run must emit auditable artifacts, including category confidence and matched-rule evidence.

## Roadmap

1. **Private BA plus tracked summary**: keep detailed BA artifacts ignored and maintain this
   sanitized tracked roadmap.
2. **Venue category catalog**: store operator-approved category names, roles, spending-policy
   behavior, enabled status, and notes.
3. **Category rule engine**: infer categories from barcode overrides, item-name overrides, Odin
   source category, phrase rules, token rules, and manual-review fallback.
4. **Operator tuning GUI**: manage category catalog/rules, import/export profiles, test sample
   items, and use review corrections to improve rules.
5. **Upload readiness and packaging**: validate unresolved review rows, required fields, category
   compliance, duplicate barcodes, duplicate POS names, and Windows packaging.

## Lunchtab Category Behavior

Lunchtab product categories can be used for filtering/reporting and can also be marked exempt from
spending restrictions. The app does not administer Lunchtab spending restrictions in v1; it prepares
category assignments in the ProductData CSV so the venue can align products with its configured
Lunchtab category policy.
