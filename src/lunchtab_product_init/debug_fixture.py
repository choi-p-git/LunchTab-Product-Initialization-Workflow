from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lunchtab_product_init.io import read_csv
from lunchtab_product_init.models import BuildInputs, LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.session_workflow import (
    ImportSession,
    SessionExportResult,
    SessionRow,
    apply_venue_profile,
    export_session,
    load_venue_profile,
    prepare_edit_review,
    run_pos_generation,
)

DebugStagePreset = Literal["step1", "step2", "step3", "step4", "step5", "step6"]

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_FIXTURE_DIR = PACKAGE_ROOT / "debug_fixtures" / "default"
DEBUG_OUTPUT_DIR = REPO_ROOT / "debug-output"
PROFILE_INFERENCE_OUTPUT_DIR = DEBUG_OUTPUT_DIR / "profile-inference"
STAGE_LABELS: dict[DebugStagePreset, str] = {
    "step1": "Step 1 Complete",
    "step2": "Step 2 Complete",
    "step3": "Step 3 Complete",
    "step4": "Step 4 Complete",
    "step5": "Step 5 Complete",
    "step6": "Step 6 Complete",
}


class DebugFixtureError(ValueError):
    pass


@dataclass(frozen=True)
class DebugFixturePaths:
    fixture_dir: Path
    manifest: Path
    product_template: Path
    recipe_list: Path
    generic_inventory: Path
    venue_profile: Path
    final_import: Path
    session_audit: Path


@dataclass(frozen=True)
class DebugStageResult:
    session: ImportSession
    result: SessionExportResult | None = None


def default_debug_output_root() -> Path:
    return DEBUG_OUTPUT_DIR


