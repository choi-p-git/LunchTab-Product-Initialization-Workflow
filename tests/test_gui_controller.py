from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lunchtab_product_init.gui_controller import (
    AppController,
    AppPhase,
    AppState,
    SourceFileAudit,
    UndoEntry,
    deselect_shown_category_rows,
    final_review_audit_text,
    next_displayed_pos_row_id,
    select_category_action_rows,
    select_shown_category_rows,
    source_file_audits,
    toggle_category_row_selection,
    undo_button_text,
)
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS
from lunchtab_product_init.session_workflow import FinalReviewMetadata, ImportSession


def test_controller_ready_to_parse_after_required_files_selected() -> None:
    controller = AppController()
    controller.select_product_template(Path("ProductData.csv"))
    state = controller.select_recipe_list(Path("recipeList.csv"))
    assert state.phase == AppPhase.READY_TO_PARSE
    assert state.can_parse
    inputs = controller.build_inputs()
    assert inputs.odin_inventory_path is None
    assert inputs.generic_inventory_path is None


def test_controller_tracks_optional_inventory_inputs() -> None:
    controller = AppController()
    controller.select_product_template(Path("ProductData.csv"))
    controller.select_recipe_list(Path("recipeList.csv"))
    controller.select_odin_inventory(Path("inventory.xlsx"))
    state = controller.select_generic_inventory(Path("inventory.csv"))

    assert state.can_parse
    inputs = controller.build_inputs()
    assert inputs.odin_inventory_path == Path("inventory.xlsx")
    assert inputs.generic_inventory_path == Path("inventory.csv")


def test_controller_tracks_is_orderable_setting() -> None:
    controller = AppController()
    state = controller.set_is_orderable(True)
    assert state.is_orderable


def test_controller_parse_and_step_transitions() -> None:
    controller = AppController()
    controller.select_product_template(Path("ProductData.csv"))
    controller.select_recipe_list(Path("recipeList.csv"))

    assert controller.begin_parse().phase == AppPhase.PARSING
    session = ImportSession(headers=list(LUNCHTAB_TEMPLATE_HEADERS), rows=())
    assert controller.parse_succeeded(session).phase == AppPhase.CATEGORIZING
    assert controller.go_to_edit_review().phase == AppPhase.EDIT_REVIEW
    assert controller.go_to_pos_review().phase == AppPhase.POS_REVIEW
    assert controller.go_to_final_review().phase == AppPhase.FINAL_REVIEW


def test_controller_session_update_can_rewind_from_final_review() -> None:
    controller = AppController()
    session = ImportSession(headers=list(LUNCHTAB_TEMPLATE_HEADERS), rows=())
    controller.parse_succeeded(session)
    controller.go_to_edit_review()
    controller.go_to_pos_review()
    controller.go_to_final_review()
    controller.state = replace(controller.state, result=object())  # type: ignore[arg-type]

    state = controller.set_session(
        session,
        phase=AppPhase.EDIT_REVIEW,
        message="Edit changes made. Continue through POS names before final review.",
    )

    assert state.phase == AppPhase.EDIT_REVIEW
    assert state.result is None
    assert "POS names" in state.message


def test_controller_session_update_preserves_phase_by_default() -> None:
    controller = AppController()
    session = ImportSession(headers=list(LUNCHTAB_TEMPLATE_HEADERS), rows=())
    controller.parse_succeeded(session)
    controller.go_to_pos_review()

    state = controller.set_session(session)

    assert state.phase == AppPhase.POS_REVIEW


def test_controller_requires_all_files_before_parse() -> None:
    controller = AppController()
    try:
        controller.begin_parse()
    except RuntimeError as error:
        assert "ProductData template and recipe list" in str(error)
    else:
        raise AssertionError("begin_parse should reject incomplete input")


def test_undo_button_text_shows_next_undo_action() -> None:
    session = ImportSession(headers=list(LUNCHTAB_TEMPLATE_HEADERS), rows=())

    assert undo_button_text([]) == "Undo"
    assert undo_button_text(
        [
            UndoEntry(session=session, label="Assign 2 rows"),
            UndoEntry(session=session, label="Delete 1 row"),
        ]
    ) == "Undo: Delete 1 row"


