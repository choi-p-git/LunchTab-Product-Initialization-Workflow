from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from lunchtab_product_init.models import BuildInputs, LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.session_workflow import (
    ImportSession,
    SessionRow,
    apply_venue_profile,
    assign_category,
    delete_pos_abbreviation_preference,
    delete_pos_acronym_preference,
    delete_rows,
    duplicate_name_edit_rows,
    export_session,
    filter_final_rows,
    filter_rows,
    filter_pos_rows,
    final_rows,
    final_review_metadata,
    learn_pos_preferences,
    load_venue_profile,
    mark_for_edit,
    merge_rows,
    next_edit_row,
    no_barcode_rows,
    ordered_final_session_rows,
    prepare_edit_review,
    parse_barcodes,
    parse_sources,
    replace_pos_name,
    promote_pos_abbreviation_preference,
    run_pos_generation,
    save_edit,
    save_final_review_edit,
    save_venue_profile,
    suggest_pos_names,
    upsert_pos_abbreviation_preference,
    validate_edit_name_for_row,
    validate_final_review_edit,
    validate_pos_name_for_row,
)


def test_category_assignment_filters_and_marks_rows() -> None:
    session = _session(
        [
            _row("row-1", "Buffalo Ranch Chicken Sandwich", "6.50", "ABC"),
            _row("row-2", "Apple Juice", "1.25", "DEF"),
        ]
    )

    filtered = filter_rows(
        session, keyword="chicken", price_operator="range", price_value="5", price_upper="7"
    )
    assert [row.row_id for row in filtered] == ["row-1"]

    session = assign_category(session, {"row-1"}, "Sandwiches")
    session = mark_for_edit(session, {"row-2"}, "operator review")

    assert session.category_names == ("Sandwiches",)
    assert session.rows[0].category == "Sandwiches"
    assert session.rows[1].status == "needs_edit"


def test_category_assignment_clears_stale_missing_category_reason() -> None:
    session = _session(
        [
            _row(
                "row-1",
                "No Barcode Item",
                "1.00",
                "",
                status="needs_edit",
                review_reason="missing barcode; missing category",
            )
        ]
    )

    session = assign_category(session, {"row-1"}, "Snacks")

    row = session.rows[0]
    assert row.category == "Snacks"
    assert row.status == "needs_edit"
    assert row.review_reason == "missing barcode"


def test_parse_barcodes_splits_trims_and_dedupes() -> None:
    assert parse_barcodes(" ABC, DEF ,ABC,, ghi ") == ("ABC", "DEF", "ghi")


def test_parse_sources_allows_recipe_only_without_inventory(tmp_path: Path) -> None:
    template = tmp_path / "ProductData.csv"
    recipe = tmp_path / "recipe.csv"
    _write_csv(template, [], list(LUNCHTAB_TEMPLATE_HEADERS))
    _write_csv(
        recipe,
        [{"Menu Item Name": "Apple Juice", "Price": "$1.25", "Barcode": " SAGEMB111 "}],
        ["Menu Item Name", "Price", "Barcode"],
    )

    session = parse_sources(
        BuildInputs(
            product_template_path=template,
            recipe_list_path=recipe,
            output_root=tmp_path / "out",
        )
    )

    assert len(session.rows) == 1
    assert session.rows[0].candidate.source == "recipe"
    assert session.rows[0].candidate.item_name == "Apple Juice"
    assert session.rows[0].candidate.price == "1.25"
    assert session.rows[0].candidate.barcode == "SAGEMB111"
    assert session.rows[0].old_category == ""


def test_parse_sources_can_merge_generic_inventory_csv(tmp_path: Path) -> None:
    template = tmp_path / "ProductData.csv"
    recipe = tmp_path / "recipe.csv"
    inventory = tmp_path / "inventory.csv"
    _write_csv(template, [], list(LUNCHTAB_TEMPLATE_HEADERS))
    _write_csv(
        recipe,
        [{"Menu Item Name": "Apple Juice", "Price": "", "Barcode": "111"}],
        ["Menu Item Name", "Price", "Barcode"],
    )
    _write_csv(
        inventory,
        [
            {
                "Item Name": "Apple Juice Retail",
                "Price": "1.25",
                "Category": "Beverages",
                "Barcode": "111",
                "Stock": "5",
            }
        ],
        ["Item Name", "Price", "Category", "Barcode", "Stock"],
    )

    session = parse_sources(
        BuildInputs(
            product_template_path=template,
            recipe_list_path=recipe,
            output_root=tmp_path / "out",
            generic_inventory_path=inventory,
        )
    )

    assert len(session.rows) == 1
    row = session.rows[0]
    assert row.candidate.source == "recipe+inventory"
    assert row.candidate.item_name == "Apple Juice"
    assert row.candidate.price == "1.25"
    assert row.candidate.category == "Beverages"
    assert row.candidate.stock == "5"
    assert row.old_category == "Beverages"


def test_parse_sources_rejects_multiple_inventory_sources(tmp_path: Path) -> None:
    template = tmp_path / "ProductData.csv"
    recipe = tmp_path / "recipe.csv"
    _write_csv(template, [], list(LUNCHTAB_TEMPLATE_HEADERS))
    _write_csv(recipe, [], ["Menu Item Name", "Price", "Barcode"])

    with pytest.raises(ValueError, match="either Odin inventory or generic inventory"):
        parse_sources(
            BuildInputs(
                product_template_path=template,
                recipe_list_path=recipe,
                output_root=tmp_path / "out",
                odin_inventory_path=tmp_path / "inventory.xlsx",
                generic_inventory_path=tmp_path / "inventory.csv",
            )
        )


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
    assert [row.row_id for row in filter_rows(session, old_category="bev")] == ["row-2"]
    assert [row.row_id for row in filter_rows(session, old_category="No category")] == ["row-3"]


def test_category_filter_can_group_duplicate_item_names() -> None:
    session = _session(
        [
            _row("row-1", "Z Drink", "1.00", "A"),
            _row("row-2", "Apple Juice", "1.00", "B"),
            _row("row-3", "z drink", "1.25", "C"),
            _row("row-4", "Banana", "1.00", "D"),
            _row("row-5", "Apple  Juice", "1.50", "E"),
        ]
    )

    assert [row.row_id for row in filter_rows(session, name_filter="Duplicate name")] == [
        "row-2",
        "row-5",
        "row-1",
        "row-3",
    ]


