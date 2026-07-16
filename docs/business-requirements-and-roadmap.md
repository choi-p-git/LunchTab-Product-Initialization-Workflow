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
- Final-row `Handle` should mirror `BaseProductName`.
- Final-row `IsOrderable` is operator-configurable and defaults to `false`.
- `ProductCategories` must contain only category names that the operator created directly in
  Lunchtab; restriction policy must not be written as a separate product category.
- Category profiles must keep food/category assignment and restriction-policy metadata as separate
  concepts.
- Restriction policy metadata is used only for operator visibility, audit evidence, and category
  sorting logic. Lunchtab remains the system that enforces exemption/non-exemption settings.
- The current starter profile assumes packaged snack categories are non-exempt and prepared,
  plated, or trayed snack categories are exempt.
- Operators must be able to tune the venue category catalog and category rules through import,
  export, GUI review, and manual correction workflows.
- Manual review must be an in-GUI workflow that allows operators to accept low-confidence category
  suggestions, change categories, and use review decisions to improve future matching rules.
- Every run must emit auditable artifacts, including category confidence and matched-rule evidence.
- Odin and recipe-list rows are both source-of-truth inputs; they do not need to match each other
  to be eligible.
- Odin-backed rows with `Stock` equal to `0` must be excluded from final automation and written to a
  dedicated review artifact.

## Roadmap

1. **Private BA plus tracked summary**: keep detailed BA artifacts ignored and maintain this
   sanitized tracked roadmap.
2. **Venue category catalog**: store operator-approved Lunchtab category names, restriction-policy
   metadata, enabled status, matching criteria, and notes.
3. **Category rule engine**: infer output categories from barcode overrides, item-name overrides,
   Odin source category, phrase rules, token rules, and manual-review fallback without writing
   policy metadata into `ProductCategories`.
4. **Operator tuning and review GUI**: manage the full category profile, import/export profiles,
   test sample items, review low-confidence suggestions in-app, and use review corrections to
   improve rules.
5. **Upload readiness and packaging**: validate unresolved review rows, required fields, category
   compliance, duplicate barcodes, duplicate POS names, and Windows packaging.

## Lunchtab Category Behavior

Lunchtab product categories can be used for filtering/reporting and can also carry
exemption/non-exemption settings inside Lunchtab. The app does not administer Lunchtab spending
restrictions in v1. It prepares category assignments in the ProductData CSV and records restriction
policy metadata in profile/audit views so operators can align products with their configured
Lunchtab category policy.
