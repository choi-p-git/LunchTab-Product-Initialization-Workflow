from __future__ import annotations

import csv
from pathlib import Path

import pytest
from openpyxl import Workbook

from lunchtab_product_init.models import BuildInputs, CategoryResult, ProductCandidate
from lunchtab_product_init.workflow import (
    build_product_import,
    classify_candidates,
    write_generic_inventory_template,
)


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
        [
            {
                "Recipe ID": "1",
                "Menu Item Name": "Assorted Cold Cereals",
                "Price": "$1.75",
                "Barcode": "ABC123",
                "Combo/Seasoning Item Recipe IDs": "",
            }
        ],
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
    assert rows[0]["Handle"] == "Assorted Cold Cereals"
    assert rows[0]["IsOrderable"] == "false"
    assert rows[0]["BaseProductPosName"] == "AsstColdCereals"
    assert rows[0]["ProductCategories"] == "Breakfast;"
    with result.summary.output_paths.category_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert audit_rows[0]["FinalCategories"] == "Breakfast;"
    assert audit_rows[0]["RestrictionPolicy"] == "exempt"
    assert audit_rows[0]["ConfidenceBand"] == "high"


def test_write_generic_inventory_template_uses_required_headers(tmp_path: Path) -> None:
    template = tmp_path / "generic-inventory-template.csv"

    write_generic_inventory_template(template)

    assert template.read_text(encoding="utf-8-sig") == (
        '"Item Name","Price","Category","Barcode","Stock"\n'
    )
    with template.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    assert reader.fieldnames == ["Item Name", "Price", "Category", "Barcode", "Stock"]
    assert rows == []


def test_build_product_import_rejects_multiple_inventory_sources(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="either Odin inventory or generic inventory"):
        build_product_import(
            BuildInputs(
                product_template_path=tmp_path / "ProductData.csv",
                recipe_list_path=tmp_path / "recipe.csv",
                output_root=tmp_path / "out",
                odin_inventory_path=tmp_path / "inventory.xlsx",
                generic_inventory_path=tmp_path / "inventory.csv",
            )
        )


def test_build_product_import_can_mark_rows_orderable(tmp_path: Path) -> None:
    template, recipe, inventory = _build_basic_files(tmp_path, stock="5")
    result = build_product_import(
        BuildInputs(
            product_template_path=template,
            recipe_list_path=recipe,
            odin_inventory_path=inventory,
            output_root=tmp_path / "out",
            is_orderable=True,
        )
    )
    with result.summary.output_paths.final_import.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["IsOrderable"] == "true"


def test_zero_stock_odin_row_routes_to_dedicated_review_artifact(tmp_path: Path) -> None:
    template, recipe, inventory = _build_basic_files(tmp_path, stock="0")
    result = build_product_import(
        BuildInputs(
            product_template_path=template,
            recipe_list_path=recipe,
            odin_inventory_path=inventory,
            output_root=tmp_path / "out",
        )
    )
    assert result.summary.accepted_rows == 0
    assert result.summary.zero_stock_review_rows == 1
    with result.summary.output_paths.zero_stock_review.open(
        encoding="utf-8-sig", newline=""
    ) as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["ReviewReason"] == "zero Odin stock"


def test_odin_only_item_can_be_accepted_when_complete(tmp_path: Path) -> None:
    template, _recipe, inventory = _build_basic_files(tmp_path, stock="5")
    empty_recipe = tmp_path / "empty-recipeList.csv"
    write_csv(
        empty_recipe,
        [],
        ["Recipe ID", "Menu Item Name", "Price", "Barcode", "Combo/Seasoning Item Recipe IDs"],
    )
    result = build_product_import(
        BuildInputs(
            product_template_path=template,
            recipe_list_path=empty_recipe,
            odin_inventory_path=inventory,
            output_root=tmp_path / "out",
        )
    )
    assert result.summary.accepted_rows == 1


def test_classify_candidates_detects_duplicate_barcode_inside_comma_list() -> None:
    candidates = [
        ProductCandidate("recipe", "one", "Apple Juice", "1.25", "111,222", "Beverages"),
        ProductCandidate("recipe", "two", "Orange Juice", "1.25", "222", "Beverages"),
        ProductCandidate("recipe", "three", "Grape Juice", "1.25", "333", "Beverages"),
    ]
    categories = {
        candidate.source_key: CategoryResult(
            categories=("Beverages",),
            restriction_policies=(),
            status="ok",
            confidence=100,
            confidence_band="manual",
            reason="operator assigned",
            matched_rules=(),
            source_evidence=(),
        )
        for candidate in candidates
    }

    accepted, review, _names = classify_candidates(candidates, categories)

    assert [candidate.source_key for candidate in accepted] == ["three"]
    assert [candidate.source_key for candidate in review] == ["one", "two"]
    assert all("duplicate barcode" in candidate.review_reason for candidate in review)


def _build_basic_files(tmp_path: Path, *, stock: str) -> tuple[Path, Path, Path]:
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
        [
            {
                "Recipe ID": "1",
                "Menu Item Name": "Assorted Cold Cereals",
                "Price": "$1.75",
                "Barcode": "ABC123",
                "Combo/Seasoning Item Recipe IDs": "",
            }
        ],
        ["Recipe ID", "Menu Item Name", "Price", "Barcode", "Combo/Seasoning Item Recipe IDs"],
    )
    inventory = tmp_path / "inventory.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Report"])
    sheet.append(["Stock", "Item", "Retail Price", "Department", "Barcode"])
    sheet.append([stock, "Assorted Cold Cereals", "1.75", "Breakfast", "ABC123"])
    workbook.save(inventory)
    return template, recipe, inventory
