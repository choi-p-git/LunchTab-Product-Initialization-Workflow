from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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


CategoryRole = Literal["food", "policy", "hybrid"]
SpendingPolicy = Literal["none", "non_exempt", "restrictable", "exempt"]
CategoryRuleType = Literal[
    "barcode",
    "item_name",
    "source_category",
    "phrase",
    "token",
]


@dataclass(frozen=True)
class CategoryCatalogEntry:
    name: str
    role: CategoryRole
    spending_policy: SpendingPolicy = "none"
    enabled: bool = True
    notes: str = ""


@dataclass(frozen=True)
class CategoryRule:
    rule_id: str
    rule_type: CategoryRuleType
    pattern: str
    categories: tuple[str, ...]
    confidence: int
    priority: int
    enabled: bool = True
    notes: str = ""


@dataclass(frozen=True)
class CategoryProfile:
    schema_version: int
    name: str
    catalog: tuple[CategoryCatalogEntry, ...]
    rules: tuple[CategoryRule, ...]


@dataclass(frozen=True)
class CategoryResult:
    categories: tuple[str, ...]
    restriction_policies: tuple[SpendingPolicy, ...]
    status: str
    confidence: int
    confidence_band: str
    reason: str
    matched_rules: tuple[str, ...]
    source_evidence: tuple[str, ...]


@dataclass(frozen=True)
class BuildInputs:
    product_template_path: Path
    recipe_list_path: Path
    output_root: Path
    odin_inventory_path: Path | None = None
    generic_inventory_path: Path | None = None
    category_profile_path: Path | None = None
    is_orderable: bool = False


@dataclass(frozen=True)
class OutputPaths:
    final_import: Path
    manual_review: Path
    zero_stock_review: Path
    accepted_audit: Path
    rejected_audit: Path
    naming_audit: Path
    category_audit: Path
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
    category_review_rows: int
    zero_stock_review_rows: int
    output_paths: OutputPaths


@dataclass(frozen=True)
class BuildResult:
    run_dir: Path
    summary: BuildSummary
