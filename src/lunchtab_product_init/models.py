from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


LUNCHTAB_TEMPLATE_HEADERS = (
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
)


@dataclass(frozen=True)
class ProductCandidate:
    source: str
    source_key: str
    item_name: str
    price: str
    barcode: str
    category: str
    stock: str = ""
    recipe_name: str = ""
    odin_name: str = ""
    confidence: str = "review"
    review_reason: str = ""


@dataclass(frozen=True)
class PosNameResult:
    value: str
    status: str
    reason: str
    normalized: str
    abbreviation_steps: tuple[str, ...]


@dataclass(frozen=True)
class BuildInputs:
    product_template_path: Path
    recipe_list_path: Path
    odin_inventory_path: Path
    output_root: Path


@dataclass(frozen=True)
class OutputPaths:
    final_import: Path
    manual_review: Path
    accepted_audit: Path
    rejected_audit: Path
    naming_audit: Path
    manifest: Path
    summary: Path


@dataclass(frozen=True)
class BuildSummary:
    candidate_rows: int
    accepted_rows: int
    manual_review_rows: int
    rejected_rows: int
    duplicate_barcodes: int
    duplicate_pos_names: int
    output_paths: OutputPaths


@dataclass(frozen=True)
class BuildResult:
    run_dir: Path
    summary: BuildSummary