def test_category_filters_compose_for_duplicate_vendor_uncategorized_rows() -> None:
    session = _session(
        [
            _row("row-1", "Apple Juice", "1.00", "SAGEMB001", category="Beverages"),
            _row("row-2", "Apple  Juice", "1.50", "VENDOR-001", old_category="Beverages"),
            _row("row-3", "Orange Juice", "1.50", "VENDOR-002"),
            _row("row-4", "apple juice", "2.50", "VENDOR-003"),
            _row("row-5", "Loose Apple Juice", "", ""),
        ]
    )

    assert [
        row.row_id
        for row in filter_rows(
            session,
            keyword="juice",
            name_filter="Duplicate name",
            barcode_filter="Vendor",
            category_assignment="No category",
            price_operator="range",
            price_value="1.00",
            price_upper="2.00",
        )
    ] == ["row-2"]


def test_category_filter_can_select_sagemb_or_vendor_barcodes() -> None:
    session = _session(
        [
            _row("row-1", "Sage Item", "1.00", "SAGEMB001"),
            _row("row-2", "Vendor Item", "2.00", "Vendor-ABC"),
            _row("row-3", "Numeric Item", "3.00", "12345"),
            _row("row-4", "No Barcode Item", "4.00", ""),
        ]
    )

    assert [row.row_id for row in filter_rows(session, barcode_filter="SAGEMB")] == ["row-1"]
    assert [row.row_id for row in filter_rows(session, barcode_filter="Vendor")] == [
        "row-2",
        "row-3",
    ]


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

    assert [row.row_id for row in session.rows if "duplicate barcode" in row.review_reason] == [
        "row-1",
        "row-2",
    ]