def default_fixture_paths(fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> DebugFixturePaths:
    return DebugFixturePaths(
        fixture_dir=fixture_dir,
        manifest=fixture_dir / "fixture-manifest.json",
        product_template=fixture_dir / "product_template.csv",
        recipe_list=fixture_dir / "recipe_list.csv",
        generic_inventory=fixture_dir / "generic_inventory.csv",
        venue_profile=fixture_dir / "venue_profile.json",
        final_import=fixture_dir / "final_import.csv",
        session_audit=fixture_dir / "session_audit.csv",
    )


def validate_debug_fixture(paths: DebugFixturePaths | None = None) -> DebugFixturePaths:
    paths = paths or default_fixture_paths()
    if not paths.manifest.exists():
        raise DebugFixtureError(f"Debug fixture manifest is missing: {paths.manifest}")
    payload = json.loads(paths.manifest.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise DebugFixtureError("Unsupported debug fixture manifest schema.")
    files = payload.get("files")
    if not isinstance(files, list):
        raise DebugFixtureError("Debug fixture manifest must contain a files list.")
    for entry in files:
        if not isinstance(entry, dict):
            raise DebugFixtureError("Debug fixture manifest has an invalid file entry.")
        name = str(entry.get("name") or "")
        expected_hash = str(entry.get("sha256") or "")
        if not name or not expected_hash:
            raise DebugFixtureError("Debug fixture manifest file entries require name and sha256.")
        path = paths.fixture_dir / name
        if not path.exists():
            raise DebugFixtureError(f"Debug fixture file is missing: {path}")
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise DebugFixtureError(
                f"Debug fixture hash mismatch for {name}: expected {expected_hash}, got "
                f"{actual_hash}"
            )
    return paths


def build_debug_stage(
    stage: DebugStagePreset,
    *,
    fixture_paths: DebugFixturePaths | None = None,
    profile_path: Path | None = None,
    load_default_profile: bool = True,
    output_root: Path | None = None,
) -> DebugStageResult:
    paths = validate_debug_fixture(fixture_paths)
    profile = _selected_profile_path(paths, profile_path, load_default_profile)
    if stage == "step1":
        session = _parsed_session(paths)
    elif stage == "step2":
        session = _edit_review_session(paths)
    elif stage == "step3":
        session = run_pos_generation(_post_edit_session(paths))
    elif stage in {"step4", "step5", "step6"}:
        session = _final_session(paths)
    else:
        raise DebugFixtureError(f"Unsupported debug stage preset: {stage}")
    if profile is not None:
        session = apply_venue_profile(session, load_venue_profile(profile))
    if stage != "step6":
        return DebugStageResult(session=session)
    result = export_session(session, _build_inputs(paths, output_root or DEBUG_OUTPUT_DIR))
    return DebugStageResult(session=session, result=result)


def build_profile_edit_session(
    *,
    fixture_paths: DebugFixturePaths | None = None,
    profile_path: Path | None = None,
    load_default_profile: bool = True,
    row_limit: int = 25,
) -> ImportSession:
    paths = validate_debug_fixture(fixture_paths)
    profile = _selected_profile_path(paths, profile_path, load_default_profile)
    session = _profile_sample_session(paths, row_limit=row_limit)
    if profile is not None:
        session = apply_venue_profile(session, load_venue_profile(profile))
    return run_pos_generation(session)


def _selected_profile_path(
    paths: DebugFixturePaths, profile_path: Path | None, load_default_profile: bool
) -> Path | None:
    if profile_path is not None:
        return profile_path
    return paths.venue_profile if load_default_profile else None


def _parsed_session(paths: DebugFixturePaths) -> ImportSession:
    rows = []
    for index, row in enumerate(_audit_rows(paths), start=1):
        rows.append(
            SessionRow(
                row_id=row["RowId"] or f"row-{index}",
                candidate=_candidate_from_audit(row),
                old_category=row["OldCategory"],
                status="active",
                review_reason="",
                is_published=False,
                is_orderable=False,
            )
        )
    return ImportSession(headers=list(LUNCHTAB_TEMPLATE_HEADERS), rows=tuple(rows))


def _edit_review_session(paths: DebugFixturePaths) -> ImportSession:
    final_lookup = _final_lookup(paths)
    audit_rows = _audit_rows(paths)
    duplicate_names = _duplicate_names(audit_rows)
    rows = []
    categories = set()
    for row in audit_rows:
        final_row = _pop_final_for_audit_row(final_lookup, row)
        category = _category_from_final(final_row) or row["Category"] or row["OldCategory"]
        if category:
            categories.add(category)
        candidate = _candidate_from_audit(row, final_row=final_row, category=category)
        needs_review = _needs_inferred_review(row, candidate, category, duplicate_names)
        rows.append(
            SessionRow(
                row_id=row["RowId"],
                candidate=candidate,
                old_category=row["OldCategory"],
                category=category,
                status="needs_edit" if needs_review else "active",
                review_reason=_inferred_review_reason(row, candidate, category, duplicate_names),
                deleted_reason="",
                merge_target_row_id=row["MergeTargetRowId"],
                merge_transferred_barcodes=row["MergeTransferredBarcodes"],
                merge_target_barcode_before=row["MergeTargetBarcodeBefore"],
                merge_target_barcode_after=row["MergeTargetBarcodeAfter"],
                merge_action_timestamp=row["MergeActionTimestamp"],
                edited=_truthy(row["Edited"]),
                is_published=_truthy((final_row or {}).get("IsPublished", "")),
                is_orderable=_truthy((final_row or {}).get("IsOrderable", "")),
            )
        )
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=tuple(rows),
        category_names=tuple(sorted(categories, key=str.casefold)),
    )
    return prepare_edit_review(session)


def _post_edit_session(paths: DebugFixturePaths) -> ImportSession:
    session = _final_session(paths)
    rows = []
    for row in session.rows:
        if row.status == "deleted":
            rows.append(row)
        else:
            rows.append(
                SessionRow(
                    row_id=row.row_id,
                    candidate=row.candidate,
                    old_category=row.old_category,
                    category=row.category,
                    status="edit_complete",
                    edited=row.edited,
                    is_published=row.is_published,
                    is_orderable=row.is_orderable,
                )
            )
    return ImportSession(
        headers=session.headers,
        rows=tuple(rows),
        category_names=session.category_names,
        pos_preferences=session.pos_preferences,
    )


def _final_session(paths: DebugFixturePaths) -> ImportSession:
    final_lookup = _final_lookup(paths)
    rows = []
    categories = set()
    for audit_row in _audit_rows(paths):
        final_row = _pop_final_for_audit_row(final_lookup, audit_row)
        category = _category_from_final(final_row) or audit_row["Category"]
        if category:
            categories.add(category)
        status = "deleted" if audit_row["Status"] == "deleted" else "pos_ready"
        rows.append(
            SessionRow(
                row_id=audit_row["RowId"],
                candidate=_candidate_from_audit(audit_row, final_row=final_row, category=category),
                old_category=audit_row["OldCategory"],
                category=category,
                pos_name=(final_row or {}).get(
                    "BaseProductPosName", audit_row["BaseProductPosName"]
                ),
                status=status,
                review_reason="" if status != "deleted" else audit_row["ReviewReason"],
                deleted_reason=audit_row["DeletedReason"] if status == "deleted" else "",
                merge_target_row_id=audit_row["MergeTargetRowId"],
                merge_transferred_barcodes=audit_row["MergeTransferredBarcodes"],
                merge_target_barcode_before=audit_row["MergeTargetBarcodeBefore"],
                merge_target_barcode_after=audit_row["MergeTargetBarcodeAfter"],
                merge_action_timestamp=audit_row["MergeActionTimestamp"],
                edited=_truthy(audit_row["Edited"]),
                is_published=_truthy((final_row or {}).get("IsPublished", "")),
                is_orderable=_truthy((final_row or {}).get("IsOrderable", "")),
            )
        )
    return ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=tuple(rows),
        category_names=tuple(sorted(categories, key=str.casefold)),
    )


