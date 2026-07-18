from __future__ import annotations

import csv
import json
from pathlib import Path

from lunchtab_product_init.models import BuildInputs, LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.session_workflow import (
    ImportSession,
    SessionRow,
    apply_venue_profile,
    assign_category,
    delete_rows,
    export_session,
    filter_rows,
    filter_pos_rows,
    learn_pos_preferences,
    load_venue_profile,
    mark_for_edit,
    merge_rows,
    next_edit_row,
    no_barcode_rows,
    parse_barcodes,
    replace_pos_name,
    run_pos_generation,
    save_edit,
    save_venue_profile,
    suggest_pos_names,
)


def test_category_assignment_filters_and_marks_rows() -> None:
    session = _session(
        [
            _row("row-1", "Buffalo Ranch Chicken Sandwich", "6.50", "ABC"),
            _row("row-2", "Apple Juice", "1.25", "DEF"),
        ]
    )

    filtered = filter_rows(session, keyword="chicken", price_operator="range", price_value="5", price_upper="7")
    assert [row.row_id for row in filtered] == ["row-1"]

    session = assign_category(session, {"row-1"}, "Sandwiches")
    session = mark_for_edit(session, {"row-2"}, "operator review")

    assert session.category_names == ("Sandwiches",)
    assert session.rows[0].category == "Sandwiches"
    assert session.rows[1].status == "needs_edit"


def test_parse_barcodes_splits_trims_and_dedupes() -> None:
    assert parse_barcodes(" ABC, DEF ,ABC,, ghi ") == ("ABC", "DEF", "ghi")


def test_category_names_are_sorted_ascending() -> None:
    session = _session([])

    session = assign_category(session, {"row-1"}, "Sandwiches")
    session = assign_category(session, {"row-2"}, "Beverages")
    session = assign_category(session, {"row-3"}, "Snacks")

    assert session.category_names == ("Beverages", "Sandwiches", "Snacks")


def test_old_category_is_preserved_and_filterable() -> None:
    session = _session(
        [
            _row("row-1", "Chicken Sandwich", "6.50", "ABC", old_category="Entrees"),
            _row("row-2", "Apple Juice", "1.25", "DEF", old_category="Beverages"),
            _row("row-3", "Loose Item", "2.00", "GHI", old_category=""),
        ]
    )

    session = assign_category(session, {"row-1"}, "Sandwiches")

    assert session.rows[0].old_category == "Entrees"
    assert session.rows[0].category == "Sandwiches"
    assert [
        row.row_id for row in filter_rows(session, old_category="bev")
    ] == ["row-2"]
    assert [
        row.row_id for row in filter_rows(session, old_category="No category")
    ] == ["row-3"]


def test_category_filter_can_select_sagemb_or_vendor_barcodes() -> None:
    session = _session(
        [
            _row("row-1", "Sage Item", "1.00", "SAGEMB001"),
            _row("row-2", "Vendor Item", "2.00", "Vendor-ABC"),
            _row("row-3", "Numeric Item", "3.00", "12345"),
            _row("row-4", "No Barcode Item", "4.00", ""),
        ]
    )

    assert [
        row.row_id for row in filter_rows(session, barcode_filter="SAGEMB")
    ] == ["row-1"]
    assert [
        row.row_id for row in filter_rows(session, barcode_filter="Vendor")
    ] == ["row-2", "row-3"]


def test_duplicate_barcode_validation_splits_comma_separated_values() -> None:
    session = _session(
        [
            _row("row-1", "Primary Item", "1.00", "111,222", category="Snacks"),
            _row("row-2", "Duplicate Item", "2.00", "222", category="Snacks"),
            _row("row-3", "Clean Item", "3.00", "333,444", category="Snacks"),
        ]
    )

    session = save_edit(
        session,
        "row-1",
        item_name="Primary Item",
        price="1.00",
        barcode="111,222",
        category="Snacks",
    )

    assert [
        row.row_id for row in session.rows if "duplicate barcode" in row.review_reason
    ] == ["row-1", "row-2"]


def test_category_filter_can_select_rows_without_barcode() -> None:
    session = _session(
        [
            _row("row-1", "No Barcode Item", "1.00", ""),
            _row("row-2", "Sage Item", "2.00", "SAGEMB001"),
            _row("row-3", "Vendor Item", "3.00", "Vendor-ABC"),
        ]
    )

    assert [
        row.row_id for row in filter_rows(session, barcode_filter="No barcode")
    ] == ["row-1"]


