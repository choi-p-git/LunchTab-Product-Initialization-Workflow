from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from lunchtab_product_init.barcodes import duplicate_barcodes, format_barcodes, parse_barcodes
from lunchtab_product_init.io import write_csv
from lunchtab_product_init.models import BuildInputs, ProductCandidate
from lunchtab_product_init.naming import (
    ABBREVIATIONS,
    MAX_POS_NAME_LENGTH,
    duplicate_values,
    generate_pos_name,
    normalize_text,
)
from lunchtab_product_init.workflow import (
    CATEGORY_AUDIT_NAME,
    FINAL_OUTPUT_NAME,
    NAMING_AUDIT_NAME,
    merge_candidates,
    product_row,
    read_generic_inventory_candidates,
    read_lunchtab_template,
    read_odin_candidates,
    read_recipe_candidates,
)

RowStatus = Literal[
    "active",
    "deleted",
    "needs_edit",
    "edit_complete",
    "pos_ready",
    "pos_needs_review",
    "export_ready",
]
PriceFilterOperator = Literal["=", "<", ">", "<=", ">=", "range", "no_price", "any"]
StockFilterOperator = Literal["=", "<", ">", "<=", ">=", "range", "no_stock", "any"]
CategoryAssignmentFilter = Literal["any", "assigned", "unassigned"]
NameFilter = Literal["any", "duplicate_name"]

DELETED_AUDIT_NAME = "Deleted Product Audit.csv"
SESSION_AUDIT_NAME = "Session Review Audit.csv"
CORE_CATALOGUE_NAME = "Core Catalogue.csv"
POS_PROFILE_AUDIT_NAME = "POS Preference Profile.csv"
POS_NAME_STOP_WORDS = {"a", "an", "and", "of", "the", "with"}
POS_NAME_PHRASE_REPLACEMENTS = {("english", "muffin"): "Muff"}


@dataclass(frozen=True)
class PosNameAbbreviationPreference:
    value: str
    count: int = 1
    source_token_counts: tuple[int, ...] = ()
    override_lengths: tuple[int, ...] = ()
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class PosNameAcronymPreference:
    suffix_tokens: tuple[str, ...]
    span_length: int
    count: int = 1
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class PosNamePreferenceProfile:
    abbreviations: dict[str, str]
    abbreviation_options: dict[str, tuple[PosNameAbbreviationPreference, ...]] = field(
        default_factory=dict
    )
    acronym_patterns: tuple[PosNameAcronymPreference, ...] = ()
    spaced_overrides: int = 0
    compact_overrides: int = 0


@dataclass(frozen=True)
class VenueProfile:
    name: str
    category_names: tuple[str, ...]
    pos_preferences: PosNamePreferenceProfile


@dataclass(frozen=True)
class SessionRow:
    row_id: str
    candidate: ProductCandidate
    old_category: str = ""
    category: str = ""
    pos_name: str = ""
    status: RowStatus = "active"
    review_reason: str = ""
    deleted_reason: str = ""
    merge_target_row_id: str = ""
    merge_target_barcode_before: str = ""
    merge_target_barcode_after: str = ""
    merge_transferred_barcodes: str = ""
    merge_action_timestamp: str = ""
    edited: bool = False
    pos_overridden: bool = False
    is_published: bool = False
    is_orderable: bool = False
    core_catalogue: bool = False
    pos_name_before_override: str = ""
    pos_edit_distance: int = 0
    pos_character_delta: int = 0
    pos_spaces_changed: int = 0
    pos_token_changes: int = 0
    pos_active_edit_actions: int = 0
    pos_edit_effort: str = ""

    @property
    def item_name(self) -> str:
        return self.candidate.item_name

    @property
    def price(self) -> str:
        return self.candidate.price

    @property
    def barcode(self) -> str:
        return self.candidate.barcode


@dataclass(frozen=True)
class ImportSession:
    headers: list[str]
    rows: tuple[SessionRow, ...]
    category_names: tuple[str, ...] = ()
    pos_preferences: PosNamePreferenceProfile = field(
        default_factory=lambda: PosNamePreferenceProfile(abbreviations={})
    )

    @property
    def active_rows(self) -> tuple[SessionRow, ...]:
        return tuple(row for row in self.rows if row.status != "deleted")

    @property
    def deleted_rows(self) -> tuple[SessionRow, ...]:
        return tuple(row for row in self.rows if row.status == "deleted")

    @property
    def edit_queue(self) -> tuple[SessionRow, ...]:
        return tuple(
            row
            for row in self.rows
            if row.status == "needs_edit" or (row.status == "edit_complete" and row.review_reason)
        )

    @property
    def can_leave_edit_review(self) -> bool:
        return all(row.status != "needs_edit" for row in self.rows if row.status != "deleted")

    @property
    def can_leave_pos_review(self) -> bool:
        return all(row.status in {"pos_ready", "export_ready"} for row in self.active_rows)

    @property
    def can_export(self) -> bool:
        return validate_session_export_ready(self) == []


@dataclass(frozen=True)
class SessionOutputPaths:
    final_import: Path
    core_catalogue: Path
    category_audit: Path
    naming_audit: Path
    pos_profile_audit: Path
    session_audit: Path
    deleted_audit: Path
    manifest: Path
    summary: Path


@dataclass(frozen=True)
class SessionBuildSummary:
    parsed_rows: int
    exported_rows: int
    deleted_rows: int
    edited_rows: int
    category_count: int
    pos_overrides: int
    pos_light_edits: int
    pos_moderate_edits: int
    pos_heavy_overrides: int
    duplicate_barcodes: int
    duplicate_pos_names: int
    core_catalogue_rows: int
    output_paths: SessionOutputPaths


@dataclass(frozen=True)
class SessionExportResult:
    run_dir: Path
    summary: SessionBuildSummary


@dataclass(frozen=True)
class FinalReviewMetadata:
    parsed_rows: int
    active_rows: int
    deleted_rows: int
    edited_rows: int
    merge_rows: int
    pos_overrides: int
    published_rows: int
    orderable_rows: int
    core_catalogue_rows: int
    duplicate_barcodes: int
    duplicate_pos_names: int
    category_counts: tuple[tuple[str, int], ...]
    export_errors: tuple[str, ...]

    @property
    def export_ready(self) -> bool:
        return not self.export_errors


def parse_sources(inputs: BuildInputs) -> ImportSession:
    _require_single_inventory_source(inputs)
    headers = read_lunchtab_template(inputs.product_template_path)
    recipes = read_recipe_candidates(inputs.recipe_list_path)
    inventory = []
    if inputs.odin_inventory_path is not None:
        inventory.extend(read_odin_candidates(inputs.odin_inventory_path))
    if inputs.generic_inventory_path is not None:
        inventory.extend(read_generic_inventory_candidates(inputs.generic_inventory_path))
    candidates = merge_candidates(recipes, inventory)
    barcode_duplicates = duplicate_barcodes(candidate.barcode for candidate in candidates)
    rows = tuple(
        _session_row(
            index,
            candidate,
            barcode_duplicates,
            is_published=inputs.is_published,
            is_orderable=inputs.is_orderable,
        )
        for index, candidate in enumerate(candidates, start=1)
    )
    return ImportSession(headers=headers, rows=rows)


def _require_single_inventory_source(inputs: BuildInputs) -> None:
    if inputs.odin_inventory_path is not None and inputs.generic_inventory_path is not None:
        raise ValueError("Select either Odin inventory or generic inventory, not both.")


def add_category(session: ImportSession, name: str) -> ImportSession:
    cleaned = _clean_text(name)
    if not cleaned:
        return session
    categories = list(session.category_names)
    if cleaned not in categories:
        categories.append(cleaned)
    return replace(session, category_names=_sort_category_names(categories))


def filter_rows(
    session: ImportSession,
    *,
    keyword: str = "",
    name_filter: NameFilter | str = "any",
    old_category: str = "",
    barcode_filter: str = "",
    category_assignment: CategoryAssignmentFilter | str = "any",
    price_operator: PriceFilterOperator = "any",
    price_value: str = "",
    price_upper: str = "",
    min_price: str = "",
    max_price: str = "",
    stock_operator: StockFilterOperator = "any",
    stock_value: str = "",
    stock_upper: str = "",
    include_deleted: bool = False,
) -> tuple[SessionRow, ...]:
    keyword_norm = normalize_text(keyword)
    name_filter = _normalize_name_filter(name_filter)
    old_category_norm = normalize_text(old_category)
    barcode_norm = normalize_text(barcode_filter)
    category_assignment = _normalize_category_assignment_filter(category_assignment)
    price_operator = _normalize_price_operator(price_operator)
    stock_operator_text = str(stock_operator or "").strip().casefold()
    stock_operator = _normalize_stock_operator(stock_operator)
    if stock_operator_text in {"0", "zero", "zero stock"} and not stock_value:
        stock_value = "0"
    if min_price or max_price:
        price_operator = "range"
        price_value = min_price
        price_upper = max_price
    target_price = _decimal_or_none(price_value)
    upper_price = _decimal_or_none(price_upper)
    target_stock = _decimal_or_none(stock_value)
    upper_stock = _decimal_or_none(stock_upper)
    rows = session.rows if include_deleted else session.active_rows
    duplicate_names = _duplicate_item_names(rows) if name_filter == "duplicate_name" else set()
    filtered = []
    for row in rows:
        if keyword_norm and keyword_norm not in normalize_text(row.item_name):
            continue
        item_name_norm = normalize_text(row.item_name)
        if name_filter == "duplicate_name" and item_name_norm not in duplicate_names:
            continue
        if not _old_category_filter_matches(row.old_category, old_category_norm):
            continue
        if not _barcode_filter_matches(row.barcode, barcode_norm):
            continue
        if category_assignment == "assigned" and not row.category.strip():
            continue
        if category_assignment == "unassigned" and row.category.strip():
            continue
        price = _decimal_or_none(row.price)
        if not _price_matches(price, price_operator, target_price, upper_price):
            continue
        stock = _decimal_or_none(row.candidate.stock)
        if not _stock_matches(
            row.candidate.source,
            row.candidate.stock,
            stock,
            stock_operator,
            target_stock,
            upper_stock,
        ):
            continue
        filtered.append(row)
    if name_filter == "duplicate_name":
        filtered.sort(key=lambda row: normalize_text(row.item_name))
    return tuple(filtered)


