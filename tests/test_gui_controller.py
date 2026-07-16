from __future__ import annotations

from pathlib import Path

from lunchtab_product_init.gui_controller import AppController, AppPhase


def test_controller_ready_after_all_files_selected() -> None:
    controller = AppController()
    controller.select_product_template(Path("ProductData.csv"))
    controller.select_recipe_list(Path("recipeList.csv"))
    state = controller.select_odin_inventory(Path("inventory.xlsx"))
    assert state.phase == AppPhase.READY
    assert state.can_build


def test_controller_tracks_optional_category_profile() -> None:
    controller = AppController()
    state = controller.select_category_profile(Path("category-profile.json"))
    assert state.category_profile_path == Path("category-profile.json")


def test_controller_requires_all_files_before_build() -> None:
    controller = AppController()
    try:
        controller.begin_build()
    except RuntimeError as error:
        assert "All three source files" in str(error)
    else:
        raise AssertionError("begin_build should reject incomplete input")