def test_category_filter_can_select_assigned_or_unassigned_rows() -> None:
    session = _session(
        [
            _row("row-1", "Assigned Item", "1.00", "ABC", category="Entrees"),
            _row("row-2", "Blank Category Item", "2.00", "DEF", category=""),
            _row("row-3", "Whitespace Category Item", "3.00", "GHI", category="   "),
        ]
    )

    assert [
        row.row_id for row in filter_rows(session, category_assignment="Has category")
    ] == ["row-1"]
    assert [
        row.row_id for row in filter_rows(session, category_assignment="No category")
    ] == ["row-2", "row-3"]


def test_category_price_filter_supports_exact_comparison_and_range() -> None:
    session = _session(
        [
            _row("row-1", "Small Drink", "1.25", "ABC"),
            _row("row-2", "Large Drink", "2.00", "DEF"),
            _row("row-3", "Combo Meal", "6.50", "GHI"),
        ]
    )

    assert [row.row_id for row in filter_rows(session, price_operator="=", price_value="2.00")] == ["row-2"]
    assert [row.row_id for row in filter_rows(session, price_operator="<", price_value="2.00")] == ["row-1"]
    assert [row.row_id for row in filter_rows(session, price_operator=">=", price_value="2.00")] == ["row-2", "row-3"]
    assert [
        row.row_id
        for row in filter_rows(
            session,
            price_operator="range",
            price_value="1.25",
            price_upper="2.00",
        )
    ] == ["row-1", "row-2"]


def test_category_price_filter_can_show_rows_without_price() -> None:
    session = _session(
        [
            _row("row-1", "Blank Price", "", "ABC"),
            _row("row-2", "Invalid Price", "N/A", "DEF"),
            _row("row-3", "Priced Item", "2.00", "GHI"),
        ]
    )

    assert [
        row.row_id
        for row in filter_rows(session, price_operator="no_price")
    ] == ["row-1", "row-2"]


def test_edit_review_no_barcode_filter_select_delete_and_save_next() -> None:
    session = _session(
        [
            _row("row-1", "No Barcode Chips", "1.50", "", status="needs_edit"),
            _row("row-2", "No Barcode Cookie", "1.00", "", status="needs_edit"),
            _row("row-3", "Valid Drink", "2.00", "XYZ", status="needs_edit"),
        ]
    )

    selected = {row.row_id for row in no_barcode_rows(session)}
    assert selected == {"row-1", "row-2"}

    session = delete_rows(session, selected, "no barcode import cleanup")
    assert [row.row_id for row in session.deleted_rows] == ["row-1", "row-2"]
    assert next_edit_row(session).row_id == "row-3"  # type: ignore[union-attr]

    session = save_edit(
        session,
        "row-3",
        item_name="Valid Drink",
        price="2.00",
        barcode="XYZ",
        category="Beverages",
    )

    assert session.can_leave_edit_review
    assert next_edit_row(session) is None


def test_merge_rows_transfers_barcodes_deletes_sources_and_revalidates() -> None:
    session = _session(
        [
            _row("row-1", "Target Item", "1.00", "111", category="Snacks", status="needs_edit"),
            _row("row-2", "Source Item", "1.00", "222,333", category="Snacks", status="needs_edit"),
            _row("row-3", "Other Item", "1.00", "444", category="Snacks"),
        ]
    )

    session = merge_rows(session, "row-1", {"row-2"})
    target = next(row for row in session.rows if row.row_id == "row-1")
    source = next(row for row in session.rows if row.row_id == "row-2")

    assert target.barcode == "111,222,333"
    assert target.status == "edit_complete"
    assert target.edited
    assert source.status == "deleted"
    assert source.deleted_reason == "merged into row-1"
    assert "barcode transferred to row-1" in source.review_reason


def test_saving_one_edit_row_does_not_complete_other_operator_review_rows() -> None:
    session = _session(
        [
            _row("row-1", "Missing Price", "", "ABC", category="Snacks", status="needs_edit"),
            _row("row-2", "Missing Barcode", "2.00", "", category="Snacks", status="needs_edit"),
            *[
                _row(f"row-{index}", f"Review Item {index}", "1.00", f"BAR{index}", category="Snacks")
                for index in range(3, 13)
            ],
        ]
    )
    session = mark_for_edit(session, {f"row-{index}" for index in range(3, 13)})

    session = save_edit(
        session,
        "row-1",
        item_name="Missing Price",
        price="1.50",
        barcode="ABC",
        category="Snacks",
    )

    saved_row = next(row for row in session.rows if row.row_id == "row-1")
    assert saved_row.status == "edit_complete"
    assert [
        row.row_id for row in session.rows if row.status == "needs_edit"
    ] == ["row-2", *[f"row-{index}" for index in range(3, 13)]]
    assert len(session.edit_queue) == 11


