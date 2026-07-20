from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lunchtab_product_init.barcodes import duplicate_barcodes, parse_barcodes
from lunchtab_product_init.categories import (
    format_product_categories,
    format_restriction_policies,
    infer_categories,
    load_category_profile,
)
from lunchtab_product_init.io import read_csv, read_inventory_workbook, write_csv
from lunchtab_product_init.models import (
    BuildInputs,
    BuildResult,
    BuildSummary,
    LUNCHTAB_TEMPLATE_HEADERS,
    OutputPaths,
    CategoryResult,
    PosNameResult,
    ProductCandidate,
)
from lunchtab_product_init.naming import duplicate_values, generate_pos_name

FINAL_OUTPUT_NAME = "Lunchtab Product Import.csv"
MANUAL_REVIEW_OUTPUT_NAME = "Manual Review Products.csv"
ACCEPTED_AUDIT_NAME = "Accepted Product Audit.csv"
REJECTED_AUDIT_NAME = "Rejected Product Audit.csv"
NAMING_AUDIT_NAME = "BaseProductPosName Audit.csv"
CATEGORY_AUDIT_NAME = "Product Category Audit.csv"
ZERO_STOCK_REVIEW_NAME = "Zero Stock Odin Review.csv"
GENERIC_INVENTORY_HEADERS = ("Item Name", "Price", "Category", "Barcode", "Stock")


def default_output_root() -> Path:
    return Path.home() / "Documents" / "Lunchtab Product Initialization"


def _money_text(value: str) -> str:
    cleaned = str(value or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return ""
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return ""
    if not amount.is_finite():
        return ""
    return f"{amount:.2f}"


def _barcode(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _handle(name: str) -> str:
    return " ".join(str(name or "").split())


def _is_zero_stock(candidate: ProductCandidate) -> bool:
    if candidate.source not in {"odin", "inventory", "recipe+odin", "recipe+inventory"}:
        return False
    try:
        return Decimal(str(candidate.stock or "").strip()) == Decimal("0")
    except InvalidOperation:
        return False


def read_lunchtab_template(path: Path) -> list[str]:
    headers, rows = read_csv(path)
    missing = [header for header in LUNCHTAB_TEMPLATE_HEADERS if header not in headers]
    if missing:
        raise ValueError(f"Lunchtab template is missing required columns: {', '.join(missing)}")
    example_rows = [
        row
        for row in rows
        if row.get("Handle") == "example-product"
        or row.get("BaseProductName", "").startswith("Example Product")
    ]
    if len(rows) == len(example_rows):
        return headers
    return headers


def read_recipe_candidates(path: Path) -> list[ProductCandidate]:
    headers, rows = read_csv(path)
    required = {"Menu Item Name", "Price", "Barcode"}
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"Recipe list is missing required columns: {', '.join(missing)}")
    candidates = []
    for index, row in enumerate(rows, start=2):
        name = row.get("Menu Item Name", "").strip()
        barcode = _barcode(row.get("Barcode", ""))
        if not name and not barcode:
            continue
        candidates.append(
            ProductCandidate(
                source="recipe",
                source_key=f"recipe:{index}",
                item_name=name,
                price=_money_text(row.get("Price", "")),
                barcode=barcode,
                category="",
                recipe_name=name,
            )
        )
    return candidates


def read_odin_candidates(path: Path) -> list[ProductCandidate]:
    headers, rows = read_inventory_workbook(path)
    required = {"Stock", "Item", "Retail Price", "Department", "Barcode"}
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"Odin inventory is missing required columns: {', '.join(missing)}")
    candidates = []
    for index, row in enumerate(rows, start=2):
        item = row.get("Item", "").strip()
        barcode = _barcode(row.get("Barcode", ""))
        category = row.get("Department", "").strip()
        if not item and not barcode:
            continue
        if category.casefold() in {"discontinued", "separator", "category"}:
            continue
        candidates.append(
            ProductCandidate(
                source="odin",
                source_key=f"odin:{index}",
                item_name=item,
                price=_money_text(row.get("Retail Price", "")),
                barcode=barcode,
                category=category,
                stock=row.get("Stock", "").strip(),
                odin_name=item,
            )
        )
    return candidates


