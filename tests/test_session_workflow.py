from __future__ import annotations

import csv
import json
from pathlib import Path

from lunchtab_product_init.models import BuildInputs, LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.session_workflow import (
    ImportSession,
    SessionRow,
    assign_category,
    delete_rows,
    export_session,
    filter_rows,
    learn_pos_preferences,
    mark_for_edit,
    next_edit_row,
    no_barcode_rows,
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

    filtered = filter_rows(session, keyword="chicken", min_price="5", max_price="7")
    assert [row.row_id for row in filtered] == ["row-1"]

    session = assign_category(session, {"row-1"}, "Sandwiches")
    session = mark_for_edit(session, {"row-2"}, "operator review")

    assert session.category_names == ("Sandwiches",)
    assert session.rows[0].category == "Sandwiches"
    assert session.rows[1].status == "needs_edit"


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
    assert suggest_pos_names(session, "row-2")[0] == "ChickCaeSal"


def test_export_excludes_deleted_rows_and_writes_audits(tmp_path: Path) -> None:
    source_template, recipe, odin = _source_files(tmp_path)
    session = _session(
        [
            _row("row-1", "Apple Juice", "1.25", "ABC", category="Beverages", pos_name="AppleJuice"),
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


def test_venue_profile_saves_categories_and_pos_preferences(tmp_path: Path) -> None:
    preferences = learn_pos_preferences(_session([]).pos_preferences, "Chicken Caesar Salad", "Chick Cae Sal")
    session = _session([], categories=("Salads",), preferences=preferences)

    path = tmp_path / "venue-profile.json"
    save_venue_profile(session, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["categories"] == ["Salads"]
    assert payload["pos_name_preferences"]["chicken"] == "Chick"


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
            category=category,
        ),
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