def test_pos_generation_validation_override_learning_and_suggestions() -> None:
    session = _session(
        [
            _row("row-1", "Buffalo Ranch Chicken Sandwich", "6.50", "ABC", category="Sandwiches"),
            _row("row-2", "Chicken Caesar Salad", "5.25", "DEF", category="Salads"),
        ],
        categories=("Sandwiches", "Salads"),
    )

    session = run_pos_generation(session)
    assert all(row.pos_name for row in session.active_rows)

    session = replace_pos_name(session, "row-1", "Buff Rch Chk Sd")
    session = replace_pos_name(session, "row-2", "Buff Rch Chk Sd")
    assert {row.status for row in session.active_rows} == {"pos_needs_review"}

    session = replace_pos_name(session, "row-2", "Chick Cae Sal")
    assert session.can_leave_pos_review
    assert session.pos_preferences.abbreviations["chicken"] == "Chick"
    assert suggest_pos_names(session, "row-2")[0] == "Chick Cae Sal"


def test_pos_preferences_allow_context_specific_token_shortening() -> None:
    session = _session(
        [
            _row("row-1", "Chicken Caesar Salad", "5.25", "ABC", category="Salads"),
            _row("row-2", "SW Chicken Cobb Caesar", "6.25", "DEF", category="Sandwiches"),
        ],
        categories=("Salads", "Sandwiches"),
    )

    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "Chick Cae Sal")
    session = replace_pos_name(session, "row-2", "SW Chk Cobb Cae")

    assert suggest_pos_names(session, "row-1")[0] == "Chick Cae Sal"
    assert suggest_pos_names(session, "row-2")[0] == "SW Chk Cobb Cae"


def test_pos_preferences_learn_breakfast_sandwich_acronym_pattern() -> None:
    session = _session(
        [
            _row("row-1", "Bacon, Egg, and Cheese Bagel", "5.25", "ABC", category="Breakfast"),
            _row(
                "row-2",
                "Sausage Egg and Cheese English Muffin",
                "5.25",
                "DEF",
                category="Breakfast",
            ),
        ],
        categories=("Breakfast",),
    )

    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "BEC Bagel")

    assert suggest_pos_names(session, "row-2")[0] == "SEC Muff"


def test_pos_generation_does_not_overwrite_manual_overrides() -> None:
    session = _session(
        [
            _row("row-1", "Chicken Caesar Salad", "5.25", "ABC", category="Salads"),
            _row("row-2", "Chicken Caesar Wrap", "6.25", "DEF", category="Wraps"),
        ],
        categories=("Salads", "Wraps"),
    )

    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "Manual Name")
    session = replace_pos_name(session, "row-2", "Chick Cae Wrap")
    session = run_pos_generation(session)

    assert next(row for row in session.rows if row.row_id == "row-1").pos_name == "Manual Name"
    assert suggest_pos_names(session, "row-1")[0] != "Manual Name"


def test_pos_generation_preserves_reviewed_names_after_barcode_merge() -> None:
    session = _session(
        [
            _row("row-1", "Bacon, Egg, and Cheese Bagel", "5.25", "ABC", category="Breakfast"),
            _row("row-2", "Burrito Egg and Cheese Bagel", "5.25", "DEF", category="Breakfast"),
            _row("row-3", "Duplicate Barcode Source", "5.25", "GHI", category="Breakfast"),
        ],
        categories=("Breakfast",),
    )

    session = run_pos_generation(session)
    original_row_2_pos_name = next(row for row in session.rows if row.row_id == "row-2").pos_name
    session = replace_pos_name(session, "row-1", "BEC Bagel")
    assert session.can_leave_pos_review

    session = merge_rows(session, "row-2", {"row-3"})
    session = run_pos_generation(session)

    row_2 = next(row for row in session.rows if row.row_id == "row-2")
    assert row_2.pos_name == original_row_2_pos_name
    assert session.can_leave_pos_review


def test_pos_rows_can_filter_to_review_reason() -> None:
    session = _session(
        [
            _row("row-1", "Drink A", "1.00", "A", category="Beverages"),
            _row("row-2", "Drink B", "1.00", "B", category="Beverages"),
            _row("row-3", "Drink C", "1.00", "C", category="Beverages"),
        ]
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "Duplicate")
    session = replace_pos_name(session, "row-2", "Duplicate")

    assert [
        row.row_id for row in filter_pos_rows(session, "Needs review")
    ] == ["row-1", "row-2"]
    assert [
        row.row_id for row in filter_pos_rows(session, "duplicate")
    ] == ["row-1", "row-2"]