def test_source_file_audits_hash_selected_inputs(tmp_path: Path) -> None:
    template = tmp_path / "ProductData.csv"
    recipe = tmp_path / "recipeList.csv"
    inventory = tmp_path / "inventory.xlsx"
    template.write_text("template", encoding="utf-8")
    recipe.write_text("recipe", encoding="utf-8")
    inventory.write_bytes(b"inventory")
    generic = tmp_path / "inventory.csv"
    generic.write_text("inventory", encoding="utf-8")
    audits = source_file_audits(
        AppState(
            product_template_path=template,
            recipe_list_path=recipe,
            odin_inventory_path=inventory,
            generic_inventory_path=generic,
        )
    )

    assert [audit.label for audit in audits] == ["Template", "Recipe", "Odin", "Generic Inventory"]
    assert [audit.filename for audit in audits] == [
        "ProductData.csv",
        "recipeList.csv",
        "inventory.xlsx",
        "inventory.csv",
    ]
    assert all(len(audit.sha256) == 64 for audit in audits)
    assert audits[0].sha256 == "5cde0f1298f41f7d1c8b907a36992a7a513225a2615bd6e307bf1a9149b06b40"
    assert audits[0].short_sha256 == "5cde0f1298f4"


def test_final_review_audit_text_includes_source_filenames_and_short_hashes() -> None:
    metadata = FinalReviewMetadata(
        parsed_rows=10,
        active_rows=8,
        deleted_rows=2,
        edited_rows=1,
        merge_rows=1,
        pos_overrides=3,
        duplicate_barcodes=0,
        duplicate_pos_names=1,
        category_counts=(("Bread", 4), ("Snacks", 4)),
        export_errors=("row-1: duplicate POS name",),
    )

    text = final_review_audit_text(
        metadata,
        is_orderable=True,
        source_files=(
            SourceFileAudit("Template", "ProductData.csv", "abcdef1234567890"),
            SourceFileAudit("Recipe", "recipeList.csv", "123456abcdef7890"),
        ),
    )

    assert "Rows: parsed 10 | active 8 | deleted 2 | edited 1 | merged 1" in text
    assert "Validation: export 1 blocker(s) | duplicate barcodes 0 | duplicate POS names 1" in text
    assert "Categories: Bread: 4, Snacks: 4" in text
    assert "POS overrides: 3 | IsOrderable: true" in text
    assert "Sources: Template: ProductData.csv (abcdef123456); Recipe: recipeList.csv (123456abcdef)" in text


def test_category_action_rows_prefer_checked_rows_over_highlighted_rows() -> None:
    action = select_category_action_rows(["row-1", "row-2"], ["row-3"])

    assert action.row_ids == frozenset({"row-1", "row-2"})
    assert not action.using_highlighted
    assert not action.needs_delete_confirmation


def test_category_action_rows_fall_back_to_highlighted_rows_for_delete_confirmation() -> None:
    action = select_category_action_rows([], ["row-3", "row-4"])

    assert action.row_ids == frozenset({"row-3", "row-4"})
    assert action.using_highlighted
    assert action.needs_delete_confirmation


def test_category_selection_helpers_toggle_select_and_deselect_shown_rows() -> None:
    selected = toggle_category_row_selection([], "row-1")
    selected = toggle_category_row_selection(selected, "row-2")
    selected = toggle_category_row_selection(selected, "row-1")
    assert selected == frozenset({"row-2"})

    selected = select_shown_category_rows(selected, ["row-3", "row-4"])
    assert selected == frozenset({"row-2", "row-3", "row-4"})

    selected = deselect_shown_category_rows(selected, ["row-3", "row-5"])
    assert selected == frozenset({"row-2", "row-4"})


def test_next_displayed_pos_row_advances_within_current_filtered_rows() -> None:
    assert next_displayed_pos_row_id("row-1", ["row-1", "row-2", "row-3"], ["row-1", "row-2"]) == "row-2"


def test_next_displayed_pos_row_keeps_last_visible_row_when_current_is_last() -> None:
    assert next_displayed_pos_row_id("row-2", ["row-1", "row-2"], ["row-1", "row-2"]) == "row-2"


def test_next_displayed_pos_row_uses_next_surviving_row_when_current_leaves_filter() -> None:
    assert next_displayed_pos_row_id(
        "row-2",
        ["row-1", "row-2", "row-3", "row-4"],
        ["row-1", "row-4"],
    ) == "row-4"


def test_next_displayed_pos_row_uses_stable_fallback_without_previous_context() -> None:
    assert next_displayed_pos_row_id("row-9", ["row-1", "row-2"], ["row-3", "row-4"]) == "row-3"


def test_next_displayed_pos_row_returns_none_when_filter_has_no_rows() -> None:
    assert next_displayed_pos_row_id("row-1", ["row-1"], []) is None
