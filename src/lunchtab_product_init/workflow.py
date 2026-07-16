from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lunchtab_product_init.io import read_csv, read_inventory_workbook, write_csv
from lunchtab_product_init.models import (
    BuildInputs,
    BuildResult,
    BuildSummary,
    LUNCHTAB_TEMPLATE_HEADERS,
    OutputPaths,
    PosNameResult,
    ProductCandidate,
)
from lunchtab_product_init.naming import duplicate_values, generate_pos_name, normalize_text

FINAL_OUTPUT_NAME = "Lunchtab Product Import.csv"
MANUAL_REVIEW_OUTPUT_NAME = "Manual Review Products.csv"
ACCEPTED_AUDIT_NAME = "Accepted Product Audit.csv"
REJECTED_AUDIT_NAME = "Rejected Product Audit.csv"
NAMING_AUDIT_NAME = "BaseProductPosName Audit.csv"


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


def _handle(name: str, barcode: str) -> str:
    base = "-".join(normalize_text(name).split())[:48].strip("-") or "product"
    suffix = re.sub(r"[^a-zA-Z0-9]", "", barcode)[-6:]
    return f"{base}-{suffix}" if suffix else base


def _category(value: str) -> str:
    cleaned = " ".join(str(value or "").split())
    return f"{cleaned};" if cleaned and not cleaned.endswith(";") else cleaned


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
            merged.append(
                ProductCandidate(
                    source="recipe+odin",
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
) -> tuple[list[ProductCandidate], list[ProductCandidate], dict[str, PosNameResult]]:
    barcode_duplicates = duplicate_values([candidate.barcode for candidate in candidates])
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
        if not candidate.item_name:
            reasons.append("missing item name")
        if not candidate.price:
            reasons.append("missing or invalid price")
        if not candidate.barcode:
            reasons.append("missing barcode")
        if candidate.barcode in barcode_duplicates:
            reasons.append("duplicate barcode")
        if not candidate.category:
            reasons.append("missing category")
        if candidate.source != "recipe+odin":
            reasons.append("not matched between recipe list and Odin")
        name_result = generated[candidate.source_key]
        if name_result.status != "ok":
            reasons.append(name_result.reason)
        if name_result.value in pos_duplicates:
            reasons.append("duplicate generated POS name")

        if reasons:
            review.append(
                replace(candidate, confidence="review", review_reason="; ".join(sorted(set(reasons))))
            )
        else:
            accepted.append(replace(candidate, confidence="auto", review_reason=""))
    return accepted, review, generated


def product_row(headers: list[str], candidate: ProductCandidate, pos_name: str) -> dict[str, str]:
    row = {header: "" for header in headers}
    row.update(
        {
            "Handle": _handle(candidate.item_name, candidate.barcode),
            "ProductVersionType": "Standard",
            "Price": candidate.price,
            "Barcodes": candidate.barcode,
            "BaseProductName": candidate.item_name,
            "BaseProductPosName": pos_name,
            "ShortDescription": candidate.item_name,
            "IsPublished": "true",
            "IsOrderable": "true",
            "ProductCategories": _category(candidate.category),
        }
    )
    return row


def _audit_row(candidate: ProductCandidate, name_result: PosNameResult) -> dict[str, str]:
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
    }


def _output_paths(run_dir: Path) -> OutputPaths:
    return OutputPaths(
        final_import=run_dir / FINAL_OUTPUT_NAME,
        manual_review=run_dir / MANUAL_REVIEW_OUTPUT_NAME,
        accepted_audit=run_dir / ACCEPTED_AUDIT_NAME,
        rejected_audit=run_dir / REJECTED_AUDIT_NAME,
        naming_audit=run_dir / NAMING_AUDIT_NAME,
        manifest=run_dir / "run-manifest.json",
        summary=run_dir / "run-summary.md",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_product_import(inputs: BuildInputs) -> BuildResult:
    headers = read_lunchtab_template(inputs.product_template_path)
    recipes = read_recipe_candidates(inputs.recipe_list_path)
    odin = read_odin_candidates(inputs.odin_inventory_path)
    candidates = merge_candidates(recipes, odin)
    accepted, review, names = classify_candidates(candidates)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = inputs.output_root / timestamp
    paths = _output_paths(run_dir)
    final_rows = [product_row(headers, candidate, names[candidate.source_key].value) for candidate in accepted]

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
    write_csv(paths.final_import, headers, final_rows)
    write_csv(paths.manual_review, audit_headers, (_audit_row(row, names[row.source_key]) for row in review))
    write_csv(paths.accepted_audit, audit_headers, (_audit_row(row, names[row.source_key]) for row in accepted))
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

    barcode_counts = Counter(candidate.barcode for candidate in candidates if candidate.barcode)
    pos_counts = Counter(names[candidate.source_key].value for candidate in candidates if names[candidate.source_key].value)
    summary = BuildSummary(
        candidate_rows=len(candidates),
        accepted_rows=len(accepted),
        manual_review_rows=len(review),
        rejected_rows=0,
        duplicate_barcodes=sum(1 for _, count in barcode_counts.items() if count > 1),
        duplicate_pos_names=sum(1 for _, count in pos_counts.items() if count > 1),
        output_paths=paths,
    )
    _write_manifest(inputs, paths, summary)
    _write_summary(paths.summary, summary, run_dir)
    return BuildResult(run_dir=run_dir, summary=summary)


def _write_manifest(inputs: BuildInputs, paths: OutputPaths, summary: BuildSummary) -> None:
    artifact_paths = [
        paths.final_import,
        paths.manual_review,
        paths.accepted_audit,
        paths.rejected_audit,
        paths.naming_audit,
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
            },
        },
        "counts": {
            "candidate_rows": summary.candidate_rows,
            "accepted_rows": summary.accepted_rows,
            "manual_review_rows": summary.manual_review_rows,
            "duplicate_barcodes": summary.duplicate_barcodes,
            "duplicate_pos_names": summary.duplicate_pos_names,
        },
        "artifacts": {
            path.name: {"sha256": _sha256(path)}
            for path in artifact_paths
            if path.is_file()
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
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Lunchtab product import CSV.")
    parser.add_argument("--product-template", type=Path, required=True)
    parser.add_argument("--recipe-list", type=Path, required=True)
    parser.add_argument("--odin-inventory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=default_output_root())
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = build_product_import(
        BuildInputs(
            product_template_path=args.product_template,
            recipe_list_path=args.recipe_list,
            odin_inventory_path=args.odin_inventory,
            output_root=args.output_root,
        )
    )
    print(f"Wrote {result.summary.accepted_rows} row(s) to {result.summary.output_paths.final_import}")
