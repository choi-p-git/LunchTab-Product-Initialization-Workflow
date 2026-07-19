from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lunchtab_product_init.gui_controller import (
    AppController,
    AppPhase,
    UndoEntry,
    deselect_shown_category_rows,
    next_displayed_pos_row_id,
    select_category_action_rows,
    select_shown_category_rows,
    toggle_category_row_selection,
    undo_button_text,
)
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS
from lunchtab_product_init.session_workflow import ImportSession


def test_controller_ready_to_parse_after_all_files_selected() -> None:
    controller = AppController()
    controller.select_product_template(Path("ProductData.csv"))
    controller.select_recipe_list(Path("recipeList.csv"))
    state = controller.select_odin_inventory(Path("inventory.xlsx"))
    assert state.phase == AppPhase.READY_TO_PARSE
    assert state.can_parse


def test_controller_tracks_is_orderable_setting() -> None:
    controller = AppController()
    state = controller.set_is_orderable(True)
    assert state.is_orderable


def test_controller_parse_and_step_transitions() -> None:
    controller = AppController()
    controller.select_product_template(Path("ProductData.csv"))
    controller.select_recipe_list(Path("recipeList.csv"))
    controller.select_odin_inventory(Path("inventory.xlsx"))

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
        assert "All three source files" in str(error)
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