def assign_category(session: ImportSession, row_ids: set[str], category: str) -> ImportSession:
    session = add_category(session, category)
    cleaned = _clean_text(category)
    return _refresh_after_category_assignment(
        replace(
            session,
            rows=tuple(
                replace(row, category=cleaned)
                if row.row_id in row_ids and row.status != "deleted"
                else row
                for row in session.rows
            ),
        ),
        row_ids,
    )


def _refresh_after_category_assignment(session: ImportSession, row_ids: set[str]) -> ImportSession:
    barcode_duplicates = duplicate_barcodes(row.barcode for row in session.active_rows)
    rows = []
    for row in session.rows:
        if row.row_id not in row_ids or row.status == "deleted":
            rows.append(row)
            continue
        reasons = _core_review_reasons(row.candidate, barcode_duplicates)
        if not row.category:
            reasons.append("missing category")
        if reasons:
            rows.append(
                replace(
                    row,
                    status="needs_edit",
                    review_reason="; ".join(sorted(set(reasons))),
                )
            )
        elif _is_unedited_operator_review(row):
            rows.append(replace(row, status="needs_edit", review_reason="operator review"))
        elif row.status == "active":
            rows.append(replace(row, review_reason=""))
        else:
            rows.append(replace(row, status="edit_complete", review_reason=""))
    return replace(
        session,
        rows=tuple(rows),
    )


def mark_for_edit(
    session: ImportSession, row_ids: set[str], reason: str = "operator review"
) -> ImportSession:
    return replace(
        session,
        rows=tuple(
            replace(
                row, status="needs_edit", review_reason=_append_reason(row.review_reason, reason)
            )
            if row.row_id in row_ids and row.status != "deleted"
            else row
            for row in session.rows
        ),
    )


def delete_rows(
    session: ImportSession, row_ids: set[str], reason: str = "operator deleted"
) -> ImportSession:
    return _refresh_after_delete(
        replace(
            session,
            rows=tuple(
                replace(row, status="deleted", deleted_reason=reason)
                if row.row_id in row_ids
                else row
                for row in session.rows
            ),
        )
    )


def _refresh_after_delete(session: ImportSession) -> ImportSession:
    rows = []
    barcode_duplicates = duplicate_barcodes(row.barcode for row in session.active_rows)
    pos_started = any(row.pos_name for row in session.active_rows)
    for row in session.rows:
        if row.status == "deleted":
            rows.append(row)
            continue
        edit_reasons = _core_review_reasons(row.candidate, barcode_duplicates)
        if not row.category and row.status != "active":
            edit_reasons.append("missing category")
        pos_reasons = (
            validate_pos_name(row.pos_name, row.row_id, session.rows) if pos_started else []
        )
        if _is_unedited_operator_review(row):
            reasons = sorted(set((*edit_reasons, *pos_reasons, row.review_reason)))
            rows.append(replace(row, status="needs_edit", review_reason="; ".join(reasons)))
            continue
        reasons = sorted(set((*edit_reasons, *pos_reasons)))
        if edit_reasons:
            status: RowStatus = "needs_edit"
        elif pos_started:
            status = "pos_needs_review" if pos_reasons else "pos_ready"
        elif row.status == "active":
            status = "active"
        else:
            status = "edit_complete"
        rows.append(replace(row, status=status, review_reason="; ".join(reasons)))
    return replace(session, rows=tuple(rows))


def merge_rows(
    session: ImportSession, target_row_id: str, source_row_ids: set[str]
) -> ImportSession:
    source_row_ids = {row_id for row_id in source_row_ids if row_id != target_row_id}
    if not source_row_ids:
        raise ValueError("Select at least one source row to merge.")
    target = _row_by_id(session, target_row_id)
    if target is None or target.status == "deleted":
        raise ValueError("Select an active target row for merge.")
    source_rows = [
        row for row in session.rows if row.row_id in source_row_ids and row.status != "deleted"
    ]
    if len(source_rows) != len(source_row_ids):
        raise ValueError("All source rows selected for merge must be active.")

    target_barcode_before = target.barcode
    merge_action_timestamp = datetime.now().isoformat(timespec="seconds")
    merged_barcode = format_barcodes(
        (
            *parse_barcodes(target.barcode),
            *(barcode for row in source_rows for barcode in parse_barcodes(row.barcode)),
        )
    )
    rows = []
    for row in session.rows:
        if row.row_id == target_row_id:
            rows.append(
                replace(
                    row,
                    candidate=replace(row.candidate, barcode=merged_barcode),
                    edited=True,
                    review_reason=_append_reason(
                        row.review_reason, "merged barcode from selected row"
                    ),
                )
            )
        elif row.row_id in source_row_ids:
            rows.append(
                replace(
                    row,
                    status="deleted",
                    deleted_reason=f"merged into {target_row_id}",
                    merge_target_row_id=target_row_id,
                    merge_target_barcode_before=target_barcode_before,
                    merge_target_barcode_after=merged_barcode,
                    merge_transferred_barcodes=format_barcodes(parse_barcodes(row.barcode)),
                    merge_action_timestamp=merge_action_timestamp,
                    review_reason=_append_reason(
                        row.review_reason, f"barcode transferred to {target_row_id}"
                    ),
                )
            )
        else:
            rows.append(row)
    return _refresh_barcode_review(replace(session, rows=tuple(rows)))


def no_barcode_rows(session: ImportSession) -> tuple[SessionRow, ...]:
    return tuple(row for row in session.active_rows if not parse_barcodes(row.barcode))


def duplicate_name_edit_rows(session: ImportSession) -> tuple[SessionRow, ...]:
    rows = session.edit_queue
    duplicate_names = _duplicate_item_names(rows)
    return tuple(
        sorted(
            (
                row
                for row in rows
                if normalize_text(row.item_name) in duplicate_names
                or "duplicate name" in row.review_reason
            ),
            key=lambda row: (normalize_text(row.item_name), row.item_name.casefold(), row.row_id),
        )
    )


def prepare_edit_review(session: ImportSession) -> ImportSession:
    duplicate_names = _duplicate_item_names(session.active_rows)
    rows = []
    for row in session.rows:
        if row.status == "deleted":
            rows.append(row)
            continue
        reasons = [
            reason for reason in _reason_parts(row.review_reason) if reason != "duplicate name"
        ]
        if normalize_text(row.item_name) in duplicate_names:
            reasons.append("duplicate name")
        if reasons:
            rows.append(
                replace(
                    row,
                    status="needs_edit" if row.status == "active" else row.status,
                    review_reason="; ".join(sorted(set(reasons))),
                )
            )
        elif row.status == "needs_edit":
            rows.append(replace(row, status="edit_complete", review_reason=""))
        else:
            rows.append(replace(row, review_reason=""))
    return replace(session, rows=tuple(rows))


def validate_edit_name_for_row(session: ImportSession, row_id: str, item_name: str) -> list[str]:
    row = _row_by_id(session, row_id)
    if row is None:
        return ["select a row"]
    cleaned = _clean_text(item_name)
    if not cleaned:
        return []
    normalized = normalize_text(cleaned)
    same_normalized_name = normalized == normalize_text(row.item_name)
    if same_normalized_name:
        return []
    if any(
        other.row_id != row_id
        and other.status != "deleted"
        and normalize_text(other.item_name) == normalized
        for other in session.rows
    ):
        return ["duplicate item name"]
    return []


def save_edit(
    session: ImportSession,
    row_id: str,
    *,
    item_name: str,
    price: str,
    barcode: str,
    category: str,
) -> ImportSession:
    category = _clean_text(category)
    session = add_category(session, category)
    updated_rows = []
    name_changed = False
    for row in session.rows:
        if row.row_id != row_id:
            updated_rows.append(row)
            continue
        cleaned_name = _clean_text(item_name)
        name_changed = cleaned_name != row.item_name
        candidate = replace(
            row.candidate,
            item_name=cleaned_name,
            price=_clean_text(price),
            barcode=format_barcodes(parse_barcodes(barcode)),
            category=category,
        )
        reasons = _core_review_reasons(candidate, set())
        if not category:
            reasons.append("missing category")
        updated_rows.append(
            replace(
                row,
                candidate=candidate,
                category=category,
                status="needs_edit" if reasons else "edit_complete",
                review_reason="; ".join(sorted(set(reasons))),
                edited=True,
            )
        )
    return _refresh_barcode_review(
        replace(session, rows=tuple(updated_rows)),
        saved_row_id=row_id,
        saved_name_changed=name_changed,
    )


def next_edit_row(session: ImportSession) -> SessionRow | None:
    for row in session.rows:
        if row.status == "needs_edit":
            return row
    return None