def test_deleting_duplicate_barcode_row_refreshes_surviving_rows() -> None:
    session = _session(
        [
            _row("row-1", "Primary Item", "1.00", "111,222", category="Snacks"),
            _row("row-2", "Duplicate Item", "2.00", "222", category="Snacks"),
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
    assert "duplicate barcode" in session.rows[0].review_reason

    session = delete_rows(session, {"row-2"})

    row_1 = next(row for row in session.rows if row.row_id == "row-1")
    assert row_1.status == "edit_complete"
    assert "duplicate barcode" not in row_1.review_reason


def test_deleting_row_preserves_uncategorized_active_rows_in_category_step() -> None:
    session = _session(
        [
            _row("row-1", "Apple Juice", "1.00", "ABC"),
            _row("row-2", "Orange Juice", "1.50", "DEF"),
            _row("row-3", "Missing Barcode", "2.00", "", status="needs_edit"),
        ]
    )

    session = delete_rows(session, {"row-1"})

    row_2 = next(row for row in session.rows if row.row_id == "row-2")
    row_3 = next(row for row in session.rows if row.row_id == "row-3")

    assert row_2.status == "active"
    assert row_2.review_reason == ""
    assert row_3.status == "needs_edit"
    assert row_3.review_reason == "missing barcode; missing category"


def test_delete_refresh_preserves_operator_review_rows_in_edit_queue() -> None:
    session = _session(
        [
            _row("row-1", "Review Juice", "1.00", "ABC", category="Beverages"),
            _row("row-2", "Review Snack", "1.50", "DEF", category="Snacks"),
            _row("row-3", "Deleted Row", "2.00", "GHI", category="Snacks"),
        ]
    )
    session = mark_for_edit(session, {"row-1", "row-2"})

    session = delete_rows(session, {"row-3"})

    assert [(row.row_id, row.status, row.review_reason) for row in session.edit_queue] == [
        ("row-1", "needs_edit", "operator review"),
        ("row-2", "needs_edit", "operator review"),
    ]


def test_category_filter_can_select_rows_without_barcode() -> None:
    session = _session(
        [
            _row("row-1", "No Barcode Item", "1.00", ""),
            _row("row-2", "Sage Item", "2.00", "SAGEMB001"),
            _row("row-3", "Vendor Item", "3.00", "Vendor-ABC"),
        ]
    )

    assert [row.row_id for row in filter_rows(session, barcode_filter="No barcode")] == ["row-1"]


def test_category_filter_can_select_assigned_or_unassigned_rows() -> None:
    session = _session(
        [
            _row("row-1", "Assigned Item", "1.00", "ABC", category="Entrees"),
            _row("row-2", "Blank Category Item", "2.00", "DEF", category=""),
            _row("row-3", "Whitespace Category Item", "3.00", "GHI", category="   "),
        ]
    )

    assert [row.row_id for row in filter_rows(session, category_assignment="Has category")] == [
        "row-1"
    ]
    assert [row.row_id for row in filter_rows(session, category_assignment="No category")] == [
        "row-2",
        "row-3",
    ]


def test_category_price_filter_supports_exact_comparison_and_range() -> None:
    session = _session(
        [
            _row("row-1", "Small Drink", "1.25", "ABC"),
            _row("row-2", "Large Drink", "2.00", "DEF"),
            _row("row-3", "Combo Meal", "6.50", "GHI"),
        ]
    )

    assert [row.row_id for row in filter_rows(session, price_operator="=", price_value="2.00")] == [
        "row-2"
    ]
    assert [row.row_id for row in filter_rows(session, price_operator="<", price_value="2.00")] == [
        "row-1"
    ]
    assert [
        row.row_id for row in filter_rows(session, price_operator=">=", price_value="2.00")
    ] == ["row-2", "row-3"]
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

    assert [row.row_id for row in filter_rows(session, price_operator="no_price")] == [
        "row-1",
        "row-2",
    ]


def test_category_stock_filter_supports_inventory_stock_values_only() -> None:
    session = _session(
        [
            _row("row-1", "Recipe Only", "1.00", "AAA", source="recipe"),
            _row("row-2", "No Stock Inventory", "1.00", "BBB", source="inventory", stock=""),
            _row("row-3", "Zero Stock Inventory", "1.00", "CCC", source="inventory", stock="0"),
            _row("row-4", "Low Stock Inventory", "1.00", "DDD", source="inventory", stock="3"),
            _row("row-5", "High Stock Inventory", "1.00", "EEE", source="inventory", stock="12"),
        ]
    )

    assert [row.row_id for row in filter_rows(session, stock_operator="no_stock")] == ["row-2"]
    assert [row.row_id for row in filter_rows(session, stock_operator="=", stock_value="0")] == [
        "row-3"
    ]
    assert [row.row_id for row in filter_rows(session, stock_operator="<", stock_value="5")] == [
        "row-3",
        "row-4",
    ]
    assert [row.row_id for row in filter_rows(session, stock_operator="<=", stock_value="3")] == [
        "row-3",
        "row-4",
    ]
    assert [row.row_id for row in filter_rows(session, stock_operator=">=", stock_value="3")] == [
        "row-4",
        "row-5",
    ]
    assert [
        row.row_id
        for row in filter_rows(
            session,
            stock_operator="range",
            stock_value="1",
            stock_upper="10",
        )
    ] == ["row-4"]


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


def test_edit_review_duplicate_name_filter_groups_duplicate_names() -> None:
    session = _session(
        [
            _row("row-1", "Orange Juice", "1.00", "111", category="Beverages", status="needs_edit"),
            _row("row-2", "Apple Juice", "1.00", "222", category="Beverages", status="needs_edit"),
            _row("row-3", "Orange Juice", "1.50", "333", category="Beverages", status="needs_edit"),
            _row("row-4", "Single Item", "2.00", "444", category="Snacks", status="needs_edit"),
            _row("row-5", "apple juice", "1.25", "555", category="Beverages", status="needs_edit"),
            _row("row-6", "Orange Juice", "1.75", "666", category="Beverages"),
        ]
    )

    assert [row.row_id for row in duplicate_name_edit_rows(session)] == [
        "row-2",
        "row-5",
        "row-1",
        "row-3",
    ]


def test_prepare_edit_review_marks_duplicate_names_for_manual_review() -> None:
    session = _session(
        [
            _row("row-1", "Orange Juice", "1.00", "111", category="Beverages"),
            _row("row-2", "orange juice", "1.50", "222", category="Beverages"),
            _row("row-3", "Single Item", "2.00", "333", category="Snacks"),
        ]
    )

    session = prepare_edit_review(session)

    assert [(row.row_id, row.status, row.review_reason) for row in session.rows] == [
        ("row-1", "needs_edit", "duplicate name"),
        ("row-2", "needs_edit", "duplicate name"),
        ("row-3", "active", ""),
    ]


def test_duplicate_name_review_can_be_approved_without_name_change() -> None:
    session = _session(
        [
            _row("row-1", "Orange Juice", "1.00", "111", category="Beverages"),
            _row("row-2", "orange juice", "1.50", "222", category="Beverages"),
        ]
    )
    session = prepare_edit_review(session)

    session = save_edit(
        session,
        "row-1",
        item_name="Orange Juice",
        price="1.00",
        barcode="111",
        category="Beverages",
    )

    row_1 = next(row for row in session.rows if row.row_id == "row-1")
    row_2 = next(row for row in session.rows if row.row_id == "row-2")

    assert row_1.status == "edit_complete"
    assert row_1.review_reason == ""
    assert row_1.edited
    assert row_2.status == "needs_edit"
    assert row_2.review_reason == "duplicate name"
    assert [row.row_id for row in duplicate_name_edit_rows(session)] == ["row-2"]


def test_duplicate_name_review_rename_rechecks_and_clears_resolved_pair() -> None:
    session = _session(
        [
            _row("row-1", "Orange Juice", "1.00", "111", category="Beverages"),
            _row("row-2", "orange juice", "1.50", "222", category="Beverages"),
        ]
    )
    session = prepare_edit_review(session)

    session = save_edit(
        session,
        "row-1",
        item_name="Apple Juice",
        price="1.00",
        barcode="111",
        category="Beverages",
    )

    assert [(row.row_id, row.item_name, row.status, row.review_reason) for row in session.rows] == [
        ("row-1", "Apple Juice", "edit_complete", ""),
        ("row-2", "orange juice", "edit_complete", ""),
    ]
    assert duplicate_name_edit_rows(session) == ()


def test_duplicate_name_review_rename_rechecks_and_flags_new_collision() -> None:
    session = _session(
        [
            _row("row-1", "Orange Juice", "1.00", "111", category="Beverages"),
            _row("row-2", "orange juice", "1.50", "222", category="Beverages"),
            _row("row-3", "Apple Juice", "2.00", "333", category="Beverages"),
        ]
    )
    session = prepare_edit_review(session)

    session = save_edit(
        session,
        "row-1",
        item_name="Apple Juice",
        price="1.00",
        barcode="111",
        category="Beverages",
    )

    assert [(row.row_id, row.item_name, row.status, row.review_reason) for row in session.rows] == [
        ("row-1", "Apple Juice", "needs_edit", "duplicate name"),
        ("row-2", "orange juice", "edit_complete", ""),
        ("row-3", "Apple Juice", "needs_edit", "duplicate name"),
    ]
    assert [row.row_id for row in duplicate_name_edit_rows(session)] == ["row-1", "row-3"]


def test_edit_name_validation_rejects_new_duplicate_but_allows_unchanged_duplicate_review() -> None:
    session = _session(
        [
            _row("row-1", "Orange Juice", "1.00", "111", category="Beverages"),
            _row("row-2", "orange juice", "1.50", "222", category="Beverages"),
            _row("row-3", "Apple Juice", "2.00", "333", category="Beverages"),
        ]
    )
    session = prepare_edit_review(session)

    assert validate_edit_name_for_row(session, "row-1", "Orange Juice") == []
    assert validate_edit_name_for_row(session, "row-1", "Apple Juice") == ["duplicate item name"]


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
    assert source.merge_target_row_id == "row-1"
    assert source.merge_transferred_barcodes == "222,333"
    assert source.merge_target_barcode_before == "111"
    assert source.merge_target_barcode_after == "111,222,333"
    assert source.merge_action_timestamp
    datetime.fromisoformat(source.merge_action_timestamp)
    assert "barcode transferred to row-1" in source.review_reason


def test_saving_one_edit_row_does_not_complete_other_operator_review_rows() -> None:
    session = _session(
        [
            _row("row-1", "Missing Price", "", "ABC", category="Snacks", status="needs_edit"),
            _row("row-2", "Missing Barcode", "2.00", "", category="Snacks", status="needs_edit"),
            *[
                _row(
                    f"row-{index}", f"Review Item {index}", "1.00", f"BAR{index}", category="Snacks"
                )
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
    assert [row.row_id for row in session.rows if row.status == "needs_edit"] == [
        "row-2",
        *[f"row-{index}" for index in range(3, 13)],
    ]
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


def test_pos_override_tracks_edit_amount_and_effort_bands() -> None:
    session = _session(
        [
            _row("row-1", "Light Edit", "1.00", "111", category="Snacks", pos_name="AppleJuic"),
            _row(
                "row-2",
                "Moderate Edit",
                "1.00",
                "222",
                category="Snacks",
                pos_name="Chik Caesr",
            ),
            _row(
                "row-3",
                "Heavy Edit",
                "1.00",
                "333",
                category="Snacks",
                pos_name="LongGenerated",
            ),
        ],
        categories=("Snacks",),
    )

    session = replace_pos_name(session, "row-1", "AppleJuice")
    session = replace_pos_name(session, "row-2", "Chick Cae Sal")
    session = replace_pos_name(session, "row-3", "Manual Name")

    row_1 = next(row for row in session.rows if row.row_id == "row-1")
    row_2 = next(row for row in session.rows if row.row_id == "row-2")
    row_3 = next(row for row in session.rows if row.row_id == "row-3")

    assert row_1.pos_name_before_override == "AppleJuic"
    assert row_1.pos_edit_distance == 1
    assert row_1.pos_character_delta == 1
    assert row_1.pos_spaces_changed == 0
    assert row_1.pos_token_changes == 1
    assert row_1.pos_active_edit_actions == 1
    assert row_1.pos_edit_effort == "light"

    assert row_2.pos_edit_distance == 5
    assert row_2.pos_character_delta == 3
    assert row_2.pos_spaces_changed == 1
    assert row_2.pos_token_changes == 3
    assert row_2.pos_edit_effort == "moderate"

    assert row_3.pos_edit_distance > 5
    assert row_3.pos_edit_effort == "heavy"


def test_pos_suggestions_exclude_names_that_fail_validation() -> None:
    session = _session(
        [
            _row("row-1", "Apple Juice", "1.00", "A", category="Beverages", pos_name="Apple Juice"),
            _row("row-2", "Apple Juice", "1.00", "B", category="Beverages"),
        ]
    )

    assert "Apple Juice" not in suggest_pos_names(session, "row-2")


def test_pos_validation_checks_replacement_value_for_current_row() -> None:
    session = _session(
        [
            _row("row-1", "Apple Juice", "1.00", "A", category="Beverages", pos_name="Apple Juice"),
            _row("row-2", "Orange Juice", "1.00", "B", category="Beverages", pos_name=""),
        ]
    )

    assert validate_pos_name_for_row(session, "row-2", "Apple Juice") == ["duplicate POS name"]
    assert validate_pos_name_for_row(session, "row-2", "Orange Juice") == []


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


def test_pos_preferences_decay_same_context_mistaken_association() -> None:
    session = _session(
        [_row("row-1", "Chicken Caesar Salad", "5.25", "ABC", category="Salads")],
        categories=("Salads",),
    )
    session = run_pos_generation(session)

    session = replace_pos_name(session, "row-1", "Chk Cae Sal")
    session = replace_pos_name(session, "row-1", "Chick Cae Sal")

    chicken_options = session.pos_preferences.abbreviation_options["chicken"]

    assert session.pos_preferences.abbreviations["chicken"] == "Chick"
    assert [option.value for option in chicken_options] == ["Chick"]
    assert suggest_pos_names(session, "row-1")[0] == "Chick Cae Sal"


def test_pos_preferences_preserve_context_specific_variants() -> None:
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

    chicken_options = session.pos_preferences.abbreviation_options["chicken"]

    assert {option.value for option in chicken_options} == {"Chick", "Chk"}
    assert suggest_pos_names(session, "row-1")[0] == "Chick Cae Sal"
    assert suggest_pos_names(session, "row-2")[0] == "SW Chk Cobb Cae"


def test_pos_suggestions_reserve_third_slot_for_second_ranked_pattern() -> None:
    session = _session(
        [_row("row-1", "Chicken Caesar Salad", "5.25", "ABC", category="Salads")],
        categories=("Salads",),
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "Chick Cae Sal")
    session = replace_pos_name(session, "row-1", "Chick Cae Sal")
    session = replace_pos_name(session, "row-1", "Chk Cae Sal")

    suggestions = suggest_pos_names(session, "row-1")

    assert suggestions[:3] == ("Chick Cae Sal", "ChickCaeSal", "Chk Cae Sal")


def test_pos_preference_profile_rules_can_be_edited_and_redirected() -> None:
    session = _session(
        [_row("row-1", "Chicken", "5.25", "ABC", category="Salads")],
        categories=("Salads",),
    )
    session = run_pos_generation(session)

    session = upsert_pos_abbreviation_preference(
        session,
        token="Chicken",
        value="Chx",
        count=3,
        source_token_count=3,
        example="Chx Cae Sal",
    )
    assert session.pos_preferences.abbreviations["chicken"] == "Chx"
    assert suggest_pos_names(session, "row-1")[0] == "Chx"

    session = upsert_pos_abbreviation_preference(session, token="Chicken", value="Chick", count=1)
    session = promote_pos_abbreviation_preference(session, token="chicken", value="Chick")
    assert session.pos_preferences.abbreviations["chicken"] == "Chick"
    assert suggest_pos_names(session, "row-1")[0] == "Chick"

    session = delete_pos_abbreviation_preference(session, token="chicken", value="Chick")
    assert session.pos_preferences.abbreviations["chicken"] == "Chx"

    session = delete_pos_abbreviation_preference(session, token="chicken")
    assert "chicken" not in session.pos_preferences.abbreviation_options
    assert "chicken" not in session.pos_preferences.abbreviations


def test_pos_profile_acronym_patterns_can_be_removed() -> None:
    session = _session(
        [_row("row-1", "Bacon Egg and Cheese Bagel", "5.25", "ABC", category="Breakfast")],
        categories=("Breakfast",),
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "BEC Bagel")

    assert session.pos_preferences.acronym_patterns

    pattern = session.pos_preferences.acronym_patterns[0]
    session = delete_pos_acronym_preference(
        session,
        suffix_tokens=pattern.suffix_tokens,
        span_length=pattern.span_length,
    )

    assert session.pos_preferences.acronym_patterns == ()


def test_pos_suggestions_condense_long_names_to_valid_candidates() -> None:
    session = _session(
        [
            _row(
                "row-1",
                "Buffalo Ranch Chicken Sandwich",
                "6.50",
                "ABC",
                category="Sandwiches",
            ),
            _row(
                "row-2",
                "Southwest Buffalo Ranch Chicken Sandwich Combo Meal",
                "8.50",
                "DEF",
                category="Sandwiches",
            ),
        ],
        categories=("Sandwiches",),
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "Buff Rch Chk Sd")

    suggestions = suggest_pos_names(session, "row-2")

    assert suggestions
    assert all(len(suggestion) <= 15 for suggestion in suggestions)
    assert any("Chk" in suggestion for suggestion in suggestions)


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

    assert [row.row_id for row in filter_pos_rows(session, "Needs review")] == ["row-1", "row-2"]
    assert [row.row_id for row in filter_pos_rows(session, "duplicate")] == ["row-1", "row-2"]


def test_deleting_duplicate_pos_row_refreshes_surviving_rows() -> None:
    session = _session(
        [
            _row("row-1", "Drink A", "1.00", "A", category="Beverages"),
            _row("row-2", "Drink B", "1.00", "B", category="Beverages"),
        ]
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "Duplicate")
    session = replace_pos_name(session, "row-2", "Duplicate")
    assert not session.can_export

    session = delete_rows(session, {"row-2"})

    row_1 = next(row for row in session.rows if row.row_id == "row-1")
    assert row_1.status == "pos_ready"
    assert "duplicate POS name" not in row_1.review_reason
    assert session.can_export


def test_back_edit_merge_delete_preserves_reviewed_pos_names_and_refreshes_export_state() -> None:
    session = _session(
        [
            _row("row-1", "Bacon, Egg, and Cheese Bagel", "5.25", "111", category="Breakfast"),
            _row(
                "row-2",
                "Sausage Egg and Cheese English Muffin",
                "5.25",
                "222",
                category="Breakfast",
            ),
            _row(
                "row-3",
                "Sausage Egg and Cheese English Muffin",
                "5.25",
                "333",
                category="Breakfast",
            ),
            _row("row-4", "Duplicate POS Source", "1.00", "444", category="Snacks"),
        ],
        categories=("Breakfast", "Snacks"),
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "BEC Bagel")
    session = replace_pos_name(session, "row-2", "SEC Muff")
    session = replace_pos_name(session, "row-3", "SEC Muffin")
    session = replace_pos_name(session, "row-4", "Quick Snack")
    assert session.can_export

    session = merge_rows(session, "row-2", {"row-3"})
    session = delete_rows(session, {"row-4"})
    session = run_pos_generation(session)

    row_1 = next(row for row in session.rows if row.row_id == "row-1")
    row_2 = next(row for row in session.rows if row.row_id == "row-2")
    row_3 = next(row for row in session.rows if row.row_id == "row-3")
    row_4 = next(row for row in session.rows if row.row_id == "row-4")
    metadata = final_review_metadata(session)

    assert row_1.pos_name == "BEC Bagel"
    assert row_2.pos_name == "SEC Muff"
    assert row_2.barcode == "222,333"
    assert row_2.status == "pos_ready"
    assert row_3.status == "deleted"
    assert row_3.deleted_reason == "merged into row-2"
    assert row_4.status == "deleted"
    assert session.can_export
    assert metadata.export_ready
    assert metadata.active_rows == 2
    assert metadata.deleted_rows == 2
    assert metadata.merge_rows == 1


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
    )

    with result.summary.output_paths.final_import.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["BaseProductName"] == "Apple Juice"
    assert rows[0]["IsPublished"] == "false"
    assert rows[0]["IsOrderable"] == "false"
    assert rows[0]["ProductCategories"] == "Beverages;"

    with result.summary.output_paths.deleted_audit.open(encoding="utf-8-sig", newline="") as file:
        deleted = list(csv.DictReader(file))
    assert deleted[0]["ItemName"] == "Deleted Chips"
    assert "MergeTargetRowId" in deleted[0]

    with result.summary.output_paths.category_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert audit_rows[0]["OldCategory"] == "Drinks"


def test_final_rows_are_grouped_by_category_then_name() -> None:
    session = _session(
        [
            _row("row-1", "Zebra Snack", "1.25", "111", category="Snacks", pos_name="ZebraSnack"),
            _row(
                "row-2", "Apple Drink", "1.50", "222", category="Beverages", pos_name="AppleDrink"
            ),
            _row(
                "row-3", "Banana Drink", "1.75", "333", category="Beverages", pos_name="BananaDrink"
            ),
            _row("row-4", "Apple Snack", "2.00", "444", category="Snacks", pos_name="AppleSnack"),
        ],
        categories=("Beverages", "Snacks"),
    )

    assert [row.row_id for row in ordered_final_session_rows(session)] == [
        "row-2",
        "row-3",
        "row-4",
        "row-1",
    ]
    assert [(row["ProductCategories"], row["BaseProductName"]) for row in final_rows(session)] == [
        ("Beverages;", "Apple Drink"),
        ("Beverages;", "Banana Drink"),
        ("Snacks;", "Apple Snack"),
        ("Snacks;", "Zebra Snack"),
    ]


def test_export_sorts_final_import_but_preserves_session_audit_order(tmp_path: Path) -> None:
    source_template, recipe, odin = _source_files(tmp_path)
    session = _session(
        [
            _row("row-1", "Zebra Snack", "1.25", "111", category="Snacks", pos_name="ZebraSnack"),
            _row(
                "row-2", "Apple Drink", "1.50", "222", category="Beverages", pos_name="AppleDrink"
            ),
            _row("row-3", "Apple Snack", "2.00", "333", category="Snacks", pos_name="AppleSnack"),
        ],
        categories=("Beverages", "Snacks"),
    )

    result = export_session(
        session,
        BuildInputs(
            product_template_path=source_template,
            recipe_list_path=recipe,
            odin_inventory_path=odin,
            output_root=tmp_path / "out",
        ),
    )

    with result.summary.output_paths.final_import.open(encoding="utf-8-sig", newline="") as file:
        final_import = list(csv.DictReader(file))
    with result.summary.output_paths.session_audit.open(encoding="utf-8-sig", newline="") as file:
        session_audit = list(csv.DictReader(file))

    assert [row["BaseProductName"] for row in final_import] == [
        "Apple Drink",
        "Apple Snack",
        "Zebra Snack",
    ]
    assert [row["RowId"] for row in session_audit] == ["row-1", "row-2", "row-3"]


def test_export_includes_pos_edit_effort_metrics(tmp_path: Path) -> None:
    source_template, recipe, odin = _source_files(tmp_path)
    session = _session(
        [
            _row("row-1", "Apple Juice", "1.25", "111", category="Beverages", pos_name="AppleJuic"),
            _row(
                "row-2",
                "Chicken Caesar Salad",
                "5.25",
                "222",
                category="Salads",
                pos_name="GeneratedName",
            ),
        ],
        categories=("Beverages", "Salads"),
    )
    session = replace_pos_name(session, "row-1", "AppleJuice")
    session = replace_pos_name(session, "row-2", "Chick Cae Sal")

    result = export_session(
        session,
        BuildInputs(
            product_template_path=source_template,
            recipe_list_path=recipe,
            odin_inventory_path=odin,
            output_root=tmp_path / "out",
        ),
    )

    with result.summary.output_paths.naming_audit.open(encoding="utf-8-sig", newline="") as file:
        naming_audit = list(csv.DictReader(file))
    with result.summary.output_paths.session_audit.open(encoding="utf-8-sig", newline="") as file:
        session_audit = list(csv.DictReader(file))
    manifest = json.loads(result.summary.output_paths.manifest.read_text(encoding="utf-8"))
    summary_text = result.summary.output_paths.summary.read_text(encoding="utf-8")

    assert naming_audit[0]["PosNameBeforeOverride"] == "AppleJuic"
    assert naming_audit[0]["PosEditDistance"] == "1"
    assert naming_audit[0]["PosCharacterDelta"] == "1"
    assert naming_audit[0]["PosSpacesChanged"] == "0"
    assert naming_audit[0]["PosTokenChanges"] == "1"
    assert naming_audit[0]["PosActiveEditActions"] == "1"
    assert naming_audit[0]["PosEditEffort"] == "light"
    assert naming_audit[1]["PosEditEffort"] == "heavy"
    assert session_audit[0]["PosEditEffort"] == "light"
    assert result.summary.pos_light_edits == 1
    assert result.summary.pos_moderate_edits == 0
    assert result.summary.pos_heavy_overrides == 1
    assert manifest["counts"]["pos_light_edits"] == 1
    assert manifest["counts"]["pos_heavy_overrides"] == 1
    assert "- POS-name light edits: 1" in summary_text
    assert "- POS-name heavy overrides: 1" in summary_text


def test_export_writes_pos_preference_profile_audit(tmp_path: Path) -> None:
    source_template, recipe, odin = _source_files(tmp_path)
    session = _session(
        [
            _row("row-1", "Chicken Caesar Salad", "5.25", "111", category="Salads"),
            _row(
                "row-2",
                "Bacon, Egg, and Cheese Bagel",
                "5.25",
                "222",
                category="Breakfast",
            ),
        ],
        categories=("Breakfast", "Salads"),
    )
    session = run_pos_generation(session)
    session = replace_pos_name(session, "row-1", "Chick Cae Sal")
    session = replace_pos_name(session, "row-1", "Chk Cae Sal")
    session = replace_pos_name(session, "row-2", "BEC Bagel")

    result = export_session(
        session,
        BuildInputs(
            product_template_path=source_template,
            recipe_list_path=recipe,
            odin_inventory_path=odin,
            output_root=tmp_path / "out",
        ),
    )

    with result.summary.output_paths.pos_profile_audit.open(
        encoding="utf-8-sig", newline=""
    ) as file:
        profile_rows = list(csv.DictReader(file))
    manifest = json.loads(result.summary.output_paths.manifest.read_text(encoding="utf-8"))

    chicken_rows = [
        row
        for row in profile_rows
        if row["RuleType"] == "abbreviation" and row["Token"] == "chicken"
    ]
    acronym_rows = [row for row in profile_rows if row["RuleType"] == "acronym"]
    style_rows = [row for row in profile_rows if row["RuleType"] == "style"]

    assert result.summary.output_paths.pos_profile_audit.name == "POS Preference Profile.csv"
    assert [(row["Rank"], row["Replacement"], row["Count"]) for row in chicken_rows] == [
        ("1", "Chk", "1")
    ]
    assert chicken_rows[0]["SourceTokenCounts"] == "3"
    assert "Chk Cae Sal" in chicken_rows[0]["Examples"]
    assert acronym_rows[0]["SuffixTokens"] == "egg, cheese"
    assert acronym_rows[0]["SpanLength"] == "3"
    assert style_rows == [
        {
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
            "SpacedOverrides": "3",
            "CompactOverrides": "0",
        }
    ]
    assert "POS Preference Profile.csv" in manifest["artifacts"]


def test_deleted_audit_includes_merge_transfer_details(tmp_path: Path) -> None:
    source_template, recipe, odin = _source_files(tmp_path)
    session = _session(
        [
            _row(
                "row-1",
                "Target Item",
                "1.25",
                "111",
                category="Snacks",
                pos_name="TargetItem",
            ),
            _row(
                "row-2",
                "Source Item",
                "1.25",
                "222,333",
                category="Snacks",
                pos_name="SourceItem",
            ),
        ],
        categories=("Snacks",),
    )
    session = merge_rows(session, "row-1", {"row-2"})
    session = replace_pos_name(session, "row-1", "TargetItem")

    result = export_session(
        session,
        BuildInputs(
            product_template_path=source_template,
            recipe_list_path=recipe,
            odin_inventory_path=odin,
            output_root=tmp_path / "out",
        ),
    )

    with result.summary.output_paths.deleted_audit.open(encoding="utf-8-sig", newline="") as file:
        deleted = list(csv.DictReader(file))

    assert deleted[0]["RowId"] == "row-2"
    assert deleted[0]["DeletedReason"] == "merged into row-1"
    assert deleted[0]["MergeTargetRowId"] == "row-1"
    assert deleted[0]["MergeTransferredBarcodes"] == "222,333"
    assert deleted[0]["MergeTargetBarcodeBefore"] == "111"
    assert deleted[0]["MergeTargetBarcodeAfter"] == "111,222,333"
    assert deleted[0]["MergeActionTimestamp"]
    datetime.fromisoformat(deleted[0]["MergeActionTimestamp"])


def test_final_review_metadata_summarizes_counts_and_validation() -> None:
    session = _session(
        [
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "111",
                category="Beverages",
                pos_name="AppleJuice",
                pos_overridden=True,
            ),
            _row(
                "row-2",
                "Orange Juice",
                "1.25",
                "111,222",
                category="Beverages",
                pos_name="OrangeJuice",
                status="edit_complete",
            ),
            _row(
                "row-3",
                "Merged Source",
                "1.00",
                "333",
                category="Snacks",
                status="deleted",
                deleted_reason="merged into row-2",
            ),
        ],
        categories=("Beverages", "Snacks"),
    )

    metadata = final_review_metadata(session)

    assert metadata.parsed_rows == 3
    assert metadata.active_rows == 2
    assert metadata.deleted_rows == 1
    assert metadata.merge_rows == 1
    assert metadata.pos_overrides == 1
    assert metadata.published_rows == 0
    assert metadata.orderable_rows == 0
    assert metadata.core_catalogue_rows == 0
    assert metadata.duplicate_barcodes == 1
    assert metadata.category_counts == (("Beverages", 2),)
    assert not metadata.export_ready
    assert "row-1: duplicate barcode" in metadata.export_errors
    assert "row-2: duplicate barcode" in metadata.export_errors


def test_raw_data_guided_session_profile_subset_exports_with_audits(tmp_path: Path) -> None:
    template, recipe, inventory, profile_path = _raw_data_paths()
    inputs = BuildInputs(
        product_template_path=template,
        recipe_list_path=recipe,
        odin_inventory_path=inventory,
        output_root=tmp_path / "out",
    )
    profile = load_venue_profile(profile_path)

    session = apply_venue_profile(parse_sources(inputs), profile)
    raw_row_count = len(session.rows)

    assert raw_row_count > 1000
    assert session.category_names == profile.category_names
    assert "Bread" in session.category_names
    assert "Vendor Beverages" in session.category_names
    assert len(no_barcode_rows(session)) > 300
    assert any(row.old_category for row in session.rows)

    keep_ids = _first_exportable_unique_barcode_row_ids(session, count=5)
    assert len(keep_ids) == 5

    session = delete_rows(
        session,
        {row.row_id for row in session.rows if row.row_id not in keep_ids},
        "raw fixture excluded",
    )
    session = assign_category(session, keep_ids, "Bread")
    session = run_pos_generation(session)
    for index, row in enumerate(session.active_rows, start=1):
        session = replace_pos_name(session, row.row_id, f"RawPOS{index:02d}")

    metadata = final_review_metadata(session)
    assert metadata.export_ready
    assert metadata.parsed_rows == raw_row_count
    assert metadata.active_rows == 5
    assert metadata.deleted_rows == raw_row_count - 5
    assert metadata.pos_overrides == 5
    assert metadata.category_counts == (("Bread", 5),)

    result = export_session(session, inputs)

    with result.summary.output_paths.final_import.open(encoding="utf-8-sig", newline="") as file:
        final_rows = list(csv.DictReader(file))
    with result.summary.output_paths.deleted_audit.open(encoding="utf-8-sig", newline="") as file:
        deleted_rows = list(csv.DictReader(file))
    with result.summary.output_paths.session_audit.open(encoding="utf-8-sig", newline="") as file:
        session_audit_rows = list(csv.DictReader(file))
    manifest = json.loads(result.summary.output_paths.manifest.read_text(encoding="utf-8"))

    assert result.summary.parsed_rows == raw_row_count
    assert result.summary.exported_rows == 5
    assert result.summary.deleted_rows == raw_row_count - 5
    assert result.summary.category_count == len(session.category_names)
    assert result.summary.pos_overrides == 5
    assert len(final_rows) == 5
    assert len(deleted_rows) == raw_row_count - 5
    assert len(session_audit_rows) == raw_row_count
    assert {row["IsPublished"] for row in final_rows} == {"false"}
    assert {row["IsOrderable"] for row in final_rows} == {"false"}
    assert {row["ProductCategories"] for row in final_rows} == {"Bread;"}
    assert [row["BaseProductPosName"] for row in final_rows] == [
        f"RawPOS{index:02d}" for index in range(1, 6)
    ]
    assert all(row["Barcodes"] for row in final_rows)
    assert {row["DeletedReason"] for row in deleted_rows} == {"raw fixture excluded"}
    assert manifest["sources"]["product_template"]["filename"] == template.name
    assert manifest["sources"]["recipe_list"]["filename"] == recipe.name
    assert manifest["sources"]["odin_inventory"]["filename"] == inventory.name
    assert manifest["sources"]["generic_inventory"] is None
    assert all(
        len(source["sha256"]) == 64 for source in manifest["sources"].values() if source is not None
    )
    assert manifest["counts"]["exported_rows"] == 5
    assert manifest["counts"]["deleted_rows"] == raw_row_count - 5
    assert "Bread" in manifest["categories"]
    assert "chicken" in manifest["pos_name_preferences"]


def test_venue_profile_saves_categories_and_pos_preferences(tmp_path: Path) -> None:
    preferences = learn_pos_preferences(
        _session([]).pos_preferences, "Chicken Caesar Salad", "Chick Cae Sal"
    )
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


def test_final_review_edit_validation_checks_export_blockers() -> None:
    session = _session(
        [
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "111",
                category="Beverages",
                pos_name="Apple Juice",
                status="pos_ready",
            ),
            _row(
                "row-2",
                "Orange Juice",
                "1.50",
                "222",
                category="Beverages",
                pos_name="OrangeJuice",
                status="pos_ready",
            ),
        ],
        categories=("Beverages",),
    )

    errors = validate_final_review_edit(
        session,
        "row-1",
        item_name="Orange Juice",
        price="1.25",
        barcode="222",
        category="Beverages",
        pos_name="OrangeJuice",
    )

    assert errors == ["duplicate POS name", "duplicate barcode", "duplicate item name"]


def test_save_final_review_edit_updates_row_and_keeps_export_ready() -> None:
    session = _session(
        [
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "111",
                category="Beverages",
                pos_name="Apple Juice",
                status="pos_ready",
            ),
            _row(
                "row-2",
                "Orange Juice",
                "1.50",
                "222",
                category="Beverages",
                pos_name="OrangeJuice",
                status="pos_ready",
            ),
        ],
        categories=("Beverages",),
    )

    session = save_final_review_edit(
        session,
        "row-1",
        item_name="Apple Bottle",
        price="1.35",
        barcode="111, 333",
        category="Drinks",
        pos_name="Apple Bottle",
        is_published=True,
        is_orderable=True,
        core_catalogue=True,
    )

    row = next(row for row in session.rows if row.row_id == "row-1")
    assert row.item_name == "Apple Bottle"
    assert row.price == "1.35"
    assert row.barcode == "111,333"
    assert row.category == "Drinks"
    assert row.pos_name == "Apple Bottle"
    assert row.is_published is True
    assert row.is_orderable is True
    assert row.core_catalogue is True
    assert row.status == "pos_ready"
    assert row.edited is True
    assert session.category_names == ("Beverages", "Drinks")
    assert session.can_export is True


def test_final_rows_use_row_level_publish_order_flags_and_core_catalogue_export(
    tmp_path: Path,
) -> None:
    source_template, recipe, odin = _source_files(tmp_path)
    session = _session(
        [
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "111",
                category="Beverages",
                pos_name="Apple Juice",
                status="pos_ready",
                is_published=True,
                is_orderable=True,
                core_catalogue=True,
            ),
            _row(
                "row-2",
                "Orange Juice",
                "1.50",
                "222",
                category="Beverages",
                pos_name="OrangeJuice",
                status="pos_ready",
            ),
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
    )

    with result.summary.output_paths.final_import.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    with result.summary.output_paths.core_catalogue.open(encoding="utf-8-sig", newline="") as file:
        core_rows = list(csv.DictReader(file))

    assert [(row["BaseProductName"], row["IsPublished"], row["IsOrderable"]) for row in rows] == [
        ("Apple Juice", "true", "true"),
        ("Orange Juice", "false", "false"),
    ]
    assert [row["BaseProductName"] for row in core_rows] == ["Apple Juice"]
    assert result.summary.core_catalogue_rows == 1
    assert result.summary.output_paths.core_catalogue.name == "Core Catalogue.csv"


def test_filter_final_rows_finds_text_and_flagged_rows() -> None:
    session = _session(
        [
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "111",
                category="Beverages",
                pos_name="Apple Juice",
                status="pos_ready",
                is_published=True,
            ),
            _row(
                "row-2",
                "Orange Snack",
                "1.50",
                "222",
                category="Snacks",
                pos_name="OrangeSnack",
                status="pos_ready",
                core_catalogue=True,
            ),
        ],
        categories=("Beverages", "Snacks"),
    )

    assert [row.row_id for row in filter_final_rows(session, keyword="snack")] == ["row-2"]
    assert [row.row_id for row in filter_final_rows(session, flag_filter="Published")] == ["row-1"]
    assert [row.row_id for row in filter_final_rows(session, flag_filter="Core Catalogue")] == [
        "row-2"
    ]