def read_generic_inventory_candidates(path: Path) -> list[ProductCandidate]:
    headers, rows = read_csv(path)
    missing = sorted(set(GENERIC_INVENTORY_HEADERS) - set(headers))
    if missing:
        raise ValueError(
            f"Generic inventory list is missing required columns: {', '.join(missing)}"
        )
    candidates = []
    for index, row in enumerate(rows, start=2):
        item = row.get("Item Name", "").strip()
        barcode = _barcode(row.get("Barcode", ""))
        if not item and not barcode:
            continue
        candidates.append(
            ProductCandidate(
                source="inventory",
                source_key=f"inventory:{index}",
                item_name=item,
                price=_money_text(row.get("Price", "")),
                barcode=barcode,
                category=row.get("Category", "").strip(),
                stock=row.get("Stock", "").strip(),
                odin_name=item,
            )
        )
    return candidates


def write_generic_inventory_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(GENERIC_INVENTORY_HEADERS)


def merge_candidates(
    recipe_candidates: list[ProductCandidate],
    odin_candidates: list[ProductCandidate],
) -> list[ProductCandidate]:
    by_barcode: dict[str, ProductCandidate] = {}
    no_barcode: list[ProductCandidate] = []
    for candidate in odin_candidates:
        if candidate.barcode:
            by_barcode[candidate.barcode] = candidate
        else:
            no_barcode.append(candidate)

    merged: list[ProductCandidate] = []
    seen_odin_barcodes: set[str] = set()
    for recipe in recipe_candidates:
        odin = by_barcode.get(recipe.barcode)
        if odin:
            seen_odin_barcodes.add(recipe.barcode)
            source = "recipe+inventory" if odin.source == "inventory" else "recipe+odin"
            merged.append(
                ProductCandidate(
                    source=source,
                    source_key=f"{recipe.source_key}|{odin.source_key}",
                    item_name=recipe.item_name or odin.item_name,
                    price=recipe.price or odin.price,
                    barcode=recipe.barcode,
                    category=odin.category,
                    stock=odin.stock,
                    recipe_name=recipe.item_name,
                    odin_name=odin.item_name,
                )
            )
        else:
            merged.append(recipe)

    for odin in odin_candidates:
        if odin.barcode not in seen_odin_barcodes:
            merged.append(odin)
    merged.extend(no_barcode)
    return merged


def classify_candidates(
    candidates: list[ProductCandidate],
    categories: dict[str, CategoryResult],
) -> tuple[list[ProductCandidate], list[ProductCandidate], dict[str, PosNameResult]]:
    barcode_duplicates = duplicate_barcodes(candidate.barcode for candidate in candidates)
    generated: dict[str, PosNameResult] = {}
    pos_values: list[str] = []
    for candidate in candidates:
        result = generate_pos_name(candidate.item_name)
        generated[candidate.source_key] = result
        pos_values.append(result.value)
    pos_duplicates = duplicate_values(pos_values)

    accepted: list[ProductCandidate] = []
    review: list[ProductCandidate] = []
    for candidate in candidates:
        reasons = []
        barcodes = parse_barcodes(candidate.barcode)
        if not candidate.item_name:
            reasons.append("missing item name")
        if not candidate.price:
            reasons.append("missing or invalid price")
        if not barcodes:
            reasons.append("missing barcode")
        if any(barcode.casefold() in barcode_duplicates for barcode in barcodes):
            reasons.append("duplicate barcode")
        category_result = categories[candidate.source_key]
        if category_result.status != "ok":
            reasons.append(category_result.reason)
        if not category_result.categories:
            reasons.append("missing category")
        if _is_zero_stock(candidate):
            reasons.append("zero Odin stock")
        name_result = generated[candidate.source_key]
        if name_result.status != "ok":
            reasons.append(name_result.reason)
        if name_result.value in pos_duplicates:
            reasons.append("duplicate generated POS name")

        if reasons:
            review.append(
                replace(
                    candidate, confidence="review", review_reason="; ".join(sorted(set(reasons)))
                )
            )
        else:
            accepted.append(replace(candidate, confidence="auto", review_reason=""))
    return accepted, review, generated


