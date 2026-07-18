from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

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

DELETED_AUDIT_NAME = "Deleted Product Audit.csv"
SESSION_AUDIT_NAME = "Session Review Audit.csv"


@dataclass(frozen=True)
class PosNamePreferenceProfile:
    abbreviations: dict[str, str]


@dataclass(frozen=True)
class SessionRow:
    row_id: str
    candidate: ProductCandidate
    category: str = ""
    pos_name: str = ""
    status: RowStatus = "active"
    review_reason: str = ""
    deleted_reason: str = ""
    edited: bool = False
    pos_overridden: bool = False

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
        return all(validate_export_ready(row) == [] for row in self.active_rows)


@dataclass(frozen=True)
class SessionOutputPaths:
    final_import: Path
    category_audit: Path
    naming_audit: Path
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
    duplicate_barcodes: int
    duplicate_pos_names: int
    output_paths: SessionOutputPaths


@dataclass(frozen=True)
class SessionExportResult:
    run_dir: Path
    summary: SessionBuildSummary


def parse_sources(inputs: BuildInputs) -> ImportSession:
    headers = read_lunchtab_template(inputs.product_template_path)
    recipes = read_recipe_candidates(inputs.recipe_list_path)
    odin = read_odin_candidates(inputs.odin_inventory_path)
    candidates = merge_candidates(recipes, odin)
    barcode_duplicates = duplicate_values([candidate.barcode for candidate in candidates])
    rows = tuple(
        _session_row(index, candidate, barcode_duplicates)
        for index, candidate in enumerate(candidates, start=1)
    )
    return ImportSession(headers=headers, rows=rows)


def add_category(session: ImportSession, name: str) -> ImportSession:
    cleaned = _clean_text(name)
    if not cleaned:
        return session
    categories = list(session.category_names)
    if cleaned not in categories:
        categories.append(cleaned)
    return replace(session, category_names=tuple(categories))


def filter_rows(
    session: ImportSession,
    *,
    keyword: str = "",
    price_operator: PriceFilterOperator = "any",
    price_value: str = "",
    price_upper: str = "",
    min_price: str = "",
    max_price: str = "",
    include_deleted: bool = False,
) -> tuple[SessionRow, ...]:
    keyword_norm = normalize_text(keyword)
    price_operator = _normalize_price_operator(price_operator)
    if min_price or max_price:
        price_operator = "range"
        price_value = min_price
        price_upper = max_price
    target_price = _decimal_or_none(price_value)
    upper_price = _decimal_or_none(price_upper)
    rows = session.rows if include_deleted else session.active_rows
    filtered = []
    for row in rows:
        if keyword_norm and keyword_norm not in normalize_text(row.item_name):
            continue
        price = _decimal_or_none(row.price)
        if not _price_matches(price, price_operator, target_price, upper_price):
            continue
        filtered.append(row)
    return tuple(filtered)


def assign_category(session: ImportSession, row_ids: set[str], category: str) -> ImportSession:
    session = add_category(session, category)
    cleaned = _clean_text(category)
    return replace(
        session,
        rows=tuple(
            replace(row, category=cleaned) if row.row_id in row_ids and row.status != "deleted" else row
            for row in session.rows
        ),
    )


def mark_for_edit(session: ImportSession, row_ids: set[str], reason: str = "operator review") -> ImportSession:
    return replace(
        session,
        rows=tuple(
            replace(row, status="needs_edit", review_reason=_append_reason(row.review_reason, reason))
            if row.row_id in row_ids and row.status != "deleted"
            else row
            for row in session.rows
        ),
    )


def delete_rows(session: ImportSession, row_ids: set[str], reason: str = "operator deleted") -> ImportSession:
    return replace(
        session,
        rows=tuple(
            replace(row, status="deleted", deleted_reason=reason)
            if row.row_id in row_ids
            else row
            for row in session.rows
        ),
    )