def test_export_excludes_deleted_rows_and_writes_audits(tmp_path: Path) -> None:
    source_template, recipe, odin = _source_files(tmp_path)
    session = _session(
        [
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "ABC",
                category="Beverages",
                old_category="Drinks",
                pos_name="AppleJuice",
            ),
            _row("row-2", "Deleted Chips", "1.00", "", status="deleted"),
        ],
        categories=("Beverages",),
    )

    result = export_session(
        session,
        BuildInputs(
            product_template_path=source_template,
            recipe_list_path=recipe,
            odin_inventory_path=odin,
            output_root=tmp_path / "out",
        ),
        is_orderable=True,
    )

    with result.summary.output_paths.final_import.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["BaseProductName"] == "Apple Juice"
    assert rows[0]["IsOrderable"] == "true"
    assert rows[0]["ProductCategories"] == "Beverages;"

    with result.summary.output_paths.deleted_audit.open(encoding="utf-8-sig", newline="") as file:
        deleted = list(csv.DictReader(file))
    assert deleted[0]["ItemName"] == "Deleted Chips"

    with result.summary.output_paths.category_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert audit_rows[0]["OldCategory"] == "Drinks"


def test_venue_profile_saves_categories_and_pos_preferences(tmp_path: Path) -> None:
    preferences = learn_pos_preferences(_session([]).pos_preferences, "Chicken Caesar Salad", "Chick Cae Sal")
    session = _session([], categories=("Salads",), preferences=preferences)

    path = tmp_path / "venue-profile.json"
    save_venue_profile(session, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["categories"] == ["Salads"]
    assert payload["pos_name_preferences"]["chicken"] == "Chick"
    assert payload["pos_name_preference_rules"]["chicken"][0]["value"] == "Chick"
    assert payload["pos_name_style"]["spaced_overrides"] == 1

    profile = load_venue_profile(path)
    seeded = apply_venue_profile(_session([]), profile)
    assert seeded.category_names == ("Salads",)
    assert seeded.pos_preferences.abbreviations["chicken"] == "Chick"
    assert seeded.pos_preferences.abbreviation_options["chicken"][0].value == "Chick"


def test_venue_profile_saves_breakfast_acronym_rules(tmp_path: Path) -> None:
    session = _session(
        [
            _row("row-1", "Bacon, Egg, and Cheese Bagel", "5.25", "ABC", category="Breakfast"),
            _row(
                "row-2",
                "Sausage Egg and Cheese English Muffin",
                "5.25",
                "DEF",
                category="Breakfast",
            ),
        ],
        categories=("Breakfast",),
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "BEC Bagel")

    path = tmp_path / "venue-profile.json"
    save_venue_profile(session, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pos_name_acronym_rules"][0]["suffix_tokens"] == ["egg", "cheese"]

    profile = load_venue_profile(path)
    seeded = apply_venue_profile(_session([session.rows[1]]), profile)
    assert suggest_pos_names(seeded, "row-2")[0] == "SEC Muff"


def _session(
    rows: list[SessionRow],
    *,
    categories: tuple[str, ...] = (),
    preferences=None,
) -> ImportSession:
    kwargs = {}
    if preferences is not None:
        kwargs["pos_preferences"] = preferences
    return ImportSession(headers=list(LUNCHTAB_TEMPLATE_HEADERS), rows=tuple(rows), category_names=categories, **kwargs)


def _row(
    row_id: str,
    name: str,
    price: str,
    barcode: str,
    *,
    category: str = "",
    old_category: str = "",
    pos_name: str = "",
    status: str = "active",
) -> SessionRow:
    return SessionRow(
        row_id=row_id,
        candidate=ProductCandidate(
            source="test",
            source_key=row_id,
            item_name=name,
            price=price,
            barcode=barcode,
            category=old_category or category,
        ),
        old_category=old_category or category,
        category=category,
        pos_name=pos_name,
        status=status,  # type: ignore[arg-type]
    )


def _source_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    template = tmp_path / "ProductData.csv"
    _write_csv(template, [], list(LUNCHTAB_TEMPLATE_HEADERS))
    recipe = tmp_path / "recipe.csv"
    _write_csv(recipe, [], ["Menu Item Name", "Price", "Barcode"])
    odin = tmp_path / "odin.xlsx"
    odin.write_bytes(b"placeholder")
    return template, recipe, odin


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