def run_pos_generation(session: ImportSession) -> ImportSession:
    final_names = []
    generated = []
    for row in session.rows:
        if row.status == "deleted":
            generated.append(row)
            continue
        if row.pos_name:
            generated.append(row)
            final_names.append(row.pos_name)
            continue
        result = generate_pos_name_with_preferences(row.item_name, session.pos_preferences)
        generated.append(replace(row, pos_name=result.value))
        final_names.append(result.value)
    duplicates = duplicate_values(final_names)
    refreshed = []
    for row in generated:
        if row.status == "deleted":
            refreshed.append(row)
            continue
        reasons = validate_pos_name(row.pos_name, row.row_id, tuple(generated))
        status: RowStatus = "pos_ready" if not reasons else "pos_needs_review"
        refreshed.append(replace(row, status=status, review_reason="; ".join(reasons)))
    if duplicates:
        refreshed = [
            replace(
                row,
                status="pos_needs_review",
                review_reason=_append_reason(row.review_reason, "duplicate POS name"),
            )
            if row.pos_name in duplicates and row.status != "deleted"
            else row
            for row in refreshed
        ]
    return replace(session, rows=tuple(refreshed))


def replace_pos_name(session: ImportSession, row_id: str, pos_name: str) -> ImportSession:
    cleaned = _clean_text(pos_name)
    rows = []
    target: SessionRow | None = None
    for row in session.rows:
        if row.row_id == row_id:
            target = row
            break
    preferences = session.pos_preferences
    for row in session.rows:
        if row.row_id == row_id:
            metrics = _pos_name_edit_metrics(row.pos_name, cleaned)
            candidate = replace(
                row,
                pos_name=cleaned,
                pos_overridden=True,
                pos_name_before_override=row.pos_name,
                pos_edit_distance=metrics["edit_distance"],
                pos_character_delta=metrics["character_delta"],
                pos_spaces_changed=metrics["spaces_changed"],
                pos_token_changes=metrics["token_changes"],
                pos_active_edit_actions=metrics["active_edit_actions"],
                pos_edit_effort=metrics["effort"],
            )
        else:
            candidate = row
        rows.append(candidate)
    if target is not None and cleaned and not validate_pos_name(cleaned, row_id, tuple(rows)):
        preferences = learn_pos_preferences(preferences, target.item_name, cleaned)
    session = replace(session, rows=tuple(rows), pos_preferences=preferences)
    return _refresh_pos_status(session)


def validate_final_review_edit(
    session: ImportSession,
    row_id: str,
    *,
    item_name: str,
    price: str,
    barcode: str,
    category: str,
    pos_name: str,
    is_published: bool = False,
    is_orderable: bool = False,
    core_catalogue: bool = False,
) -> list[str]:
    row = _row_by_id(session, row_id)
    if row is None or row.status == "deleted":
        return ["row is not available for final review edit"]
    cleaned_name = _clean_text(item_name)
    cleaned_category = _clean_text(category)
    cleaned_pos_name = _clean_text(pos_name)
    candidate = replace(
        row.candidate,
        item_name=cleaned_name,
        price=_clean_text(price),
        barcode=format_barcodes(parse_barcodes(barcode)),
        category=cleaned_category,
    )
    proposed_rows = tuple(
        replace(
            current,
            candidate=candidate,
            category=cleaned_category,
            pos_name=cleaned_pos_name,
        )
        if current.row_id == row_id
        else current
        for current in session.rows
    )
    barcode_duplicates = duplicate_barcodes(
        current.barcode for current in proposed_rows if current.status != "deleted"
    )
    reasons = _core_review_reasons(candidate, barcode_duplicates)
    if not cleaned_category:
        reasons.append("missing category")
    reasons.extend(validate_pos_name(cleaned_pos_name, row_id, proposed_rows))
    reasons.extend(validate_edit_name_for_row(session, row_id, cleaned_name))
    return sorted(set(reasons))


def save_final_review_edit(
    session: ImportSession,
    row_id: str,
    *,
    item_name: str,
    price: str,
    barcode: str,
    category: str,
    pos_name: str,
    is_published: bool = False,
    is_orderable: bool = False,
    core_catalogue: bool = False,
) -> ImportSession:
    reasons = validate_final_review_edit(
        session,
        row_id,
        item_name=item_name,
        price=price,
        barcode=barcode,
        category=category,
        pos_name=pos_name,
        is_published=is_published,
        is_orderable=is_orderable,
        core_catalogue=core_catalogue,
    )
    if reasons:
        raise ValueError("; ".join(reasons))
    cleaned_category = _clean_text(category)
    session = add_category(session, cleaned_category)
    rows = []
    for row in session.rows:
        if row.row_id != row_id:
            rows.append(row)
            continue
        candidate = replace(
            row.candidate,
            item_name=_clean_text(item_name),
            price=_clean_text(price),
            barcode=format_barcodes(parse_barcodes(barcode)),
            category=cleaned_category,
        )
        rows.append(
            replace(
                row,
                candidate=candidate,
                category=cleaned_category,
                pos_name=_clean_text(pos_name),
                status="pos_ready",
                review_reason="",
                edited=True,
                is_published=is_published,
                is_orderable=is_orderable,
                core_catalogue=core_catalogue,
            )
        )
    return replace(session, rows=tuple(rows))


def validate_pos_name(pos_name: str, row_id: str, rows: tuple[SessionRow, ...]) -> list[str]:
    reasons = []
    if not pos_name:
        reasons.append("missing POS name")
    if len(pos_name) > MAX_POS_NAME_LENGTH:
        reasons.append("POS name is longer than 15 characters")
    duplicates = [
        row.row_id
        for row in rows
        if row.status != "deleted" and row.pos_name and row.pos_name == pos_name
    ]
    if len(duplicates) > 1 and row_id in duplicates:
        reasons.append("duplicate POS name")
    return reasons


def validate_pos_name_for_row(session: ImportSession, row_id: str, pos_name: str) -> list[str]:
    cleaned = _clean_text(pos_name)
    rows = tuple(
        replace(row, pos_name=cleaned) if row.row_id == row_id and row.status != "deleted" else row
        for row in session.rows
    )
    return validate_pos_name(cleaned, row_id, rows)


def suggest_pos_names(session: ImportSession, row_id: str) -> tuple[str, ...]:
    row = _row_by_id(session, row_id)
    if row is None:
        return ()
    base = generate_pos_name(row.item_name).value
    primary = _primary_pos_name_candidates(row.item_name, session.pos_preferences)
    preferred = _preferred_pos_name_candidates(row.item_name, session.pos_preferences)
    alternates = _secondary_pos_name_candidates(row.item_name, session.pos_preferences)
    condensed = _condensed_pos_name_candidates(row.item_name, session.pos_preferences)
    compact = "".join(token[:4].title() for token in normalize_text(row.item_name).split())
    suggestions = []
    for value in (
        *primary[:2],
        *alternates[:1],
        *preferred,
        *condensed[:2],
        *alternates[1:],
        *condensed[2:],
        base,
        compact[:MAX_POS_NAME_LENGTH],
    ):
        if (
            value
            and value not in suggestions
            and not validate_pos_name_for_row(session, row_id, value)
        ):
            suggestions.append(value)
    return tuple(suggestions[:3])


def filter_pos_rows(session: ImportSession, reason_filter: str = "") -> tuple[SessionRow, ...]:
    normalized = normalize_text(reason_filter)
    if normalized in {"", "any"}:
        return session.active_rows
    if normalized in {"needs review", "review", "requires attention", "attention"}:
        return tuple(row for row in session.active_rows if row.status == "pos_needs_review")
    return tuple(
        row
        for row in session.active_rows
        if normalized in normalize_text(row.review_reason)
        or normalized in normalize_text(row.status.replace("_", " "))
    )


def filter_final_rows(
    session: ImportSession,
    *,
    keyword: str = "",
    flag_filter: str = "",
) -> tuple[SessionRow, ...]:
    normalized_keyword = normalize_text(keyword)
    normalized_flag = normalize_text(flag_filter)
    rows = ordered_final_session_rows(session)
    if normalized_keyword:
        rows = tuple(
            row
            for row in rows
            if any(
                normalized_keyword in normalize_text(value)
                for value in (
                    row.item_name,
                    row.pos_name,
                    row.price,
                    row.barcode,
                    row.category,
                    row.review_reason,
                )
            )
        )
    if normalized_flag in {"published", "published rows"}:
        return tuple(row for row in rows if row.is_published)
    if normalized_flag in {"unpublished", "not published"}:
        return tuple(row for row in rows if not row.is_published)
    if normalized_flag in {"orderable", "orderable rows"}:
        return tuple(row for row in rows if row.is_orderable)
    if normalized_flag in {"not orderable", "not orderable rows"}:
        return tuple(row for row in rows if not row.is_orderable)
    if normalized_flag in {"core catalogue", "core catalog", "core"}:
        return tuple(row for row in rows if row.core_catalogue)
    if normalized_flag in {"not core catalogue", "not core catalog"}:
        return tuple(row for row in rows if not row.core_catalogue)
    return rows


def generate_pos_name_with_preferences(item_name: str, preferences: PosNamePreferenceProfile):
    if not preferences.abbreviations and not preferences.abbreviation_options:
        return generate_pos_name(item_name)
    candidates = _preferred_pos_name_candidates(item_name, preferences)
    if candidates:
        base = generate_pos_name(item_name)
        return replace(
            base,
            value=candidates[0],
            status="ok",
            reason="",
            abbreviation_steps=(*base.abbreviation_steps, "preferences=" + candidates[0]),
        )
    return generate_pos_name(item_name)