def _session(
    rows: list[SessionRow],
    *,
    categories: tuple[str, ...] = (),
    preferences=None,
) -> ImportSession:
    kwargs = {}
    if preferences is not None:
        kwargs["pos_preferences"] = preferences
    return ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=tuple(rows),
        category_names=categories,
        **kwargs,
    )


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
    review_reason: str = "",
    deleted_reason: str = "",
    pos_overridden: bool = False,
    is_published: bool = False,
    is_orderable: bool = False,
    core_catalogue: bool = False,
    source: str = "test",
    stock: str = "",
) -> SessionRow:
    return SessionRow(
        row_id=row_id,
        candidate=ProductCandidate(
            source=source,
            source_key=row_id,
            item_name=name,
            price=price,
            barcode=barcode,
            category=old_category or category,
            stock=stock,
        ),
        old_category=old_category or category,
        category=category,
        pos_name=pos_name,
        status=status,  # type: ignore[arg-type]
        review_reason=review_reason,
        deleted_reason=deleted_reason,
        pos_overridden=pos_overridden,
        is_published=is_published,
        is_orderable=is_orderable,
        core_catalogue=core_catalogue,
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


def _raw_data_paths() -> tuple[Path, Path, Path, Path]:
    raw_data = Path(__file__).resolve().parents[1] / "Raw Data"
    template = sorted(raw_data.glob("ProductData*.csv"))
    recipe = sorted(raw_data.glob("recipeList*.csv"))
    inventory = sorted(raw_data.glob("*.xlsx"))
    profile = sorted(raw_data.glob("*.json"))
    if not template or not recipe or not inventory or not profile:
        pytest.skip("Raw Data integration fixture is not available in this checkout.")
    return template[0], recipe[0], inventory[0], profile[0]


def _first_exportable_unique_barcode_row_ids(session: ImportSession, *, count: int) -> set[str]:
    row_ids = []
    seen_barcodes = set()
    for row in session.active_rows:
        barcodes = parse_barcodes(row.barcode)
        barcode_keys = {barcode.casefold() for barcode in barcodes}
        if row.status != "active" or not barcodes or barcode_keys & seen_barcodes:
            continue
        row_ids.append(row.row_id)
        seen_barcodes.update(barcode_keys)
        if len(row_ids) == count:
            break
    return set(row_ids)