def product_row(
    headers: list[str],
    candidate: ProductCandidate,
    pos_name: str,
    category_result: CategoryResult,
    is_published: bool,
    is_orderable: bool,
) -> dict[str, str]:
    row = {header: "" for header in headers}
    row.update(
        {
            "Handle": _handle(candidate.item_name),
            "ProductVersionType": "Standard",
            "Price": candidate.price,
            "Barcodes": candidate.barcode,
            "BaseProductName": candidate.item_name,
            "BaseProductPosName": pos_name,
            "ShortDescription": candidate.item_name,
            "IsPublished": "true" if is_published else "false",
            "IsOrderable": "true" if is_orderable else "false",
            "ProductCategories": format_product_categories(category_result.categories),
        }
    )
    return row


def _audit_row(
    candidate: ProductCandidate,
    name_result: PosNameResult,
    category_result: CategoryResult,
) -> dict[str, str]:
    return {
        "Source": candidate.source,
        "SourceKey": candidate.source_key,
        "ItemName": candidate.item_name,
        "RecipeName": candidate.recipe_name,
        "OdinName": candidate.odin_name,
        "Price": candidate.price,
        "Barcode": candidate.barcode,
        "Category": candidate.category,
        "Stock": candidate.stock,
        "Confidence": candidate.confidence,
        "ReviewReason": candidate.review_reason,
        "GeneratedBaseProductPosName": name_result.value,
        "FinalCategories": format_product_categories(category_result.categories),
        "RestrictionPolicy": format_restriction_policies(category_result.restriction_policies),
        "CategoryConfidence": str(category_result.confidence),
        "CategoryConfidenceBand": category_result.confidence_band,
        "CategoryMatchedRules": " | ".join(category_result.matched_rules),
    }