def learn_pos_preferences(
    preferences: PosNamePreferenceProfile, item_name: str, override: str
) -> PosNamePreferenceProfile:
    tokens = _meaningful_pos_tokens(item_name)
    override_tokens = [token for token in override.replace("-", " ").split() if token]
    abbreviations = dict(preferences.abbreviations)
    options = {token: tuple(values) for token, values in preferences.abbreviation_options.items()}
    acronym_patterns = preferences.acronym_patterns
    source_token_count = len(tokens)
    override_length = len(_clean_text(override))
    source_index = 0
    override_index = 0
    while source_index < len(tokens) and override_index < len(override_tokens):
        target = override_tokens[override_index]
        acronym_span = _matching_acronym_span(tokens, source_index, target)
        if acronym_span is not None:
            acronym_patterns = _record_acronym_preference(
                acronym_patterns,
                suffix_tokens=tuple(tokens[source_index + 1 : source_index + acronym_span]),
                span_length=acronym_span,
                example=_clean_text(override),
            )
            source_index += acronym_span
            override_index += 1
            continue
        source = tokens[source_index]
        if source and target:
            cleaned_target = _clean_text(target)
            abbreviations[source] = cleaned_target
            options[source] = _record_abbreviation_preference(
                options.get(source, ()),
                cleaned_target,
                source_token_count=source_token_count,
                override_length=override_length,
                example=_clean_text(override),
            )
        source_index += 1
        override_index += 1
    return PosNamePreferenceProfile(
        abbreviations=abbreviations,
        abbreviation_options=options,
        acronym_patterns=acronym_patterns,
        spaced_overrides=preferences.spaced_overrides + (1 if len(override_tokens) > 1 else 0),
        compact_overrides=preferences.compact_overrides + (1 if len(override_tokens) <= 1 else 0),
    )


def ordered_final_session_rows(session: ImportSession) -> tuple[SessionRow, ...]:
    return tuple(
        sorted(
            session.active_rows,
            key=lambda row: (row.category.casefold(), row.item_name.casefold(), row.row_id),
        )
    )


def final_rows(session: ImportSession) -> list[dict[str, str]]:
    rows = []
    for row in ordered_final_session_rows(session):
        errors = validate_export_ready(row)
        if errors:
            raise ValueError(f"Row {row.row_id} is not export-ready: {', '.join(errors)}")
        rows.append(
            product_row(
                session.headers,
                replace(row.candidate, category=row.category),
                row.pos_name,
                _category_result(row.category),
                row.is_published,
                row.is_orderable,
            )
        )
    return rows


def core_catalogue_rows(session: ImportSession) -> list[dict[str, str]]:
    marked = replace(
        session,
        rows=tuple(row for row in session.rows if row.core_catalogue and row.status != "deleted"),
    )
    return final_rows(marked)


def export_session(
    session: ImportSession,
    inputs: BuildInputs,
) -> SessionExportResult:
    if not session.can_export:
        raise ValueError("All active rows must be complete before export.")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = inputs.output_root / timestamp
    paths = SessionOutputPaths(
        final_import=run_dir / FINAL_OUTPUT_NAME,
        core_catalogue=run_dir / CORE_CATALOGUE_NAME,
        category_audit=run_dir / CATEGORY_AUDIT_NAME,
        naming_audit=run_dir / NAMING_AUDIT_NAME,
        pos_profile_audit=run_dir / POS_PROFILE_AUDIT_NAME,
        session_audit=run_dir / SESSION_AUDIT_NAME,
        deleted_audit=run_dir / DELETED_AUDIT_NAME,
        manifest=run_dir / "run-manifest.json",
        summary=run_dir / "run-summary.md",
    )
    write_csv(paths.final_import, session.headers, final_rows(session))
    write_csv(paths.core_catalogue, session.headers, core_catalogue_rows(session))
    write_csv(paths.category_audit, _category_audit_headers(), _category_audit_rows(session))
    write_csv(paths.naming_audit, _naming_audit_headers(), _naming_audit_rows(session))
    write_csv(
        paths.pos_profile_audit,
        _pos_profile_audit_headers(),
        _pos_profile_audit_rows(session.pos_preferences),
    )
    write_csv(paths.session_audit, _session_audit_headers(), _session_audit_rows(session))
    write_csv(
        paths.deleted_audit, _session_audit_headers(), _session_audit_rows(session.deleted_rows)
    )
    summary = _summary(session, paths)
    _write_manifest(inputs, session, paths, summary)
    _write_summary(paths.summary, summary, run_dir)
    return SessionExportResult(run_dir=run_dir, summary=summary)


