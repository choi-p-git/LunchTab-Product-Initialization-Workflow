from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from lunchtab_product_init.models import BuildInputs
from lunchtab_product_init.workflow import build_product_import


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_build_product_import_accepts_complete_matched_row(tmp_path: Path) -> None:
    template = tmp_path / "ProductData.csv"
    headers = [
        "Handle",
        "ProductVersionType",
        "Price",
        "UnitCost",
        "Barcodes",
        "LowInventoryThreshold",
        "BaseProductName",
        "BaseProductPosName",
        "ShortDescription",
        "LongDescription",
        "IsPublished",
        "IsOrderable",
        "MaxPerPersonOrderQty",
        "ValidToDate",
        "ProductCategories",
        "RequirementCategories",
        "RestrictionCategories",
        "TaxCategories",
        "Vendor",
    ]
    write_csv(
        template,
        [{"Handle": "example-product", "BaseProductName": "Example Product (Please Remove)"}],
        headers,
    )

    recipe = tmp_path / "recipeList.csv"
    write_csv(
        recipe,
        [{"Recipe ID": "1", "Menu Item Name": "Assorted Cold Cereals", "Price": "$1.75", "Barcode": "ABC123", "Combo/Seasoning Item Recipe IDs": ""}],
        ["Recipe ID", "Menu Item Name", "Price", "Barcode", "Combo/Seasoning Item Recipe IDs"],
    )

    inventory = tmp_path / "inventory.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Report"])
    sheet.append(["Stock", "Item", "Retail Price", "Department", "Barcode"])
    sheet.append(["5", "Assorted Cold Cereals", "1.75", "Breakfast", "ABC123"])
    workbook.save(inventory)

    result = build_product_import(
        BuildInputs(
            product_template_path=template,
            recipe_list_path=recipe,
            odin_inventory_path=inventory,
            output_root=tmp_path / "out",
        )
    )

    assert result.summary.accepted_rows == 1
    assert result.summary.manual_review_rows == 0
    with result.summary.output_paths.final_import.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["BaseProductPosName"] == "AsstColdCereals"
    assert rows[0]["ProductCategories"] == "Breakfast;Exempt Prepared;"
    with result.summary.output_paths.category_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert audit_rows[0]["FinalCategories"] == "Breakfast;Exempt Prepared;"
    assert audit_rows[0]["ConfidenceBand"] == "high"