def _output_paths(run_dir: Path) -> OutputPaths:
    return OutputPaths(
        final_import=run_dir / FINAL_OUTPUT_NAME,
        manual_review=run_dir / MANUAL_REVIEW_OUTPUT_NAME,
        zero_stock_review=run_dir / ZERO_STOCK_REVIEW_NAME,
        accepted_audit=run_dir / ACCEPTED_AUDIT_NAME,
        rejected_audit=run_dir / REJECTED_AUDIT_NAME,
        naming_audit=run_dir / NAMING_AUDIT_NAME,
        category_audit=run_dir / CATEGORY_AUDIT_NAME,
        manifest=run_dir / "run-manifest.json",
        summary=run_dir / "run-summary.md",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_single_inventory_source(inputs: BuildInputs) -> None:
    if inputs.odin_inventory_path is not None and inputs.generic_inventory_path is not None:
        raise ValueError("Select either Odin inventory or generic inventory, not both.")


def build_product_import(inputs: BuildInputs) -> BuildResult:
    _require_single_inventory_source(inputs)
    headers = read_lunchtab_template(inputs.product_template_path)
    category_profile = load_category_profile(inputs.category_profile_path)
    recipes = read_recipe_candidates(inputs.recipe_list_path)
    inventory = []
    if inputs.odin_inventory_path is not None:
        inventory.extend(read_odin_candidates(inputs.odin_inventory_path))
    if inputs.generic_inventory_path is not None:
        inventory.extend(read_generic_inventory_candidates(inputs.generic_inventory_path))
    candidates = merge_candidates(recipes, inventory)
    category_results = {
        candidate.source_key: infer_categories(candidate, category_profile)
        for candidate in candidates
    }
    accepted, review, names = classify_candidates(candidates, category_results)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = inputs.output_root / timestamp
    paths = _output_paths(run_dir)
    final_rows = [
        product_row(
            headers,
            candidate,
            names[candidate.source_key].value,
            category_results[candidate.source_key],
            inputs.is_published,
            inputs.is_orderable,
        )
        for candidate in accepted
    ]

    audit_headers = [
        "Source",
        "SourceKey",
        "ItemName",
        "RecipeName",
        "OdinName",
        "Price",
        "Barcode",
        "Category",
        "Stock",
        "Confidence",
        "ReviewReason",
        "GeneratedBaseProductPosName",
        "FinalCategories",
        "RestrictionPolicy",
        "CategoryConfidence",
        "CategoryConfidenceBand",
        "CategoryMatchedRules",
    ]
    naming_headers = [
        "SourceKey",
        "ItemName",
        "NormalizedName",
        "GeneratedBaseProductPosName",
        "Status",
        "Reason",
        "AbbreviationSteps",
    ]
    category_headers = [
        "SourceKey",
        "ItemName",
        "SourceCategory",
        "FinalCategories",
        "RestrictionPolicy",
        "Status",
        "Confidence",
        "ConfidenceBand",
        "Reason",
        "MatchedRules",
        "SourceEvidence",
    ]
    write_csv(paths.final_import, headers, final_rows)
    write_csv(
        paths.manual_review,
        audit_headers,
        (
            _audit_row(row, names[row.source_key], category_results[row.source_key])
            for row in review
        ),
    )
    zero_stock_review = [row for row in review if _is_zero_stock(row)]
    write_csv(
        paths.zero_stock_review,
        audit_headers,
        (
            _audit_row(row, names[row.source_key], category_results[row.source_key])
            for row in zero_stock_review
        ),
    )
    write_csv(
        paths.accepted_audit,
        audit_headers,
        (
            _audit_row(row, names[row.source_key], category_results[row.source_key])
            for row in accepted
        ),
    )
    write_csv(paths.rejected_audit, audit_headers, [])
    write_csv(
        paths.naming_audit,
        naming_headers,
        (
            {
                "SourceKey": candidate.source_key,
                "ItemName": candidate.item_name,
                "NormalizedName": names[candidate.source_key].normalized,
                "GeneratedBaseProductPosName": names[candidate.source_key].value,
                "Status": names[candidate.source_key].status,
                "Reason": names[candidate.source_key].reason,
                "AbbreviationSteps": " | ".join(names[candidate.source_key].abbreviation_steps),
            }
            for candidate in candidates
        ),
    )
    write_csv(
        paths.category_audit,
        category_headers,
        (
            {
                "SourceKey": candidate.source_key,
                "ItemName": candidate.item_name,
                "SourceCategory": candidate.category,
                "FinalCategories": format_product_categories(
                    category_results[candidate.source_key].categories
                ),
                "RestrictionPolicy": format_restriction_policies(
                    category_results[candidate.source_key].restriction_policies
                ),
                "Status": category_results[candidate.source_key].status,
                "Confidence": str(category_results[candidate.source_key].confidence),
                "ConfidenceBand": category_results[candidate.source_key].confidence_band,
                "Reason": category_results[candidate.source_key].reason,
                "MatchedRules": " | ".join(category_results[candidate.source_key].matched_rules),
                "SourceEvidence": " | ".join(
                    category_results[candidate.source_key].source_evidence
                ),
            }
            for candidate in candidates
        ),
    )

    barcode_counts = Counter(
        barcode.casefold()
        for candidate in candidates
        for barcode in parse_barcodes(candidate.barcode)
    )
    pos_counts = Counter(
        names[candidate.source_key].value
        for candidate in candidates
        if names[candidate.source_key].value
    )
    category_review_rows = sum(
        1 for result in category_results.values() if result.status != "ok" or not result.categories
    )
    summary = BuildSummary(
        candidate_rows=len(candidates),
        accepted_rows=len(accepted),
        manual_review_rows=len(review),
        rejected_rows=0,
        duplicate_barcodes=sum(1 for _, count in barcode_counts.items() if count > 1),
        duplicate_pos_names=sum(1 for _, count in pos_counts.items() if count > 1),
        category_review_rows=category_review_rows,
        zero_stock_review_rows=len(zero_stock_review),
        output_paths=paths,
    )
    _write_manifest(inputs, paths, summary)
    _write_summary(paths.summary, summary, run_dir)
    return BuildResult(run_dir=run_dir, summary=summary)


def _write_manifest(inputs: BuildInputs, paths: OutputPaths, summary: BuildSummary) -> None:
    artifact_paths = [
        paths.final_import,
        paths.manual_review,
        paths.zero_stock_review,
        paths.accepted_audit,
        paths.rejected_audit,
        paths.naming_audit,
        paths.category_audit,
        paths.summary,
    ]
    payload = {
        "workflow": "Lunchtab Product Initialization",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "product_template": {
                "filename": inputs.product_template_path.name,
                "sha256": _sha256(inputs.product_template_path),
            },
            "recipe_list": {
                "filename": inputs.recipe_list_path.name,
                "sha256": _sha256(inputs.recipe_list_path),
            },
            "odin_inventory": {
                "filename": inputs.odin_inventory_path.name,
                "sha256": _sha256(inputs.odin_inventory_path),
            }
            if inputs.odin_inventory_path is not None
            else None,
            "generic_inventory": {
                "filename": inputs.generic_inventory_path.name,
                "sha256": _sha256(inputs.generic_inventory_path),
            }
            if inputs.generic_inventory_path is not None
            else None,
        },
        "counts": {
            "candidate_rows": summary.candidate_rows,
            "accepted_rows": summary.accepted_rows,
            "manual_review_rows": summary.manual_review_rows,
            "duplicate_barcodes": summary.duplicate_barcodes,
            "duplicate_pos_names": summary.duplicate_pos_names,
            "category_review_rows": summary.category_review_rows,
            "zero_stock_review_rows": summary.zero_stock_review_rows,
        },
        "artifacts": {
            path.name: {"sha256": _sha256(path)} for path in artifact_paths if path.is_file()
        },
    }
    paths.manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_summary(path: Path, summary: BuildSummary, run_dir: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Lunchtab Product Initialization Run Summary",
                "",
                f"- Run folder: `{run_dir}`",
                f"- Candidate rows: {summary.candidate_rows}",
                f"- Auto-accepted rows: {summary.accepted_rows}",
                f"- Manual-review rows: {summary.manual_review_rows}",
                f"- Duplicate barcodes: {summary.duplicate_barcodes}",
                f"- Duplicate generated POS names: {summary.duplicate_pos_names}",
                f"- Category-review rows: {summary.category_review_rows}",
                f"- Zero-stock Odin review rows: {summary.zero_stock_review_rows}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Lunchtab product import CSV.")
    parser.add_argument("--product-template", type=Path, required=True)
    parser.add_argument("--recipe-list", type=Path, required=True)
    parser.add_argument("--odin-inventory", type=Path)
    parser.add_argument("--generic-inventory", type=Path)
    parser.add_argument("--output-root", type=Path, default=default_output_root())
    parser.add_argument("--category-profile", type=Path)
    parser.add_argument("--is-published", action="store_true")
    parser.add_argument("--is-orderable", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = build_product_import(
        BuildInputs(
            product_template_path=args.product_template,
            recipe_list_path=args.recipe_list,
            output_root=args.output_root,
            odin_inventory_path=args.odin_inventory,
            generic_inventory_path=args.generic_inventory,
            category_profile_path=args.category_profile,
            is_published=args.is_published,
            is_orderable=args.is_orderable,
        )
    )
    print(
        f"Wrote {result.summary.accepted_rows} row(s) to {result.summary.output_paths.final_import}"
    )