def _profile_sample_session(paths: DebugFixturePaths, *, row_limit: int) -> ImportSession:
    _headers, final_rows = read_csv(paths.final_import)
    rows = []
    categories = set()
    for index, final_row in enumerate(final_rows[:row_limit], start=1):
        category = _category_from_final(final_row)
        categories.add(category)
        rows.append(
            SessionRow(
                row_id=f"profile-row-{index}",
                candidate=ProductCandidate(
                    source="debug-final-import",
                    source_key=f"profile-source-{index}",
                    item_name=final_row["BaseProductName"],
                    price=final_row["Price"],
                    barcode=final_row["Barcodes"],
                    category=category,
                ),
                old_category=category,
                category=category,
                status="edit_complete",
                is_published=_truthy(final_row.get("IsPublished", "")),
                is_orderable=_truthy(final_row.get("IsOrderable", "")),
            )
        )
    return ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=tuple(rows),
        category_names=tuple(sorted(categories, key=str.casefold)),
    )


def _build_inputs(paths: DebugFixturePaths, output_root: Path) -> BuildInputs:
    return BuildInputs(
        product_template_path=paths.product_template,
        recipe_list_path=paths.recipe_list,
        generic_inventory_path=paths.generic_inventory,
        output_root=output_root,
    )


def _candidate_from_audit(
    row: dict[str, str],
    *,
    final_row: dict[str, str] | None = None,
    category: str | None = None,
) -> ProductCandidate:
    return ProductCandidate(
        source=row["Source"] or "debug-audit",
        source_key=row["SourceKey"],
        item_name=(final_row or {}).get("BaseProductName", row["ItemName"]),
        price=(final_row or {}).get("Price", row["Price"]),
        barcode=(final_row or {}).get("Barcodes", row["Barcode"]),
        category=category if category is not None else row["OldCategory"],
    )


def _audit_rows(paths: DebugFixturePaths) -> list[dict[str, str]]:
    _headers, rows = read_csv(paths.session_audit)
    return rows


def _final_lookup(paths: DebugFixturePaths) -> dict[str, deque[dict[str, str]]]:
    _headers, rows = read_csv(paths.final_import)
    lookup: dict[str, deque[dict[str, str]]] = defaultdict(deque)
    for row in rows:
        lookup[row["BaseProductName"].casefold()].append(row)
    return lookup


def _pop_final_for_audit_row(
    final_lookup: dict[str, deque[dict[str, str]]], audit_row: dict[str, str]
) -> dict[str, str] | None:
    rows = final_lookup.get(audit_row["ItemName"].casefold())
    if not rows:
        return None
    return rows.popleft()


def _category_from_final(row: dict[str, str] | None) -> str:
    if row is None:
        return ""
    return str(row.get("ProductCategories", "")).split(";", 1)[0].strip()


def _duplicate_names(rows: list[dict[str, str]]) -> set[str]:
    counts = Counter(
        row["ItemName"].casefold()
        for row in rows
        if row["Status"] != "deleted" and row["ItemName"].strip()
    )
    return {name for name, count in counts.items() if count > 1}


def _needs_inferred_review(
    audit_row: dict[str, str],
    candidate: ProductCandidate,
    category: str,
    duplicate_names: set[str],
) -> bool:
    return bool(
        audit_row["Status"] == "deleted"
        or _truthy(audit_row["Edited"])
        or audit_row["MergeTargetRowId"]
        or audit_row["ReviewReason"]
        or not candidate.item_name
        or not candidate.price
        or not candidate.barcode
        or not category
        or candidate.item_name.casefold() in duplicate_names
    )


def _inferred_review_reason(
    audit_row: dict[str, str],
    candidate: ProductCandidate,
    category: str,
    duplicate_names: set[str],
) -> str:
    reasons = []
    if audit_row["Status"] == "deleted":
        reasons.append("debug inferred deleted row review")
    if _truthy(audit_row["Edited"]):
        reasons.append("debug inferred edited row review")
    if audit_row["MergeTargetRowId"]:
        reasons.append("debug inferred merge review")
    if audit_row["ReviewReason"]:
        reasons.append(audit_row["ReviewReason"])
    if not candidate.item_name:
        reasons.append("missing item name")
    if not candidate.price:
        reasons.append("missing or invalid price")
    if not candidate.barcode:
        reasons.append("missing barcode")
    if not category:
        reasons.append("missing category")
    if candidate.item_name.casefold() in duplicate_names:
        reasons.append("duplicate name")
    return "; ".join(sorted(set(reason for reason in reasons if reason)))


def _truthy(value: str) -> bool:
    return str(value or "").strip().casefold() == "true"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