def save_venue_profile(
    session: ImportSession, path: Path, *, name: str = "Venue Product Import Profile"
) -> None:
    payload = {
        "schema_version": 2,
        "name": name,
        "categories": list(session.category_names),
        "pos_name_preferences": session.pos_preferences.abbreviations,
        "pos_name_preference_rules": _pos_preference_rules_payload(session.pos_preferences),
        "pos_name_acronym_rules": _pos_acronym_rules_payload(session.pos_preferences),
        "pos_name_style": {
            "spaced_overrides": session.pos_preferences.spaced_overrides,
            "compact_overrides": session.pos_preferences.compact_overrides,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_venue_profile(path: Path) -> VenueProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Venue profile must be a JSON object.")
    schema_version = payload.get("schema_version")
    if schema_version != 2:
        raise ValueError(f"Unsupported venue profile schema version: {schema_version!r}.")
    categories = payload.get("categories", [])
    preferences = payload.get("pos_name_preferences", {})
    preference_rules = payload.get("pos_name_preference_rules", {})
    acronym_rules = payload.get("pos_name_acronym_rules", [])
    preference_style = payload.get("pos_name_style", {})
    if not isinstance(categories, list):
        raise ValueError("Venue profile categories must be a list.")
    if not isinstance(preferences, dict):
        raise ValueError("Venue profile POS name preferences must be an object.")
    if not isinstance(preference_rules, dict):
        raise ValueError("Venue profile POS name preference rules must be an object.")
    if not isinstance(acronym_rules, list):
        raise ValueError("Venue profile POS name acronym rules must be a list.")
    if not isinstance(preference_style, dict):
        raise ValueError("Venue profile POS name style must be an object.")
    abbreviations = {
        _clean_text(str(token)).casefold(): _clean_text(str(abbreviation))
        for token, abbreviation in preferences.items()
        if _clean_text(str(token)) and _clean_text(str(abbreviation))
    }
    abbreviation_options = _load_pos_preference_rules(preference_rules)
    if not abbreviation_options:
        abbreviation_options = {
            token: (PosNameAbbreviationPreference(value=abbreviation),)
            for token, abbreviation in abbreviations.items()
        }
    return VenueProfile(
        name=_clean_text(str(payload.get("name") or "Venue Product Import Profile")),
        category_names=tuple(_dedupe_cleaned(str(category) for category in categories)),
        pos_preferences=PosNamePreferenceProfile(
            abbreviations=abbreviations,
            abbreviation_options=abbreviation_options,
            acronym_patterns=_load_pos_acronym_rules(acronym_rules),
            spaced_overrides=_positive_int(preference_style.get("spaced_overrides")),
            compact_overrides=_positive_int(preference_style.get("compact_overrides")),
        ),
    )


def apply_venue_profile(session: ImportSession, profile: VenueProfile) -> ImportSession:
    return replace(
        session,
        category_names=tuple(_dedupe_cleaned((*profile.category_names, *session.category_names))),
        pos_preferences=_merge_pos_preferences(session.pos_preferences, profile.pos_preferences),
    )


def validate_export_ready(row: SessionRow) -> list[str]:
    reasons = _core_review_reasons(row.candidate, set())
    if not row.category:
        reasons.append("missing category")
    if not row.pos_name:
        reasons.append("missing POS name")
    if len(row.pos_name) > MAX_POS_NAME_LENGTH:
        reasons.append("POS name is longer than 15 characters")
    return sorted(set(reasons))


def validate_session_export_ready(session: ImportSession) -> list[str]:
    barcode_duplicates = duplicate_barcodes(row.barcode for row in session.active_rows)
    pos_duplicates = duplicate_values(row.pos_name for row in session.active_rows if row.pos_name)
    errors = []
    for row in session.active_rows:
        reasons = validate_export_ready(row)
        if any(barcode.casefold() in barcode_duplicates for barcode in parse_barcodes(row.barcode)):
            reasons.append("duplicate barcode")
        if row.pos_name in pos_duplicates:
            reasons.append("duplicate POS name")
        if reasons:
            errors.append(f"{row.row_id}: {', '.join(sorted(set(reasons)))}")
    return errors


def final_review_metadata(session: ImportSession) -> FinalReviewMetadata:
    category_counts = Counter(row.category or "(missing)" for row in session.active_rows)
    barcode_duplicates = duplicate_barcodes(row.barcode for row in session.active_rows)
    pos_duplicates = duplicate_values(row.pos_name for row in session.active_rows if row.pos_name)
    return FinalReviewMetadata(
        parsed_rows=len(session.rows),
        active_rows=len(session.active_rows),
        deleted_rows=len(session.deleted_rows),
        edited_rows=sum(1 for row in session.rows if row.edited),
        merge_rows=sum(
            1 for row in session.deleted_rows if row.deleted_reason.startswith("merged into ")
        ),
        pos_overrides=sum(1 for row in session.rows if row.pos_overridden),
        published_rows=sum(1 for row in session.active_rows if row.is_published),
        orderable_rows=sum(1 for row in session.active_rows if row.is_orderable),
        core_catalogue_rows=sum(1 for row in session.active_rows if row.core_catalogue),
        duplicate_barcodes=len(barcode_duplicates),
        duplicate_pos_names=len(pos_duplicates),
        category_counts=tuple(sorted(category_counts.items(), key=lambda item: item[0].casefold())),
        export_errors=tuple(validate_session_export_ready(session)),
    )


def _session_row(
    index: int,
    candidate: ProductCandidate,
    barcode_duplicates: set[str],
    *,
    is_published: bool = False,
    is_orderable: bool = False,
) -> SessionRow:
    reasons = _core_review_reasons(candidate, barcode_duplicates)
    status: RowStatus = "active" if candidate.item_name and candidate.price else "needs_edit"
    return SessionRow(
        row_id=f"row-{index}",
        candidate=candidate,
        old_category=candidate.category,
        status=status if not reasons else "needs_edit",
        review_reason="; ".join(reasons),
        is_published=is_published,
        is_orderable=is_orderable,
    )


def _core_review_reasons(candidate: ProductCandidate, barcode_duplicates: set[str]) -> list[str]:
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
    return reasons


def _refresh_barcode_review(
    session: ImportSession,
    *,
    saved_row_id: str | None = None,
    saved_name_changed: bool = False,
) -> ImportSession:
    duplicates = duplicate_barcodes(row.barcode for row in session.active_rows)
    duplicate_names = _duplicate_item_names(session.active_rows)
    rows = []
    for row in session.rows:
        if row.status == "deleted":
            rows.append(row)
            continue
        reasons = _core_review_reasons(row.candidate, duplicates)
        if not row.category:
            reasons.append("missing category")
        duplicate_name = normalize_text(row.item_name) in duplicate_names
        duplicate_name_review_approved = (
            duplicate_name and row.row_id == saved_row_id and not saved_name_changed and row.edited
        )
        duplicate_name_already_approved = (
            duplicate_name
            and row.edited
            and "duplicate name" not in _reason_parts(row.review_reason)
            and row.row_id != saved_row_id
        )
        if (
            duplicate_name
            and not duplicate_name_review_approved
            and not duplicate_name_already_approved
        ):
            reasons.append("duplicate name")
        if not reasons and _is_unedited_operator_review(row):
            rows.append(row)
            continue
        status: RowStatus = "needs_edit" if reasons else "edit_complete"
        rows.append(replace(row, status=status, review_reason="; ".join(sorted(set(reasons)))))
    return replace(session, rows=tuple(rows))


def _is_unedited_operator_review(row: SessionRow) -> bool:
    return row.status == "needs_edit" and not row.edited and "operator review" in row.review_reason


def _refresh_pos_status(session: ImportSession) -> ImportSession:
    rows = []
    for row in session.rows:
        if row.status == "deleted":
            rows.append(row)
            continue
        reasons = validate_pos_name(row.pos_name, row.row_id, session.rows)
        status: RowStatus = "pos_ready" if not reasons else "pos_needs_review"
        rows.append(replace(row, status=status, review_reason="; ".join(reasons)))
    return replace(session, rows=tuple(rows))


def _preferred_pos_name_candidates(
    item_name: str, preferences: PosNamePreferenceProfile
) -> tuple[str, ...]:
    tokens = _meaningful_pos_tokens(item_name)
    if not tokens:
        return ()
    choice_sequences = _pos_choice_sequences(tokens, preferences)
    scored_candidates = []
    for token_choices in choice_sequences:
        for choice_group in itertools.product(*token_choices):
            values = [value for value, _score in choice_group]
            token_score = sum(score for _value, score in choice_group)
            for candidate, style_score in _format_pos_candidates(values, preferences):
                scored_candidates.append(
                    (candidate, token_score + style_score + _length_score(candidate))
                )
    ordered = sorted(
        scored_candidates, key=lambda item: (-item[1], len(item[0]), item[0].casefold())
    )
    candidates = []
    for candidate, _score in ordered:
        if len(candidate) > MAX_POS_NAME_LENGTH or candidate in candidates:
            continue
        candidates.append(candidate)
    return tuple(candidates[:8])


def _primary_pos_name_candidates(
    item_name: str, preferences: PosNamePreferenceProfile
) -> tuple[str, ...]:
    tokens = _meaningful_pos_tokens(item_name)
    if not tokens:
        return ()
    values = []
    token_score = 0
    for token in tokens:
        choices = _pos_token_choices(token, preferences, len(tokens))
        if not choices:
            values.append(_title_token(token))
            continue
        value, score = choices[0]
        values.append(value)
        token_score += score
    scored_candidates = []
    for candidate, style_score in _format_pos_candidates(values, preferences):
        if len(candidate) <= MAX_POS_NAME_LENGTH:
            scored_candidates.append(
                (candidate, token_score + style_score + _length_score(candidate))
            )
    ordered = sorted(
        scored_candidates,
        key=lambda item: (-item[1], len(item[0]), item[0].casefold()),
    )
    candidates = []
    for candidate, _score in ordered:
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _secondary_pos_name_candidates(
    item_name: str, preferences: PosNamePreferenceProfile
) -> tuple[str, ...]:
    tokens = _meaningful_pos_tokens(item_name)
    if not tokens:
        return ()
    primary_values = []
    token_choice_sets = []
    for token in tokens:
        choices = _pos_token_choices(token, preferences, len(tokens))
        token_choice_sets.append(choices)
        primary_values.append(choices[0][0] if choices else _title_token(token))
    scored_candidates = []
    for index, choices in enumerate(token_choice_sets):
        if len(choices) < 2:
            continue
        values = [*primary_values]
        values[index] = choices[1][0]
        token_score = sum(
            choices[1][1] if token_index == index and choices else token_choices[0][1]
            for token_index, token_choices in enumerate(token_choice_sets)
        )
        for candidate, style_score in _format_pos_candidates(values, preferences):
            scored_candidates.append(
                (candidate, token_score + style_score + _length_score(candidate))
            )
    ordered = sorted(
        scored_candidates, key=lambda item: (-item[1], len(item[0]), item[0].casefold())
    )
    candidates = []
    for candidate, _score in ordered:
        if len(candidate) > MAX_POS_NAME_LENGTH or candidate in candidates:
            continue
        candidates.append(candidate)
    return tuple(candidates[:4])


def _condensed_pos_name_candidates(
    item_name: str, preferences: PosNamePreferenceProfile
) -> tuple[str, ...]:
    tokens = _meaningful_pos_tokens(item_name)
    if len(tokens) <= 4:
        return ()
    choices = [_pos_token_choices(token, preferences, len(tokens)) for token in tokens]
    primary = [(token_choices[0][0], token_choices[0][1]) for token_choices in choices]
    scored_candidates = []
    max_kept = min(4, len(primary))
    for kept_count in range(max_kept, 1, -1):
        for indexes in itertools.combinations(range(len(primary)), kept_count):
            values = [primary[index][0] for index in indexes]
            token_score = sum(primary[index][1] for index in indexes)
            keep_score = kept_count * 8
            edge_score = (8 if 0 in indexes else 0) + (6 if len(primary) - 1 in indexes else 0)
            for candidate, style_score in _format_pos_candidates(values, preferences):
                scored_candidates.append(
                    (
                        candidate,
                        token_score
                        + keep_score
                        + edge_score
                        + style_score
                        + _length_score(candidate),
                    )
                )
    ordered = sorted(
        scored_candidates, key=lambda item: (-item[1], len(item[0]), item[0].casefold())
    )
    candidates = []
    for candidate, _score in ordered:
        if len(candidate) > MAX_POS_NAME_LENGTH or candidate in candidates:
            continue
        candidates.append(candidate)
    return tuple(candidates[:4])


def _pos_choice_sequences(
    tokens: list[str],
    preferences: PosNamePreferenceProfile,
    start_index: int = 0,
    limit: int = 64,
) -> list[list[tuple[tuple[str, int], ...]]]:
    if start_index >= len(tokens):
        return [[]]
    sequences: list[list[tuple[tuple[str, int], ...]]] = []
    for phrase_tokens, replacement in POS_NAME_PHRASE_REPLACEMENTS.items():
        phrase_length = len(phrase_tokens)
        if tuple(tokens[start_index : start_index + phrase_length]) != phrase_tokens:
            continue
        for tail in _pos_choice_sequences(tokens, preferences, start_index + phrase_length, limit):
            sequences.append([((_title_token(replacement), 18),), *tail])
            if len(sequences) >= limit:
                return sequences
    for pattern in preferences.acronym_patterns:
        if not _acronym_pattern_matches(tokens, start_index, pattern):
            continue
        value = "".join(
            token[0].upper() for token in tokens[start_index : start_index + pattern.span_length]
        )
        score = pattern.count * 55
        for tail in _pos_choice_sequences(
            tokens, preferences, start_index + pattern.span_length, limit
        ):
            sequences.append([((value, score),), *tail])
            if len(sequences) >= limit:
                return sequences
    for tail in _pos_choice_sequences(tokens, preferences, start_index + 1, limit):
        sequences.append([_pos_token_choices(tokens[start_index], preferences, len(tokens)), *tail])
        if len(sequences) >= limit:
            return sequences
    return sequences


def _pos_token_choices(
    token: str, preferences: PosNamePreferenceProfile, source_token_count: int
) -> tuple[tuple[str, int], ...]:
    choices: list[tuple[str, int]] = []
    for option in preferences.abbreviation_options.get(token, ()):
        choices.append((option.value, _abbreviation_option_score(option, source_token_count)))
    primary = preferences.abbreviations.get(token)
    if primary:
        choices.append((primary, 5))
    static = ABBREVIATIONS.get(token)
    if static:
        choices.append((static, 15))
    choices.append((token, 0))
    unique: dict[str, int] = {}
    for value, score in choices:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        unique[key] = max(score, unique.get(key, -999))
    ordered = sorted(
        ((_restore_preferred_case(key, choices), score) for key, score in unique.items()),
        key=lambda item: (-item[1], len(item[0]), item[0].casefold()),
    )
    return tuple(ordered[:3])


def _restore_preferred_case(key: str, choices: list[tuple[str, int]]) -> str:
    for value, _score in choices:
        if value.casefold() == key:
            return value
    return key


def _abbreviation_option_score(
    option: PosNameAbbreviationPreference, source_token_count: int
) -> int:
    context_penalty = 0
    if option.source_token_counts:
        nearest = min(abs(source_token_count - count) for count in option.source_token_counts)
        context_penalty = nearest * 12
    return option.count * 25 - context_penalty


def _matching_acronym_span(tokens: list[str], start_index: int, override_token: str) -> int | None:
    normalized_override = normalize_text(override_token).replace(" ", "")
    if len(normalized_override) < 2:
        return None
    max_span = min(4, len(tokens) - start_index)
    for span_length in range(max_span, 1, -1):
        acronym = "".join(token[0] for token in tokens[start_index : start_index + span_length])
        if acronym == normalized_override:
            return span_length
    return None


def _record_acronym_preference(
    patterns: tuple[PosNameAcronymPreference, ...],
    *,
    suffix_tokens: tuple[str, ...],
    span_length: int,
    example: str,
) -> tuple[PosNameAcronymPreference, ...]:
    if not suffix_tokens:
        return patterns
    rows = []
    matched = False
    for pattern in patterns:
        if pattern.suffix_tokens != suffix_tokens or pattern.span_length != span_length:
            rows.append(pattern)
            continue
        matched = True
        rows.append(
            replace(
                pattern,
                count=pattern.count + 1,
                examples=_append_limited(pattern.examples, example),
            )
        )
    if not matched:
        rows.append(
            PosNameAcronymPreference(
                suffix_tokens=suffix_tokens,
                span_length=span_length,
                examples=(example,),
            )
        )
    return tuple(sorted(rows, key=lambda pattern: (-pattern.count, pattern.suffix_tokens)))


def _acronym_pattern_matches(
    tokens: list[str], start_index: int, pattern: PosNameAcronymPreference
) -> bool:
    end_index = start_index + pattern.span_length
    if end_index > len(tokens):
        return False
    return tuple(tokens[start_index + 1 : end_index]) == pattern.suffix_tokens


def _format_pos_candidates(
    values: list[str], preferences: PosNamePreferenceProfile
) -> tuple[tuple[str, int], ...]:
    titled = [_title_token(value) for value in values if value]
    if not titled:
        return ()
    spaced = " ".join(titled)
    compact = "".join(titled)
    spaced_score = preferences.spaced_overrides * 4
    compact_score = preferences.compact_overrides * 4
    if preferences.spaced_overrides >= preferences.compact_overrides:
        return ((spaced, spaced_score), (compact, compact_score))
    return ((compact, compact_score), (spaced, spaced_score))


def _length_score(candidate: str) -> int:
    if len(candidate) > MAX_POS_NAME_LENGTH:
        return -500 - len(candidate)
    # Prefer names that use the available POS space without hitting the limit accidentally.
    return MAX_POS_NAME_LENGTH - abs(MAX_POS_NAME_LENGTH - len(candidate))


def _record_abbreviation_preference(
    options: tuple[PosNameAbbreviationPreference, ...],
    value: str,
    *,
    source_token_count: int,
    override_length: int,
    example: str,
) -> tuple[PosNameAbbreviationPreference, ...]:
    rows = []
    matched = False
    selected_after_count = 1
    for option in options:
        if option.value.casefold() == value.casefold():
            selected_after_count = option.count + 1
            break
    for option in options:
        if option.value.casefold() != value.casefold():
            decayed = _decay_abbreviation_option(
                option,
                source_token_count,
                selected_after_count=selected_after_count,
            )
            if decayed is not None:
                rows.append(decayed)
            continue
        matched = True
        rows.append(
            replace(
                option,
                count=option.count + 1,
                source_token_counts=(*option.source_token_counts, source_token_count),
                override_lengths=(*option.override_lengths, override_length),
                examples=_append_limited(option.examples, example),
            )
        )
    if not matched:
        rows.append(
            PosNameAbbreviationPreference(
                value=value,
                source_token_counts=(source_token_count,),
                override_lengths=(override_length,),
                examples=(example,),
            )
        )
    return tuple(sorted(rows, key=lambda option: (-option.count, option.value.casefold())))


def _decay_abbreviation_option(
    option: PosNameAbbreviationPreference,
    source_token_count: int,
    *,
    selected_after_count: int,
) -> PosNameAbbreviationPreference | None:
    if not _abbreviation_context_overlaps(option, source_token_count):
        return option
    if option.count > selected_after_count:
        return option
    new_count = option.count - 1
    if new_count <= 0:
        return None
    return replace(option, count=new_count)


def _abbreviation_context_overlaps(
    option: PosNameAbbreviationPreference,
    source_token_count: int,
) -> bool:
    if not option.source_token_counts:
        return True
    return source_token_count in option.source_token_counts


def _append_limited(values: tuple[str, ...], value: str, limit: int = 5) -> tuple[str, ...]:
    if not value or value in values:
        return values
    return (*values, value)[-limit:]


def _meaningful_pos_tokens(item_name: str) -> list[str]:
    return [
        token for token in normalize_text(item_name).split() if token not in POS_NAME_STOP_WORDS
    ]


def _pos_preference_rules_payload(profile: PosNamePreferenceProfile) -> dict[str, list[dict]]:
    return {
        token: [
            {
                "value": option.value,
                "count": option.count,
                "source_token_counts": list(option.source_token_counts),
                "override_lengths": list(option.override_lengths),
                "examples": list(option.examples),
            }
            for option in options
        ]
        for token, options in sorted(profile.abbreviation_options.items())
        if options
    }


def _pos_acronym_rules_payload(profile: PosNamePreferenceProfile) -> list[dict]:
    return [
        {
            "suffix_tokens": list(pattern.suffix_tokens),
            "span_length": pattern.span_length,
            "count": pattern.count,
            "examples": list(pattern.examples),
        }
        for pattern in profile.acronym_patterns
    ]


def _load_pos_preference_rules(
    payload: dict,
) -> dict[str, tuple[PosNameAbbreviationPreference, ...]]:
    rules = {}
    for raw_token, raw_options in payload.items():
        token = normalize_text(str(raw_token))
        if not token or not isinstance(raw_options, list):
            continue
        options = []
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                continue
            value = _clean_text(str(raw_option.get("value") or ""))
            if not value:
                continue
            options.append(
                PosNameAbbreviationPreference(
                    value=value,
                    count=max(1, _positive_int(raw_option.get("count"))),
                    source_token_counts=_positive_int_tuple(raw_option.get("source_token_counts")),
                    override_lengths=_positive_int_tuple(raw_option.get("override_lengths")),
                    examples=tuple(
                        _clean_text(str(example))
                        for example in raw_option.get("examples", [])
                        if _clean_text(str(example))
                    )[:5]
                    if isinstance(raw_option.get("examples"), list)
                    else (),
                )
            )
        if options:
            rules[token] = tuple(
                sorted(options, key=lambda option: (-option.count, option.value.casefold()))
            )
    return rules


def _load_pos_acronym_rules(payload: list) -> tuple[PosNameAcronymPreference, ...]:
    patterns = []
    for raw_pattern in payload:
        if not isinstance(raw_pattern, dict):
            continue
        raw_suffix = raw_pattern.get("suffix_tokens", [])
        if not isinstance(raw_suffix, list):
            continue
        suffix_tokens = tuple(
            token
            for raw_token in raw_suffix
            if (token := normalize_text(str(raw_token)).replace(" ", ""))
        )
        span_length = _positive_int(raw_pattern.get("span_length"))
        if not suffix_tokens or span_length < 2:
            continue
        raw_examples = raw_pattern.get("examples", [])
        patterns.append(
            PosNameAcronymPreference(
                suffix_tokens=suffix_tokens,
                span_length=span_length,
                count=max(1, _positive_int(raw_pattern.get("count"))),
                examples=tuple(
                    _clean_text(str(example))
                    for example in raw_examples
                    if _clean_text(str(example))
                )[:5]
                if isinstance(raw_examples, list)
                else (),
            )
        )
    return tuple(sorted(patterns, key=lambda pattern: (-pattern.count, pattern.suffix_tokens)))


def _merge_pos_preferences(
    left: PosNamePreferenceProfile, right: PosNamePreferenceProfile
) -> PosNamePreferenceProfile:
    abbreviations = {**left.abbreviations, **right.abbreviations}
    option_tokens = set(left.abbreviation_options) | set(right.abbreviation_options)
    options = {}
    for token in option_tokens:
        merged: tuple[PosNameAbbreviationPreference, ...] = ()
        for option in (
            *left.abbreviation_options.get(token, ()),
            *right.abbreviation_options.get(token, ()),
        ):
            merged = _merge_abbreviation_option(merged, option)
        options[token] = merged
    return PosNamePreferenceProfile(
        abbreviations=abbreviations,
        abbreviation_options=options,
        acronym_patterns=_merge_acronym_patterns(left.acronym_patterns, right.acronym_patterns),
        spaced_overrides=left.spaced_overrides + right.spaced_overrides,
        compact_overrides=left.compact_overrides + right.compact_overrides,
    )


def merge_pos_preferences(
    left: PosNamePreferenceProfile, right: PosNamePreferenceProfile
) -> PosNamePreferenceProfile:
    return _merge_pos_preferences(left, right)


def _merge_abbreviation_option(
    options: tuple[PosNameAbbreviationPreference, ...],
    incoming: PosNameAbbreviationPreference,
) -> tuple[PosNameAbbreviationPreference, ...]:
    rows = []
    matched = False
    for option in options:
        if option.value.casefold() != incoming.value.casefold():
            rows.append(option)
            continue
        matched = True
        rows.append(
            replace(
                option,
                count=option.count + incoming.count,
                source_token_counts=(*option.source_token_counts, *incoming.source_token_counts),
                override_lengths=(*option.override_lengths, *incoming.override_lengths),
                examples=tuple(dict.fromkeys((*option.examples, *incoming.examples)))[:5],
            )
        )
    if not matched:
        rows.append(incoming)
    return tuple(sorted(rows, key=lambda option: (-option.count, option.value.casefold())))


def _merge_acronym_patterns(
    left: tuple[PosNameAcronymPreference, ...],
    right: tuple[PosNameAcronymPreference, ...],
) -> tuple[PosNameAcronymPreference, ...]:
    merged = left
    for pattern in right:
        for _ in range(pattern.count):
            merged = _record_acronym_preference(
                merged,
                suffix_tokens=pattern.suffix_tokens,
                span_length=pattern.span_length,
                example=pattern.examples[0] if pattern.examples else "",
            )
    return merged


def _positive_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _positive_int_tuple(value) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(number for raw in value if (number := _positive_int(raw)) > 0)


def _row_by_id(session: ImportSession, row_id: str) -> SessionRow | None:
    for row in session.rows:
        if row.row_id == row_id:
            return row
    return None


def _category_result(category: str):
    from lunchtab_product_init.models import CategoryResult

    return CategoryResult(
        categories=(category,),
        restriction_policies=(),
        status="operator",
        confidence=100,
        confidence_band="manual",
        reason="operator assigned",
        matched_rules=(),
        source_evidence=(),
    )


def _summary(session: ImportSession, paths: SessionOutputPaths) -> SessionBuildSummary:
    active = session.active_rows
    barcode_counts = Counter(
        barcode.casefold() for row in active for barcode in parse_barcodes(row.barcode)
    )
    pos_counts = Counter(row.pos_name for row in active if row.pos_name)
    pos_effort_counts = Counter(row.pos_edit_effort for row in session.rows if row.pos_overridden)
    return SessionBuildSummary(
        parsed_rows=len(session.rows),
        exported_rows=len(active),
        deleted_rows=len(session.deleted_rows),
        edited_rows=sum(1 for row in session.rows if row.edited),
        category_count=len(session.category_names),
        pos_overrides=sum(1 for row in session.rows if row.pos_overridden),
        pos_light_edits=pos_effort_counts["light"],
        pos_moderate_edits=pos_effort_counts["moderate"],
        pos_heavy_overrides=pos_effort_counts["heavy"],
        duplicate_barcodes=sum(1 for _, count in barcode_counts.items() if count > 1),
        duplicate_pos_names=sum(1 for _, count in pos_counts.items() if count > 1),
        core_catalogue_rows=sum(1 for row in active if row.core_catalogue),
        output_paths=paths,
    )


def _category_audit_headers() -> list[str]:
    return [
        "RowId",
        "ItemName",
        "Price",
        "Barcode",
        "OldCategory",
        "Category",
        "Status",
        "ReviewReason",
    ]


def _category_audit_rows(session: ImportSession):
    for row in session.rows:
        yield {
            "RowId": row.row_id,
            "ItemName": row.item_name,
            "Price": row.price,
            "Barcode": row.barcode,
            "OldCategory": row.old_category,
            "Category": row.category,
            "Status": row.status,
            "ReviewReason": row.review_reason,
        }


def _naming_audit_headers() -> list[str]:
    return [
        "RowId",
        "ItemName",
        "BaseProductPosName",
        "Overridden",
        "PosNameBeforeOverride",
        "PosEditDistance",
        "PosCharacterDelta",
        "PosSpacesChanged",
        "PosTokenChanges",
        "PosActiveEditActions",
        "PosEditEffort",
        "Status",
        "ReviewReason",
    ]


def _naming_audit_rows(session: ImportSession):
    for row in session.rows:
        yield {
            "RowId": row.row_id,
            "ItemName": row.item_name,
            "BaseProductPosName": row.pos_name,
            "Overridden": "true" if row.pos_overridden else "false",
            "PosNameBeforeOverride": row.pos_name_before_override,
            "PosEditDistance": str(row.pos_edit_distance) if row.pos_overridden else "",
            "PosCharacterDelta": str(row.pos_character_delta) if row.pos_overridden else "",
            "PosSpacesChanged": str(row.pos_spaces_changed) if row.pos_overridden else "",
            "PosTokenChanges": str(row.pos_token_changes) if row.pos_overridden else "",
            "PosActiveEditActions": str(row.pos_active_edit_actions) if row.pos_overridden else "",
            "PosEditEffort": row.pos_edit_effort,
            "Status": row.status,
            "ReviewReason": row.review_reason,
        }


def _pos_profile_audit_headers() -> list[str]:
    return [
        "RuleType",
        "Token",
        "Rank",
        "Replacement",
        "Count",
        "SourceTokenCounts",
        "OverrideLengths",
        "SuffixTokens",
        "SpanLength",
        "Examples",
        "SpacedOverrides",
        "CompactOverrides",
    ]


def _pos_profile_audit_rows(profile: PosNamePreferenceProfile):
    for token, options in sorted(profile.abbreviation_options.items()):
        for rank, option in enumerate(options, start=1):
            yield {
                "RuleType": "abbreviation",
                "Token": token,
                "Rank": str(rank),
                "Replacement": option.value,
                "Count": str(option.count),
                "SourceTokenCounts": _join_ints(option.source_token_counts),
                "OverrideLengths": _join_ints(option.override_lengths),
                "SuffixTokens": "",
                "SpanLength": "",
                "Examples": " | ".join(option.examples),
                "SpacedOverrides": "",
                "CompactOverrides": "",
            }
    for rank, pattern in enumerate(profile.acronym_patterns, start=1):
        yield {
            "RuleType": "acronym",
            "Token": "",
            "Rank": str(rank),
            "Replacement": "",
            "Count": str(pattern.count),
            "SourceTokenCounts": "",
            "OverrideLengths": "",
            "SuffixTokens": ", ".join(pattern.suffix_tokens),
            "SpanLength": str(pattern.span_length),
            "Examples": " | ".join(pattern.examples),
            "SpacedOverrides": "",
            "CompactOverrides": "",
        }
    yield {
        "RuleType": "style",
        "Token": "",
        "Rank": "",
        "Replacement": "",
        "Count": "",
        "SourceTokenCounts": "",
        "OverrideLengths": "",
        "SuffixTokens": "",
        "SpanLength": "",
        "Examples": "",
        "SpacedOverrides": str(profile.spaced_overrides),
        "CompactOverrides": str(profile.compact_overrides),
    }


def _session_audit_headers() -> list[str]:
    return [
        "RowId",
        "Source",
        "SourceKey",
        "ItemName",
        "Price",
        "Barcode",
        "OldCategory",
        "Category",
        "BaseProductPosName",
        "PosNameBeforeOverride",
        "PosEditDistance",
        "PosCharacterDelta",
        "PosSpacesChanged",
        "PosTokenChanges",
        "PosActiveEditActions",
        "PosEditEffort",
        "IsPublished",
        "IsOrderable",
        "CoreCatalogue",
        "Status",
        "Edited",
        "DeletedReason",
        "MergeTargetRowId",
        "MergeTransferredBarcodes",
        "MergeTargetBarcodeBefore",
        "MergeTargetBarcodeAfter",
        "MergeActionTimestamp",
        "ReviewReason",
    ]


def _session_audit_rows(rows_or_session):
    rows = rows_or_session.rows if isinstance(rows_or_session, ImportSession) else rows_or_session
    for row in rows:
        yield {
            "RowId": row.row_id,
            "Source": row.candidate.source,
            "SourceKey": row.candidate.source_key,
            "ItemName": row.item_name,
            "Price": row.price,
            "Barcode": row.barcode,
            "OldCategory": row.old_category,
            "Category": row.category,
            "BaseProductPosName": row.pos_name,
            "PosNameBeforeOverride": row.pos_name_before_override,
            "PosEditDistance": str(row.pos_edit_distance) if row.pos_overridden else "",
            "PosCharacterDelta": str(row.pos_character_delta) if row.pos_overridden else "",
            "PosSpacesChanged": str(row.pos_spaces_changed) if row.pos_overridden else "",
            "PosTokenChanges": str(row.pos_token_changes) if row.pos_overridden else "",
            "PosActiveEditActions": str(row.pos_active_edit_actions) if row.pos_overridden else "",
            "PosEditEffort": row.pos_edit_effort,
            "IsPublished": "true" if row.is_published else "false",
            "IsOrderable": "true" if row.is_orderable else "false",
            "CoreCatalogue": "true" if row.core_catalogue else "false",
            "Status": row.status,
            "Edited": "true" if row.edited else "false",
            "DeletedReason": row.deleted_reason,
            "MergeTargetRowId": row.merge_target_row_id,
            "MergeTransferredBarcodes": row.merge_transferred_barcodes,
            "MergeTargetBarcodeBefore": row.merge_target_barcode_before,
            "MergeTargetBarcodeAfter": row.merge_target_barcode_after,
            "MergeActionTimestamp": row.merge_action_timestamp,
            "ReviewReason": row.review_reason,
        }


def _write_manifest(
    inputs: BuildInputs,
    session: ImportSession,
    paths: SessionOutputPaths,
    summary: SessionBuildSummary,
) -> None:
    artifacts = [
        paths.final_import,
        paths.core_catalogue,
        paths.category_audit,
        paths.naming_audit,
        paths.pos_profile_audit,
        paths.session_audit,
        paths.deleted_audit,
        paths.summary,
    ]
    payload = {
        "workflow": "Lunchtab Product Initialization Guided Session",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "product_template": _source_info(inputs.product_template_path),
            "recipe_list": _source_info(inputs.recipe_list_path),
            "odin_inventory": _source_info(inputs.odin_inventory_path),
            "generic_inventory": _source_info(inputs.generic_inventory_path),
        },
        "counts": {
            "parsed_rows": summary.parsed_rows,
            "exported_rows": summary.exported_rows,
            "deleted_rows": summary.deleted_rows,
            "edited_rows": summary.edited_rows,
            "category_count": summary.category_count,
            "pos_overrides": summary.pos_overrides,
            "pos_light_edits": summary.pos_light_edits,
            "pos_moderate_edits": summary.pos_moderate_edits,
            "pos_heavy_overrides": summary.pos_heavy_overrides,
            "duplicate_barcodes": summary.duplicate_barcodes,
            "duplicate_pos_names": summary.duplicate_pos_names,
            "core_catalogue_rows": summary.core_catalogue_rows,
        },
        "categories": list(session.category_names),
        "pos_name_preferences": session.pos_preferences.abbreviations,
        "pos_name_preference_rules": _pos_preference_rules_payload(session.pos_preferences),
        "pos_name_acronym_rules": _pos_acronym_rules_payload(session.pos_preferences),
        "pos_name_style": {
            "spaced_overrides": session.pos_preferences.spaced_overrides,
            "compact_overrides": session.pos_preferences.compact_overrides,
        },
        "artifacts": {path.name: {"sha256": _sha256(path)} for path in artifacts if path.is_file()},
    }
    paths.manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_summary(
    path: Path,
    summary: SessionBuildSummary,
    run_dir: Path,
) -> None:
    path.write_text(
        "\n".join(
            [
                "# Lunchtab Product Initialization Run Summary",
                "",
                f"- Run folder: `{run_dir}`",
                f"- Parsed rows: {summary.parsed_rows}",
                f"- Exported rows: {summary.exported_rows}",
                f"- Deleted rows: {summary.deleted_rows}",
                f"- Edited rows: {summary.edited_rows}",
                f"- Category count: {summary.category_count}",
                f"- POS-name overrides: {summary.pos_overrides}",
                f"- POS-name light edits: {summary.pos_light_edits}",
                f"- POS-name moderate edits: {summary.pos_moderate_edits}",
                f"- POS-name heavy overrides: {summary.pos_heavy_overrides}",
                f"- Duplicate barcodes: {summary.duplicate_barcodes}",
                f"- Duplicate POS names: {summary.duplicate_pos_names}",
                f"- Core Catalogue rows: {summary.core_catalogue_rows}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _source_info(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    return {"filename": path.name, "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _join_ints(values: tuple[int, ...]) -> str:
    return ", ".join(str(value) for value in values)


def _pos_name_edit_metrics(before: str, after: str) -> dict[str, int | str]:
    before = _clean_text(before)
    after = _clean_text(after)
    edit_distance = _levenshtein_distance(before, after)
    return {
        "edit_distance": edit_distance,
        "character_delta": abs(len(after) - len(before)),
        "spaces_changed": abs(after.count(" ") - before.count(" ")),
        "token_changes": _levenshtein_distance(tuple(before.split()), tuple(after.split())),
        "active_edit_actions": edit_distance,
        "effort": _pos_edit_effort(edit_distance),
    }


def _pos_edit_effort(edit_distance: int) -> str:
    if edit_distance <= 0:
        return "none"
    if edit_distance <= 2:
        return "light"
    if edit_distance <= 5:
        return "moderate"
    return "heavy"


def _levenshtein_distance(left, right) -> int:
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_value in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_value in enumerate(right, start=1):
            substitution_cost = 0 if left_value == right_value else 1
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + substitution_cost,
                )
            )
        previous = current
    return previous[-1]


def _decimal_or_none(value: str):
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(str(value or "").strip())
    except InvalidOperation:
        return None


def _normalize_price_operator(value: str) -> PriceFilterOperator:
    normalized = str(value or "").strip().casefold()
    if normalized in {"", "any"}:
        return "any"
    if normalized in {"=", "exact", "exact match"}:
        return "="
    if normalized in {"no price", "no_price", "missing price", "without price"}:
        return "no_price"
    if normalized in {"<", ">", "<=", ">=", "range"}:
        return normalized  # type: ignore[return-value]
    return "any"


def _normalize_stock_operator(value: str) -> StockFilterOperator:
    normalized = str(value or "").strip().casefold()
    if normalized in {"", "any"}:
        return "any"
    if normalized in {"=", "exact", "exact match", "0", "zero", "zero stock"}:
        return "="
    if normalized in {"no stock", "no_stock", "missing stock", "without stock", "null"}:
        return "no_stock"
    if normalized in {"<", ">", "<=", ">=", "range"}:
        return normalized  # type: ignore[return-value]
    return "any"


def _normalize_category_assignment_filter(value: str) -> CategoryAssignmentFilter:
    normalized = normalize_text(value)
    if normalized in {"has category", "assigned", "category assigned"}:
        return "assigned"
    if normalized in {"no category", "unassigned", "category unassigned", "no category assigned"}:
        return "unassigned"
    return "any"


def _normalize_name_filter(value: str) -> NameFilter:
    normalized = normalize_text(value)
    if normalized in {"duplicate name", "duplicate names", "duplicates", "duplicated name"}:
        return "duplicate_name"
    return "any"


def _duplicate_item_names(rows) -> set[str]:
    counts = Counter(normalize_text(row.item_name) for row in rows if normalize_text(row.item_name))
    return {name for name, count in counts.items() if count > 1}


def _old_category_filter_matches(old_category: str, old_category_filter: str) -> bool:
    if not old_category_filter:
        return True
    if old_category_filter in {"no category", "no old category", "null", "none"}:
        return not old_category.strip()
    return old_category_filter in normalize_text(old_category)


def _price_matches(price, operator: PriceFilterOperator, target, upper) -> bool:
    if operator == "no_price":
        return price is None
    if operator == "any" or target is None:
        return True
    if price is None:
        return False
    if operator == "=":
        return price == target
    if operator == "<":
        return price < target
    if operator == ">":
        return price > target
    if operator == "<=":
        return price <= target
    if operator == ">=":
        return price >= target
    if operator == "range":
        if price < target:
            return False
        return upper is None or price <= upper
    return True


def _stock_matches(
    source: str, raw_stock: str, stock, operator: StockFilterOperator, target, upper
) -> bool:
    if operator == "any":
        return True
    if not _is_inventory_source(source):
        return False
    if not str(raw_stock or "").strip():
        return operator == "no_stock"
    if stock is None:
        return operator == "no_stock"
    if operator == "no_stock":
        return False
    if target is None:
        return True
    if operator == "=":
        return stock == target
    if operator == "<":
        return stock < target
    if operator == ">":
        return stock > target
    if operator == "<=":
        return stock <= target
    if operator == ">=":
        return stock >= target
    if operator == "range":
        if stock < target:
            return False
        return upper is None or stock <= upper
    return True


def _is_inventory_source(source: str) -> bool:
    return str(source or "").strip().casefold() in {
        "odin",
        "inventory",
        "generic_inventory",
        "recipe+odin",
        "recipe+inventory",
        "recipe+generic_inventory",
    }


def _barcode_filter_matches(barcode: str, barcode_filter: str) -> bool:
    if not barcode_filter:
        return True
    barcodes = parse_barcodes(barcode)
    barcode_norms = [normalize_text(value) for value in barcodes]
    if barcode_filter == "no barcode":
        return not barcodes
    if barcode_filter == "vendor":
        return any("sagemb" not in value for value in barcode_norms)
    return any(barcode_filter in value for value in barcode_norms)


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _dedupe_cleaned(values) -> tuple[str, ...]:
    cleaned_values = []
    seen = set()
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned.casefold() not in seen:
            cleaned_values.append(cleaned)
            seen.add(cleaned.casefold())
    return _sort_category_names(cleaned_values)


def _sort_category_names(values) -> tuple[str, ...]:
    return tuple(sorted(values, key=lambda value: (value.casefold(), value)))


def _append_reason(current: str, reason: str) -> str:
    values = _reason_parts(current)
    if reason and reason not in values:
        values.append(reason)
    return "; ".join(values)


def _reason_parts(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _title_token(token: str) -> str:
    if not token:
        return ""
    return token.upper() if token.isdigit() else token[:1].upper() + token[1:]