def no_barcode_rows(session: ImportSession) -> tuple[SessionRow, ...]:
    return tuple(row for row in session.active_rows if not row.barcode)


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
    for row in session.rows:
        if row.row_id != row_id:
            updated_rows.append(row)
            continue
        candidate = replace(
            row.candidate,
            item_name=_clean_text(item_name),
            price=_clean_text(price),
            barcode="".join(str(barcode or "").split()),
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
    return _refresh_barcode_review(replace(session, rows=tuple(updated_rows)))


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
            replace(row, status="pos_needs_review", review_reason=_append_reason(row.review_reason, "duplicate POS name"))
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
    if target is not None and cleaned:
        preferences = learn_pos_preferences(preferences, target.item_name, cleaned)
    for row in session.rows:
        if row.row_id == row_id:
            candidate = replace(row, pos_name=cleaned, pos_overridden=True)
        else:
            candidate = row
        rows.append(candidate)
    session = replace(session, rows=tuple(rows), pos_preferences=preferences)
    return _refresh_pos_status(session)


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


def suggest_pos_names(session: ImportSession, row_id: str) -> tuple[str, ...]:
    row = _row_by_id(session, row_id)
    if row is None:
        return ()
    base = generate_pos_name(row.item_name).value
    preferred = generate_pos_name_with_preferences(row.item_name, session.pos_preferences).value
    compact = "".join(token[:4].title() for token in normalize_text(row.item_name).split())
    suggestions = []
    for value in (preferred, base, compact[:MAX_POS_NAME_LENGTH]):
        if value and value not in suggestions:
            suggestions.append(value)
    return tuple(suggestions[:3])


def generate_pos_name_with_preferences(item_name: str, preferences: PosNamePreferenceProfile):
    if not preferences.abbreviations:
        return generate_pos_name(item_name)
    tokens = normalize_text(item_name).split()
    preferred = " ".join(
        preferences.abbreviations.get(token, ABBREVIATIONS.get(token, token))
        for token in tokens
        if token not in {"a", "an", "and", "of", "the", "with"}
    )
    if preferred:
        candidate = "".join(_title_token(token) for token in preferred.split())
        if len(candidate) <= MAX_POS_NAME_LENGTH:
            base = generate_pos_name(item_name)
            return replace(
                base,
                value=candidate,
                status="ok",
                reason="",
                abbreviation_steps=(*base.abbreviation_steps, "preferences=" + preferred),
            )
    return generate_pos_name(item_name)


def learn_pos_preferences(
    preferences: PosNamePreferenceProfile, item_name: str, override: str
) -> PosNamePreferenceProfile:
    tokens = normalize_text(item_name).split()
    override_tokens = [token for token in override.replace("-", " ").split() if token]
    abbreviations = dict(preferences.abbreviations)
    for source, target in zip(tokens, override_tokens, strict=False):
        if source and target:
            abbreviations[source] = target
    return PosNamePreferenceProfile(abbreviations=abbreviations)


def final_rows(session: ImportSession, is_orderable: bool) -> list[dict[str, str]]:
    rows = []
    for row in session.active_rows:
        errors = validate_export_ready(row)
        if errors:
            raise ValueError(f"Row {row.row_id} is not export-ready: {', '.join(errors)}")
        rows.append(
            product_row(
                session.headers,
                replace(row.candidate, category=row.category),
                row.pos_name,
                _category_result(row.category),
                is_orderable,
            )
        )
    return rows


def export_session(
    session: ImportSession,
    inputs: BuildInputs,
    *,
    is_orderable: bool,
) -> SessionExportResult:
    if not session.can_export:
        raise ValueError("All active rows must be complete before export.")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = inputs.output_root / timestamp
    paths = SessionOutputPaths(
        final_import=run_dir / FINAL_OUTPUT_NAME,
        category_audit=run_dir / CATEGORY_AUDIT_NAME,
        naming_audit=run_dir / NAMING_AUDIT_NAME,
        session_audit=run_dir / SESSION_AUDIT_NAME,
        deleted_audit=run_dir / DELETED_AUDIT_NAME,
        manifest=run_dir / "run-manifest.json",
        summary=run_dir / "run-summary.md",
    )
    write_csv(paths.final_import, session.headers, final_rows(session, is_orderable))
    write_csv(paths.category_audit, _category_audit_headers(), _category_audit_rows(session))
    write_csv(paths.naming_audit, _naming_audit_headers(), _naming_audit_rows(session))
    write_csv(paths.session_audit, _session_audit_headers(), _session_audit_rows(session))
    write_csv(paths.deleted_audit, _session_audit_headers(), _session_audit_rows(session.deleted_rows))
    summary = _summary(session, paths)
    _write_manifest(inputs, session, paths, summary)
    _write_summary(paths.summary, summary, run_dir, is_orderable)
    return SessionExportResult(run_dir=run_dir, summary=summary)


def save_venue_profile(
    session: ImportSession, path: Path, *, name: str = "Venue Product Import Profile"
) -> None:
    payload = {
        "schema_version": 2,
        "name": name,
        "categories": list(session.category_names),
        "pos_name_preferences": session.pos_preferences.abbreviations,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def validate_export_ready(row: SessionRow) -> list[str]:
    reasons = _core_review_reasons(row.candidate, set())
    if not row.category:
        reasons.append("missing category")
    if not row.pos_name:
        reasons.append("missing POS name")
    if len(row.pos_name) > MAX_POS_NAME_LENGTH:
        reasons.append("POS name is longer than 15 characters")
    return sorted(set(reasons))


def _session_row(index: int, candidate: ProductCandidate, barcode_duplicates: set[str]) -> SessionRow:
    reasons = _core_review_reasons(candidate, barcode_duplicates)
    status: RowStatus = "active" if candidate.item_name and candidate.price else "needs_edit"
    return SessionRow(
        row_id=f"row-{index}",
        candidate=candidate,
        status=status if not reasons else "needs_edit",
        review_reason="; ".join(reasons),
    )


def _core_review_reasons(candidate: ProductCandidate, barcode_duplicates: set[str]) -> list[str]:
    reasons = []
    if not candidate.item_name:
        reasons.append("missing item name")
    if not candidate.price:
        reasons.append("missing or invalid price")
    if not candidate.barcode:
        reasons.append("missing barcode")
    if candidate.barcode and candidate.barcode in barcode_duplicates:
        reasons.append("duplicate barcode")
    return reasons


def _refresh_barcode_review(session: ImportSession) -> ImportSession:
    duplicates = duplicate_values([row.barcode for row in session.active_rows])
    rows = []
    for row in session.rows:
        if row.status == "deleted":
            rows.append(row)
            continue
        reasons = _core_review_reasons(row.candidate, duplicates)
        if not row.category:
            reasons.append("missing category")
        status: RowStatus = "needs_edit" if reasons else "edit_complete"
        rows.append(replace(row, status=status, review_reason="; ".join(sorted(set(reasons)))))
    return replace(session, rows=tuple(rows))


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
    barcode_counts = Counter(row.barcode for row in active if row.barcode)
    pos_counts = Counter(row.pos_name for row in active if row.pos_name)
    return SessionBuildSummary(
        parsed_rows=len(session.rows),
        exported_rows=len(active),
        deleted_rows=len(session.deleted_rows),
        edited_rows=sum(1 for row in session.rows if row.edited),
        category_count=len(session.category_names),
        pos_overrides=sum(1 for row in session.rows if row.pos_overridden),
        duplicate_barcodes=sum(1 for _, count in barcode_counts.items() if count > 1),
        duplicate_pos_names=sum(1 for _, count in pos_counts.items() if count > 1),
        output_paths=paths,
    )


def _category_audit_headers() -> list[str]:
    return ["RowId", "ItemName", "Price", "Barcode", "Category", "Status", "ReviewReason"]


def _category_audit_rows(session: ImportSession):
    for row in session.rows:
        yield {
            "RowId": row.row_id,
            "ItemName": row.item_name,
            "Price": row.price,
            "Barcode": row.barcode,
            "Category": row.category,
            "Status": row.status,
            "ReviewReason": row.review_reason,
        }


def _naming_audit_headers() -> list[str]:
    return ["RowId", "ItemName", "BaseProductPosName", "Overridden", "Status", "ReviewReason"]


def _naming_audit_rows(session: ImportSession):
    for row in session.rows:
        yield {
            "RowId": row.row_id,
            "ItemName": row.item_name,
            "BaseProductPosName": row.pos_name,
            "Overridden": "true" if row.pos_overridden else "false",
            "Status": row.status,
            "ReviewReason": row.review_reason,
        }


def _session_audit_headers() -> list[str]:
    return [
        "RowId",
        "Source",
        "SourceKey",
        "ItemName",
        "Price",
        "Barcode",
        "Category",
        "BaseProductPosName",
        "Status",
        "Edited",
        "DeletedReason",
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
            "Category": row.category,
            "BaseProductPosName": row.pos_name,
            "Status": row.status,
            "Edited": "true" if row.edited else "false",
            "DeletedReason": row.deleted_reason,
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
        paths.category_audit,
        paths.naming_audit,
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
        },
        "counts": {
            "parsed_rows": summary.parsed_rows,
            "exported_rows": summary.exported_rows,
            "deleted_rows": summary.deleted_rows,
            "edited_rows": summary.edited_rows,
            "category_count": summary.category_count,
            "pos_overrides": summary.pos_overrides,
            "duplicate_barcodes": summary.duplicate_barcodes,
            "duplicate_pos_names": summary.duplicate_pos_names,
        },
        "categories": list(session.category_names),
        "pos_name_preferences": session.pos_preferences.abbreviations,
        "artifacts": {
            path.name: {"sha256": _sha256(path)} for path in artifacts if path.is_file()
        },
    }
    paths.manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_summary(
    path: Path,
    summary: SessionBuildSummary,
    run_dir: Path,
    is_orderable: bool,
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
                f"- Duplicate barcodes: {summary.duplicate_barcodes}",
                f"- Duplicate POS names: {summary.duplicate_pos_names}",
                f"- IsOrderable: {'true' if is_orderable else 'false'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _source_info(path: Path) -> dict[str, str]:
    return {"filename": path.name, "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _append_reason(current: str, reason: str) -> str:
    values = [part.strip() for part in current.split(";") if part.strip()]
    if reason and reason not in values:
        values.append(reason)
    return "; ".join(values)


def _title_token(token: str) -> str:
    if not token:
        return ""
    return token.upper() if token.isdigit() else token[:1].upper() + token[1:]
