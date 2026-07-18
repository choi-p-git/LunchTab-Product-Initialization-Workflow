from __future__ import annotations

import hashlib
import itertools
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
CategoryAssignmentFilter = Literal["any", "assigned", "unassigned"]

DELETED_AUDIT_NAME = "Deleted Product Audit.csv"
SESSION_AUDIT_NAME = "Session Review Audit.csv"
POS_NAME_STOP_WORDS = {"a", "an", "and", "of", "the", "with"}


@dataclass(frozen=True)
class PosNameAbbreviationPreference:
    value: str
    count: int = 1
    source_token_counts: tuple[int, ...] = ()
    override_lengths: tuple[int, ...] = ()
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class PosNamePreferenceProfile:
    abbreviations: dict[str, str]
    abbreviation_options: dict[str, tuple[PosNameAbbreviationPreference, ...]] = field(
        default_factory=dict
    )
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
    return replace(session, category_names=_sort_category_names(categories))


def filter_rows(
    session: ImportSession,
    *,
    keyword: str = "",
    old_category: str = "",
    barcode_filter: str = "",
    category_assignment: CategoryAssignmentFilter | str = "any",
    price_operator: PriceFilterOperator = "any",
    price_value: str = "",
    price_upper: str = "",
    min_price: str = "",
    max_price: str = "",
    include_deleted: bool = False,
) -> tuple[SessionRow, ...]:
    keyword_norm = normalize_text(keyword)
    old_category_norm = normalize_text(old_category)
    barcode_norm = normalize_text(barcode_filter)
    category_assignment = _normalize_category_assignment_filter(category_assignment)
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
        if row.pos_overridden and row.pos_name:
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
    for row in session.rows:
        if row.row_id == row_id:
            candidate = replace(row, pos_name=cleaned, pos_overridden=True)
        else:
            candidate = row
        rows.append(candidate)
    if target is not None and cleaned and not validate_pos_name(cleaned, row_id, tuple(rows)):
        preferences = learn_pos_preferences(preferences, target.item_name, cleaned)
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
    preferred = _preferred_pos_name_candidates(row.item_name, session.pos_preferences)
    compact = "".join(token[:4].title() for token in normalize_text(row.item_name).split())
    suggestions = []
    for value in (*preferred, base, compact[:MAX_POS_NAME_LENGTH]):
        if value and value not in suggestions:
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
    source_token_count = len(tokens)
    override_length = len(_clean_text(override))
    for source, target in zip(tokens, override_tokens, strict=False):
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
    return PosNamePreferenceProfile(
        abbreviations=abbreviations,
        abbreviation_options=options,
        spaced_overrides=preferences.spaced_overrides + (1 if len(override_tokens) > 1 else 0),
        compact_overrides=preferences.compact_overrides + (1 if len(override_tokens) <= 1 else 0),
    )


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
        "pos_name_preference_rules": _pos_preference_rules_payload(session.pos_preferences),
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
    preference_style = payload.get("pos_name_style", {})
    if not isinstance(categories, list):
        raise ValueError("Venue profile categories must be a list.")
    if not isinstance(preferences, dict):
        raise ValueError("Venue profile POS name preferences must be an object.")
    if not isinstance(preference_rules, dict):
        raise ValueError("Venue profile POS name preference rules must be an object.")
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


def _session_row(index: int, candidate: ProductCandidate, barcode_duplicates: set[str]) -> SessionRow:
    reasons = _core_review_reasons(candidate, barcode_duplicates)
    status: RowStatus = "active" if candidate.item_name and candidate.price else "needs_edit"
    return SessionRow(
        row_id=f"row-{index}",
        candidate=candidate,
        old_category=candidate.category,
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
    token_choices = [_pos_token_choices(token, preferences, len(tokens)) for token in tokens]
    scored_candidates = []
    for choice_group in itertools.product(*token_choices):
        values = [value for value, _score in choice_group]
        token_score = sum(score for _value, score in choice_group)
        for candidate, style_score in _format_pos_candidates(values, preferences):
            scored_candidates.append((candidate, token_score + style_score + _length_score(candidate)))
    ordered = sorted(scored_candidates, key=lambda item: (-item[1], len(item[0]), item[0].casefold()))
    candidates = []
    for candidate, _score in ordered:
        if len(candidate) > MAX_POS_NAME_LENGTH or candidate in candidates:
            continue
        candidates.append(candidate)
    return tuple(candidates[:8])


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
    for option in options:
        if option.value.casefold() != value.casefold():
            rows.append(option)
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


def _append_limited(values: tuple[str, ...], value: str, limit: int = 5) -> tuple[str, ...]:
    if not value or value in values:
        return values
    return (*values, value)[-limit:]


def _meaningful_pos_tokens(item_name: str) -> list[str]:
    return [token for token in normalize_text(item_name).split() if token not in POS_NAME_STOP_WORDS]


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


def _load_pos_preference_rules(payload: dict) -> dict[str, tuple[PosNameAbbreviationPreference, ...]]:
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
            rules[token] = tuple(sorted(options, key=lambda option: (-option.count, option.value.casefold())))
    return rules


def _merge_pos_preferences(
    left: PosNamePreferenceProfile, right: PosNamePreferenceProfile
) -> PosNamePreferenceProfile:
    abbreviations = {**left.abbreviations, **right.abbreviations}
    option_tokens = set(left.abbreviation_options) | set(right.abbreviation_options)
    options = {}
    for token in option_tokens:
        merged: tuple[PosNameAbbreviationPreference, ...] = ()
        for option in (*left.abbreviation_options.get(token, ()), *right.abbreviation_options.get(token, ())):
            merged = _merge_abbreviation_option(merged, option)
        options[token] = merged
    return PosNamePreferenceProfile(
        abbreviations=abbreviations,
        abbreviation_options=options,
        spaced_overrides=left.spaced_overrides + right.spaced_overrides,
        compact_overrides=left.compact_overrides + right.compact_overrides,
    )


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
        "OldCategory",
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
            "OldCategory": row.old_category,
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
        "pos_name_preference_rules": _pos_preference_rules_payload(session.pos_preferences),
        "pos_name_style": {
            "spaced_overrides": session.pos_preferences.spaced_overrides,
            "compact_overrides": session.pos_preferences.compact_overrides,
        },
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


def _normalize_category_assignment_filter(value: str) -> CategoryAssignmentFilter:
    normalized = normalize_text(value)
    if normalized in {"has category", "assigned", "category assigned"}:
        return "assigned"
    if normalized in {"no category", "unassigned", "category unassigned", "no category assigned"}:
        return "unassigned"
    return "any"


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


def _barcode_filter_matches(barcode: str, barcode_filter: str) -> bool:
    if not barcode_filter:
        return True
    barcode_norm = normalize_text(barcode)
    if barcode_filter == "no barcode":
        return not barcode
    if barcode_filter == "vendor":
        return bool(barcode and "sagemb" not in barcode_norm)
    return barcode_filter in barcode_norm


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
    values = [part.strip() for part in current.split(";") if part.strip()]
    if reason and reason not in values:
        values.append(reason)
    return "; ".join(values)


def _title_token(token: str) -> str:
    if not token:
        return ""
    return token.upper() if token.isdigit() else token[:1].upper() + token[1:]
