from __future__ import annotations

from pathlib import Path

from lunchtab_product_init.gui_controller import AppController, AppPhase
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


def test_controller_requires_all_files_before_parse() -> None:
    controller = AppController()
    try:
        controller.begin_parse()
    except RuntimeError as error:
        assert "All three source files" in str(error)
    else:
        raise AssertionError("begin_parse should reject incomplete input")
