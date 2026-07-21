from __future__ import annotations

import tkinter as tk
from pathlib import Path

from lunchtab_product_init.gui import ProductInitializationApp
from lunchtab_product_init.gui_controller import AppPhase
from lunchtab_product_init.io import read_csv
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.session_workflow import ImportSession, SessionRow


ROOT = Path(__file__).resolve().parents[1]
PROCESSED_RUN = ROOT / "business analysis" / "future-state" / "2026-07-19_203040"
SESSION_AUDIT = PROCESSED_RUN / "Session Review Audit.csv"
FINAL_IMPORT = PROCESSED_RUN / "Lunchtab Product Import.csv"
RAW_DATA = ROOT / "Raw Data"
PRODUCT_TEMPLATE = RAW_DATA / "ProductData_7_16_2026 4_06_08_PM.csv"
RECIPE_LIST = RAW_DATA / "recipeList_1784169005.csv"
ODIN_INVENTORY = RAW_DATA / "Cafeteria Inventory Stock and Prices Report 06-03-2026(1).xlsx"
OUTPUT_ROOT = ROOT / "demo output"


def main() -> None:
    session = _demo_session()
    root = tk.Tk()
    app = ProductInitializationApp(root)
    app.controller.select_product_template(PRODUCT_TEMPLATE)
    app.controller.select_recipe_list(RECIPE_LIST)
    app.controller.select_odin_inventory(ODIN_INVENTORY)
    app.controller.select_output_root(OUTPUT_ROOT)
    app.product_template_text.set(str(PRODUCT_TEMPLATE))
    app.recipe_list_text.set(str(RECIPE_LIST))
    app.odin_inventory_text.set(str(ODIN_INVENTORY))
    app.generic_inventory_text.set("")
    app.output_text.set(str(OUTPUT_ROOT))
    app.controller.set_session(
        session,
        phase=AppPhase.FINAL_REVIEW,
        message=(
            "Demo loaded at Step 5 from raw-data trial outputs with a blank in-memory profile."
        ),
    )
    app.profile_inference_result = None
    app.profile_inference_running = False
    app.venue_profile = None
    app.venue_profile_text.set("")
    app._render()
    app.notebook.select(app.tabs["final"])
    root.mainloop()


def _demo_session() -> ImportSession:
    _final_headers, final_rows = read_csv(FINAL_IMPORT)
    final_by_name = {row["BaseProductName"].casefold(): row for row in final_rows}
    _audit_headers, audit_rows = read_csv(SESSION_AUDIT)
    rows = []
    categories = set()
    for audit_row in audit_rows:
        final_row = final_by_name.get(audit_row["ItemName"].casefold())
        category = _category_from_final(final_row) or audit_row["Category"]
        if category:
            categories.add(category)
        rows.append(
            SessionRow(
                row_id=audit_row["RowId"],
                candidate=ProductCandidate(
                    source=audit_row["Source"],
                    source_key=audit_row["SourceKey"],
                    item_name=audit_row["ItemName"],
                    price=(final_row or {}).get("Price", audit_row["Price"]),
                    barcode=(final_row or {}).get("Barcodes", audit_row["Barcode"]),
                    category=audit_row["OldCategory"] or category,
                ),
                old_category=audit_row["OldCategory"],
                category=category,
                pos_name=(final_row or {}).get(
                    "BaseProductPosName", audit_row["BaseProductPosName"]
                ),
                status="deleted" if audit_row["Status"] == "deleted" else "pos_ready",
                review_reason=audit_row["ReviewReason"],
                deleted_reason=audit_row["DeletedReason"],
                edited=audit_row["Edited"].casefold() == "true",
                is_published=(final_row or {}).get("IsPublished", "").casefold() == "true",
                is_orderable=(final_row or {}).get("IsOrderable", "").casefold() == "true",
            )
        )
    return ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=tuple(rows),
        category_names=tuple(sorted(categories, key=str.casefold)),
    )


def _category_from_final(row: dict[str, str] | None) -> str:
    if row is None:
        return ""
    raw = row.get("ProductCategories", "")
    return raw.split(";", 1)[0].strip()


if __name__ == "__main__":
    main()
