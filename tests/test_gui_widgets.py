from __future__ import annotations

import tkinter as tk

import pytest

from lunchtab_product_init import gui as gui_module
from lunchtab_product_init.gui import ProductInitializationApp
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.pos_profile_inference import (
    PosProfileInferencePaths,
    PosProfileInferenceResult,
    PosProfileInferenceSummary,
)
from lunchtab_product_init.session_workflow import (
    ImportSession,
    PosNamePreferenceProfile,
    SessionBuildSummary,
    SessionExportResult,
    SessionOutputPaths,
    SessionRow,
)


@pytest.fixture(scope="module")
def app():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display is not available: {error}")
    root.withdraw()
    application = ProductInitializationApp(root)
    root.update_idletasks()
    try:
        yield application
    finally:
        root.destroy()


def test_category_delete_key_deletes_highlighted_row_after_confirmation(app, monkeypatch) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row("row-1", "Apple Juice", "1.25", "111", category="Beverages"),
            _row("row-2", "Orange Juice", "1.50", "222", category="Beverages"),
        ),
        category_names=("Beverages",),
    )
    app.controller.parse_succeeded(session)
    _clear_category_filter_vars(app)
    app._render()
    app.root.update()

    tree = app._tree_widget(app.category_tree)
    tree.selection_set("row-1")
    tree.focus("row-1")
    prompts = []

    def confirm_delete(title: str, message: str) -> bool:
        prompts.append((title, message))
        return True

    monkeypatch.setattr(gui_module.messagebox, "askyesno", confirm_delete)

    assert app._category_tree_delete_key(_Event()) == "break"
    app.root.update()

    row_1 = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")
    row_2 = next(row for row in app.controller.state.session.rows if row.row_id == "row-2")
    tree = app._tree_widget(app.category_tree)

    assert row_1.status == "deleted"
    assert row_1.deleted_reason == "operator deleted"
    assert row_2.status == "active"
    assert prompts == [(gui_module.APP_TITLE, "Delete 1 highlighted row from this import?")]
    assert app.category_selection == set()
    assert str(app.category_undo_button.cget("state")) == "normal"
    assert app.category_undo_button.cget("text") == "Undo: Delete 1 row"
    assert "row-1" not in tree.get_children("")
    assert "row-2" in tree.get_children("")


def test_category_keyword_filter_debounces_and_immediate_refresh_cancels_pending(
    app,
    monkeypatch,
) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row("row-1", "Apple Juice", "1.25", "111", category="Beverages"),
            _row("row-2", "Chicken Sandwich", "6.50", "222", category="Entrees"),
            _row("row-3", "Orange Juice", "1.50", "333", category="Beverages"),
        ),
        category_names=("Beverages", "Entrees"),
    )
    app.controller.parse_succeeded(session)
    _clear_category_filter_vars(app)
    app._render()
    app.root.geometry("1120x760")
    app.root.deiconify()
    app.notebook.select(app.tabs["categories"])
    app.root.update()

    tree = app._tree_widget(app.category_tree)
    assert set(tree.get_children("")) == {"row-1", "row-2", "row-3"}

    app.category_filter.set("chicken")
    app.category_filter_entry.focus_set()
    monkeypatch.setattr(app.root, "focus_get", lambda: app.category_filter_entry)
    app.root.update()

    app._category_filter_key_released(_KeyEvent(app.category_filter_entry, "n"))
    pending_after_id = app._category_filter_after_id
    assert pending_after_id is not None
    assert set(tree.get_children("")) == {"row-1", "row-2", "row-3"}

    app.root.after_cancel(pending_after_id)
    app._run_category_filter_refresh()
    app.root.update()
    tree = app._tree_widget(app.category_tree)
    assert app._category_filter_after_id is None
    assert list(tree.get_children("")) == ["row-2"]

    app.category_filter.set("orange")
    app._category_filter_after_id = "pending-filter"
    after_cancel_calls = []
    monkeypatch.setattr(app.root, "after_cancel", after_cancel_calls.append)

    app._refresh_category_rows()
    app.root.update()
    tree = app._tree_widget(app.category_tree)

    assert after_cancel_calls == ["pending-filter"]
    assert app._category_filter_after_id is None
    assert list(tree.get_children("")) == ["row-3"]


def test_category_stock_filter_uses_inventory_rows_only(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row("row-1", "Recipe Only", "1.25", "111", source="recipe"),
            _row("row-2", "Inventory No Stock", "1.50", "222", source="inventory"),
            _row("row-3", "Inventory Zero Stock", "1.75", "333", source="inventory", stock="0"),
            _row("row-4", "Inventory Five Stock", "2.00", "444", source="inventory", stock="5"),
        ),
        category_names=("Beverages",),
    )
    app.controller.parse_succeeded(session)
    _clear_category_filter_vars(app)
    app._render()
    app.notebook.select(app.tabs["categories"])
    app.root.update()

    tree = app._tree_widget(app.category_tree)
    assert set(tree.get_children("")) == {"row-1", "row-2", "row-3", "row-4"}

    app.stock_operator.set("No stock")
    app._stock_operator_changed()
    app.root.update()
    assert list(tree.get_children("")) == ["row-2"]

    app.stock_operator.set("0")
    app._stock_operator_changed()
    app.root.update()
    assert list(tree.get_children("")) == ["row-3"]

    app.stock_operator.set(">=")
    app.stock_value.set("5")
    app._stock_operator_changed()
    app.root.update()
    assert list(tree.get_children("")) == ["row-4"]


def test_inline_category_dropdown_applies_category_and_closes(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row("row-1", "Apple Juice", "1.25", "111", category=""),
            _row("row-2", "Orange Juice", "1.50", "222", category="Beverages"),
        ),
        category_names=("Beverages", "Snacks"),
    )
    app.controller.parse_succeeded(session)
    _clear_category_filter_vars(app)
    app._render()
    app.root.geometry("1120x760")
    app.root.deiconify()
    app.notebook.select(app.tabs["categories"])
    app.root.update()

    tree = app._tree_widget(app.category_tree)
    tree.see("row-1")
    app.root.update()
    app.root.update_idletasks()
    if not tree.bbox("row-1", "#6"):
        pytest.skip("Tk did not expose category-cell geometry for inline dropdown test.")

    app._show_inline_category_dropdown("row-1", focus=True)
    app.root.update()

    combo = app.inline_category_combo
    assert combo is not None
    assert combo.winfo_exists()
    assert str(combo.cget("state")) == "readonly"
    assert combo.cget("values") == ("Beverages", "Snacks")

    app._apply_inline_category("row-1", "Snacks")
    app.root.update()
    row_1 = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")

    assert row_1.category == "Snacks"
    assert row_1.status == "active"
    assert row_1.review_reason == ""
    assert app.inline_category_combo is None
    assert str(app.category_undo_button.cget("state")) == "normal"
    assert app.category_undo_button.cget("text") == "Undo: Set category to Snacks"


def test_go_to_edit_resets_no_barcode_filter_and_shows_operator_review_rows(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Marked Valid Row",
                "1.25",
                "111",
                category="Beverages",
                status="needs_edit",
                review_reason="operator review",
            ),
            _row(
                "row-2",
                "Missing Barcode Row",
                "1.50",
                "",
                category="Beverages",
                status="needs_edit",
                review_reason="missing barcode",
            ),
        ),
        category_names=("Beverages",),
    )
    app.controller = gui_module.AppController()
    app.controller.parse_succeeded(session)
    app.edit_no_barcode_only = True

    app._go_to_edit()
    app.root.update()

    tree = app._tree_widget(app.edit_tree)

    assert not app.edit_no_barcode_only
    assert list(tree.get_children("")) == ["row-1", "row-2"]


def test_edit_duplicate_name_filter_groups_review_rows_for_merge(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Orange Juice",
                "1.25",
                "111",
                category="Beverages",
                status="needs_edit",
                review_reason="operator review",
            ),
            _row(
                "row-2",
                "Apple Juice",
                "1.50",
                "222",
                category="Beverages",
                status="needs_edit",
                review_reason="operator review",
            ),
            _row(
                "row-3",
                "orange juice",
                "1.75",
                "333",
                category="Beverages",
                status="needs_edit",
                review_reason="operator review",
            ),
            _row(
                "row-4",
                "Single Item",
                "2.00",
                "444",
                category="Snacks",
                status="needs_edit",
                review_reason="operator review",
            ),
            _row(
                "row-5",
                "Apple Juice",
                "2.25",
                "555",
                category="Beverages",
                status="needs_edit",
                review_reason="operator review",
            ),
        ),
        category_names=("Beverages", "Snacks"),
    )
    app.controller = gui_module.AppController()
    app.controller.parse_succeeded(session)
    app._go_to_edit()

    app._show_duplicate_name_edit_rows()
    app.root.update()

    tree = app._tree_widget(app.edit_tree)

    assert not app.edit_no_barcode_only
    assert app.edit_duplicate_name_only
    assert list(tree.get_children("")) == ["row-2", "row-5", "row-1", "row-3"]


def test_go_to_edit_marks_duplicate_names_for_review(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row("row-1", "Orange Juice", "1.25", "111", category="Beverages"),
            _row("row-2", "orange juice", "1.50", "222", category="Beverages"),
            _row("row-3", "Single Item", "2.00", "333", category="Snacks"),
        ),
        category_names=("Beverages", "Snacks"),
    )
    app.controller = gui_module.AppController()
    app.controller.parse_succeeded(session)

    app._go_to_edit()
    app.root.update()

    tree = app._tree_widget(app.edit_tree)

    assert list(tree.get_children("")) == ["row-1", "row-2"]
    assert [
        (row.row_id, row.status, row.review_reason) for row in app.controller.state.session.rows
    ] == [
        ("row-1", "needs_edit", "duplicate name"),
        ("row-2", "needs_edit", "duplicate name"),
        ("row-3", "active", ""),
    ]


def test_save_edit_confirms_unchanged_valid_review_row(app, monkeypatch) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Orange Juice",
                "1.25",
                "111",
                category="Beverages",
                status="needs_edit",
                review_reason="duplicate name",
            ),
        ),
        category_names=("Beverages",),
    )
    prompts = []

    def confirm_save(title: str, message: str) -> bool:
        prompts.append((title, message))
        return True

    monkeypatch.setattr(gui_module.messagebox, "askyesno", confirm_save)
    app.controller = gui_module.AppController()
    app.controller.set_session(session, phase=gui_module.AppPhase.EDIT_REVIEW)
    app._load_edit_row("row-1")

    app._save_edit()
    app.root.update()

    row_1 = app.controller.state.session.rows[0]

    assert prompts == [(gui_module.APP_TITLE, "Save this valid row without changing any fields?")]
    assert row_1.status == "edit_complete"
    assert row_1.review_reason == ""
    assert row_1.edited


def test_save_edit_advances_to_next_displayed_row_and_focuses_name(app, monkeypatch) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Missing Price",
                "",
                "111",
                category="Beverages",
                status="needs_edit",
                review_reason="missing or invalid price",
            ),
            _row(
                "row-2",
                "Review Row",
                "1.50",
                "222",
                category="Beverages",
                status="needs_edit",
                review_reason="operator review",
            ),
        ),
        category_names=("Beverages",),
    )
    focus_calls = []
    selection_calls = []
    monkeypatch.setattr(app.edit_name_entry, "focus_set", lambda: focus_calls.append("focus"))
    monkeypatch.setattr(
        app.edit_name_entry,
        "selection_range",
        lambda start, end: selection_calls.append((start, end)),
    )
    app.controller = gui_module.AppController()
    app.controller.set_session(session, phase=gui_module.AppPhase.EDIT_REVIEW)
    app._render()
    app._select_edit_tree_row("row-1")
    app._load_edit_row("row-1")

    app.edit_price.set("1.25")
    app._save_edit()
    app.root.update()
    app.root.update_idletasks()

    tree = app._tree_widget(app.edit_tree)
    row_1 = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")

    assert row_1.status == "edit_complete"
    assert app.current_edit_row_id == "row-2"
    assert tree.selection() == ("row-2",)
    assert app.edit_name.get() == "Review Row"
    assert focus_calls
    assert selection_calls[-1] == (0, tk.END)


def test_edit_entry_return_saves_and_advances_to_next_displayed_row(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Missing Barcode",
                "1.00",
                "",
                category="Beverages",
                status="needs_edit",
                review_reason="missing barcode",
            ),
            _row(
                "row-2",
                "Review Row",
                "1.50",
                "222",
                category="Beverages",
                status="needs_edit",
                review_reason="operator review",
            ),
        ),
        category_names=("Beverages",),
    )
    app.controller = gui_module.AppController()
    app.controller.set_session(session, phase=gui_module.AppPhase.EDIT_REVIEW)
    app._render()
    app._select_edit_tree_row("row-1")
    app._load_edit_row("row-1")

    app.edit_barcode.set("111")

    assert app._edit_entry_return(_Event()) == "break"

    row_1 = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")
    assert row_1.status == "edit_complete"
    assert app.current_edit_row_id == "row-2"
    assert app.edit_name.get() == "Review Row"


def test_edit_duplicate_name_precheck_disables_save_and_enter(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Orange Juice",
                "1.00",
                "111",
                category="Beverages",
                status="needs_edit",
                review_reason="duplicate name",
            ),
            _row(
                "row-2",
                "Apple Juice",
                "1.50",
                "222",
                category="Beverages",
                status="active",
            ),
        ),
        category_names=("Beverages",),
    )
    app.controller = gui_module.AppController()
    app.controller.set_session(session, phase=gui_module.AppPhase.EDIT_REVIEW)
    app._render()
    app._select_edit_tree_row("row-1")
    app._load_edit_row("row-1")

    app.edit_name.set("Apple Juice")
    app._update_edit_action_state()

    assert app.edit_validation.get() == "duplicate item name"
    assert str(app.save_edit_button.cget("state")) == "disabled"
    assert app._edit_entry_return(_Event()) == "break"

    row_1 = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")
    assert row_1.item_name == "Orange Juice"
    assert row_1.status == "needs_edit"


def test_inventory_file_selection_clears_alternate_inventory_source(app, monkeypatch) -> None:
    selections = iter(("C:/source/inventory.xlsx", "C:/source/inventory.csv"))
    monkeypatch.setattr(
        gui_module.filedialog, "askopenfilename", lambda **_kwargs: next(selections)
    )

    app.generic_inventory_text.set("C:/source/old-inventory.csv")
    app._choose_odin()

    assert app.odin_inventory_text.get() == "C:/source/inventory.xlsx"
    assert app.generic_inventory_text.get() == ""
    assert app.controller.state.odin_inventory_path is not None
    assert app.controller.state.generic_inventory_path is None

    app._choose_generic_inventory()

    assert app.odin_inventory_text.get() == ""
    assert app.generic_inventory_text.get() == "C:/source/inventory.csv"
    assert app.controller.state.odin_inventory_path is None
    assert app.controller.state.generic_inventory_path is not None


def test_category_primary_actions_remain_visible_at_1366x768(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row("row-1", "Apple Juice", "1.25", "111", category="Beverages"),
            _row("row-2", "Orange Juice", "1.50", "222", category="Beverages"),
        ),
        category_names=("Beverages",),
    )
    app.controller = gui_module.AppController()
    app.controller.parse_succeeded(session)
    _clear_category_filter_vars(app)
    app.root.geometry("1366x768+0+0")
    app.root.deiconify()
    app.notebook.select(app.tabs["categories"])
    app._render()
    app.root.update()
    app.root.update_idletasks()

    _assert_widgets_inside_root(
        app.root,
        (
            app.select_all_category_button,
            app.select_highlighted_category_button,
            app.deselect_all_category_button,
            app.category_combo,
            app.assign_category_button,
            app.mark_category_button,
            app.delete_category_button,
            app.save_profile_button,
            app.to_edit_button,
        ),
    )


def test_tree_header_sort_reorders_display_without_session_mutation(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row("row-1", "Zebra Snack", "1.25", "111", category="Snacks"),
            _row("row-2", "Apple Juice", "2.50", "222", category="Beverages"),
            _row("row-3", "Banana Bread", "1.50", "333", category="Bakery"),
        ),
        category_names=("Bakery", "Beverages", "Snacks"),
    )
    app.controller = gui_module.AppController()
    app.controller.parse_succeeded(session)
    _clear_category_filter_vars(app)
    app._tree_sort_state[str(app._tree_widget(app.category_tree))] = ("", True, ("price",))
    app._render()
    tree = app._tree_widget(app.category_tree)

    app._sort_tree_by_column(tree, "name")

    assert list(tree.get_children("")) == ["row-2", "row-3", "row-1"]
    assert [row.row_id for row in app.controller.state.session.rows] == ["row-1", "row-2", "row-3"]

    app._sort_tree_by_column(tree, "name")

    assert list(tree.get_children("")) == ["row-1", "row-3", "row-2"]


def test_final_review_preview_defaults_to_export_order(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Zebra Snack",
                "1.25",
                "111",
                category="Snacks",
                pos_name="ZebraSnack",
                status="pos_ready",
            ),
            _row(
                "row-2",
                "Apple Drink",
                "1.50",
                "222",
                category="Beverages",
                pos_name="AppleDrink",
                status="pos_ready",
            ),
            _row(
                "row-3",
                "Apple Snack",
                "2.00",
                "333",
                category="Snacks",
                pos_name="AppleSnack",
                status="pos_ready",
            ),
        ),
        category_names=("Beverages", "Snacks"),
    )
    _set_final_session(app, session)
    app._tree_sort_state[str(app._tree_widget(app.final_tree))] = ("", True, ("price",))
    app._render()
    tree = app._tree_widget(app.final_tree)

    assert list(tree.get_children("")) == ["row-2", "row-3", "row-1"]


def test_final_review_primary_actions_remain_visible_at_1366x768(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
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
        ),
        category_names=("Beverages",),
    )
    _set_final_session(app, session)
    app.root.geometry("1366x768+0+0")
    app.root.deiconify()
    app.notebook.select(app.tabs["final"])
    app._render()
    app.root.update()
    app.root.update_idletasks()

    _assert_widgets_inside_root(
        app.root,
        (
            app.final_audit_label,
            app.final_save_profile_button,
            app.edit_final_row_button,
            app.export_button,
        ),
    )
    assert app.final_audit_label.cget("wraplength") >= 320


def test_final_review_filters_rows_by_text_and_flags(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
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
        ),
        category_names=("Beverages", "Snacks"),
    )
    _set_final_session(app, session)
    app.final_filter.set("snack")
    app._render()
    tree = app._tree_widget(app.final_tree)

    assert list(tree.get_children("")) == ["row-2"]

    app.final_filter.set("")
    app.final_flag_filter.set("Published")
    app._populate_final_rows()

    assert list(tree.get_children("")) == ["row-1"]


def test_complete_tab_creates_pos_profile_proposal_from_export(
    app,
    monkeypatch,
    tmp_path,
) -> None:
    export_result = _export_result(tmp_path)
    profile_path = tmp_path / "venue-profile.json"
    profile_path.write_text("{}", encoding="utf-8")
    app.controller = gui_module.AppController()
    app.controller.export_succeeded(export_result)
    app.venue_profile_text.set(str(profile_path))
    app.profile_inference_result = None
    app.profile_inference_running = False
    app._render()

    calls = []

    def infer_profile(final_import, *, existing_profile_path=None, output_root=None):
        calls.append((final_import, existing_profile_path, output_root))
        paths = PosProfileInferencePaths(
            proposed_profile=tmp_path / "profile-out" / "proposal.json",
            inference_audit=tmp_path / "profile-out" / "audit.csv",
            proposed_profile_audit=tmp_path / "profile-out" / "profile-audit.csv",
            manifest=tmp_path / "profile-out" / "manifest.json",
            summary=tmp_path / "profile-out" / "summary.md",
        )
        summary = PosProfileInferenceSummary(
            source_rows=2,
            inferred_rows=2,
            skipped_rows=0,
            proposed_abbreviation_rules=3,
            proposed_acronym_rules=1,
            output_paths=paths,
        )
        return PosProfileInferenceResult(
            run_dir=tmp_path / "profile-out",
            summary=summary,
            inferred_preferences=PosNamePreferenceProfile(abbreviations={}),
            proposed_preferences=PosNamePreferenceProfile(abbreviations={}),
        )

    monkeypatch.setattr(gui_module, "infer_pos_profile_from_final_import", infer_profile)
    monkeypatch.setattr(
        app,
        "_run_worker",
        lambda event_name, operation, *, error_event_name="error": app.events.put(
            (event_name, operation())
        ),
    )
    messages = []
    monkeypatch.setattr(
        gui_module.messagebox,
        "showinfo",
        lambda title, message: messages.append((title, message)),
    )
    opened_paths = []
    monkeypatch.setattr(gui_module, "open_path", opened_paths.append)

    app._start_profile_inference_from_export()
    app._poll_events()
    app.root.update()

    assert calls == [
        (
            export_result.summary.output_paths.final_import,
            profile_path,
            export_result.run_dir / "POS Profile Inference",
        )
    ]
    assert app.profile_inference_result is not None
    assert app.controller.state.message == "POS profile proposal export complete."
    assert str(app.open_profile_proposal_button.cget("state")) == "normal"
    assert messages == [
        (gui_module.APP_TITLE, f"POS profile proposal written to {tmp_path / 'profile-out'}")
    ]

    app._open_profile_inference_result("profile")
    app._open_profile_inference_result("audit")
    app._open_profile_inference_result("folder")

    assert opened_paths == [
        tmp_path / "profile-out" / "proposal.json",
        tmp_path / "profile-out" / "audit.csv",
        tmp_path / "profile-out",
    ]


def test_complete_tab_disables_duplicate_profile_inference_while_running(
    app,
    monkeypatch,
    tmp_path,
) -> None:
    export_result = _export_result(tmp_path)
    app.controller = gui_module.AppController()
    app.controller.export_succeeded(export_result)
    app.profile_inference_result = None
    app.profile_inference_running = False
    app._render()

    started = []

    def hold_worker(event_name, operation, *, error_event_name="error"):
        started.append((event_name, error_event_name))

    monkeypatch.setattr(app, "_run_worker", hold_worker)

    app._start_profile_inference_from_export()
    app.root.update()

    assert started == [("profile_inferred", "profile_inference_error")]
    assert app.profile_inference_running is True
    assert app.controller.state.message == "Creating POS profile proposal..."
    assert str(app.infer_profile_button.cget("state")) == "disabled"


def test_complete_tab_profile_inference_failure_preserves_completed_export(
    app,
    monkeypatch,
    tmp_path,
) -> None:
    export_result = _export_result(tmp_path)
    app.controller = gui_module.AppController()
    app.controller.export_succeeded(export_result)
    app.profile_inference_result = None
    app.profile_inference_running = False
    app._render()

    def fail_worker(event_name, operation, *, error_event_name="error"):
        app.events.put((error_event_name, RuntimeError("bad final CSV")))

    monkeypatch.setattr(app, "_run_worker", fail_worker)
    errors = []
    monkeypatch.setattr(
        gui_module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app._start_profile_inference_from_export()
    app._poll_events()
    app.root.update()

    assert app.controller.state.phase == gui_module.AppPhase.COMPLETE
    assert app.controller.state.result is export_result
    assert app.profile_inference_running is False
    assert app.profile_inference_result is None
    assert app.controller.state.message == "POS profile proposal failed: bad final CSV"
    assert str(app.infer_profile_button.cget("state")) == "normal"
    assert errors == [(gui_module.APP_TITLE, "bad final CSV")]


def test_pos_reason_filter_shows_rows_requiring_attention(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "111",
                category="Beverages",
                pos_name="Duplicate",
                status="pos_needs_review",
                review_reason="duplicate POS name",
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
            _row(
                "row-3",
                "Grape Juice",
                "1.50",
                "333",
                category="Beverages",
                status="pos_needs_review",
                review_reason="missing POS name",
            ),
        ),
    )
    _set_pos_session(app, session)
    app.current_pos_row_id = None
    app.pos_reason_filter.set("Needs review")
    app._render()
    app.notebook.select(app.tabs["pos"])
    app.root.update()

    tree = app._tree_widget(app.pos_tree)

    assert app.pos_reason_combo.cget("values") == (
        "Any",
        "Needs review",
        "duplicate POS name",
        "missing POS name",
    )
    assert list(tree.get_children("")) == ["row-1", "row-3"]

    app.pos_reason_filter.set("duplicate")
    app._populate_pos_rows()
    app.root.update()

    assert list(tree.get_children("")) == ["row-1"]


def test_pos_replace_button_advances_within_filtered_rows_and_focuses_input(
    app, monkeypatch
) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Apple Juice",
                "1.25",
                "111",
                category="Beverages",
                pos_name="Duplicate",
                status="pos_needs_review",
                review_reason="duplicate POS name",
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
            _row(
                "row-3",
                "Grape Juice",
                "1.50",
                "333",
                category="Beverages",
                status="pos_needs_review",
                review_reason="missing POS name",
            ),
        ),
    )
    focus_calls = []
    selection_calls = []
    monkeypatch.setattr(app.pos_entry, "focus_set", lambda: focus_calls.append("focus"))
    monkeypatch.setattr(
        app.pos_entry, "selection_range", lambda start, end: selection_calls.append((start, end))
    )

    _set_pos_session(app, session)
    app.current_pos_row_id = None
    app.pos_reason_filter.set("Needs review")
    app._render()
    app.notebook.select(app.tabs["pos"])
    app._select_pos_tree_row("row-1")
    app._load_pos_row("row-1")
    app.root.update()

    app.pos_name.set("AppleJuice")
    app.replace_pos_button.invoke()
    app.root.update()
    app.root.update_idletasks()

    tree = app._tree_widget(app.pos_tree)
    row_1 = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")

    assert row_1.pos_name == "AppleJuice"
    assert row_1.status == "pos_ready"
    assert list(tree.get_children("")) == ["row-3"]
    assert app.current_pos_row_id == "row-3"
    assert tree.selection() == ("row-3",)
    assert app.pos_name.get() == ""
    assert focus_calls
    assert selection_calls[-1] == (0, tk.END)


def test_pos_entry_return_replaces_valid_name_and_returns_break(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
            _row(
                "row-1",
                "Grape Juice",
                "1.50",
                "333",
                category="Beverages",
                status="pos_needs_review",
                review_reason="missing POS name",
            ),
        ),
    )
    _set_pos_session(app, session)
    app.current_pos_row_id = None
    app.pos_reason_filter.set("Needs review")
    app._render()
    app.notebook.select(app.tabs["pos"])
    app._select_pos_tree_row("row-1")
    app._load_pos_row("row-1")
    app.root.update()

    app.pos_name.set("GrapeJuice")

    assert app._pos_entry_return(_Event()) == "break"

    row_1 = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")
    assert row_1.pos_name == "GrapeJuice"
    assert row_1.status == "pos_ready"
    assert app.current_pos_row_id is None
    assert app.pos_name.get() == ""


def test_final_review_edit_dialog_disables_save_for_invalid_edit(app) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
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
        ),
        category_names=("Beverages",),
    )
    _set_final_session(app, session)
    app._render()
    app.notebook.select(app.tabs["final"])
    tree = app._tree_widget(app.final_tree)
    tree.selection_set("row-1")
    tree.focus("row-1")

    app._open_final_row_edit_dialog()
    app.root.update()
    app.final_edit_vars["pos_name"].set("OrangeJuice")
    app.root.update()

    assert str(app.final_edit_save_button.cget("state")) == "disabled"
    assert "duplicate POS name" in app.final_edit_validation.get()
    app.final_edit_dialog.destroy()


def test_final_review_edit_dialog_confirms_and_saves_valid_edit(app, monkeypatch) -> None:
    session = ImportSession(
        headers=list(LUNCHTAB_TEMPLATE_HEADERS),
        rows=(
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
        ),
        category_names=("Beverages",),
    )
    _set_final_session(app, session)
    app._render()
    app.notebook.select(app.tabs["final"])
    tree = app._tree_widget(app.final_tree)
    tree.selection_set("row-1")
    tree.focus("row-1")
    prompts = []
    monkeypatch.setattr(
        gui_module.messagebox,
        "askyesno",
        lambda title, message: prompts.append((title, message)) or True,
    )

    app._open_final_row_edit_dialog()
    app.root.update()
    app.final_edit_vars["item_name"].set("Apple Bottle")
    app.final_edit_vars["price"].set("1.35")
    app.final_edit_vars["barcode"].set("111, 333")
    app.final_edit_vars["category"].set("Drinks")
    app.final_edit_vars["pos_name"].set("Apple Bottle")
    app.final_edit_vars["is_published"].set(True)
    app.final_edit_vars["is_orderable"].set(True)
    app.final_edit_vars["core_catalogue"].set(True)
    app.root.update()

    assert str(app.final_edit_save_button.cget("state")) == "normal"
    assert app._save_final_row_edit("row-1") == "break"
    app.root.update()

    row = next(row for row in app.controller.state.session.rows if row.row_id == "row-1")
    tree = app._tree_widget(app.final_tree)
    assert prompts == [(gui_module.APP_TITLE, "Save edits to this final review row?")]
    assert row.item_name == "Apple Bottle"
    assert row.price == "1.35"
    assert row.barcode == "111,333"
    assert row.category == "Drinks"
    assert row.pos_name == "Apple Bottle"
    assert row.is_published is True
    assert row.is_orderable is True
    assert row.core_catalogue is True
    assert row.edited is True
    assert tree.set("row-1", "name") == "Apple Bottle"
    assert tree.set("row-1", "published") == "true"
    assert tree.set("row-1", "orderable") == "true"
    assert tree.set("row-1", "core") == "true"


class _Event:
    pass


class _KeyEvent:
    def __init__(self, widget: tk.Widget, keysym: str) -> None:
        self.widget = widget
        self.keysym = keysym


def _clear_category_filter_vars(app: ProductInitializationApp) -> None:
    app.category_filter.set("")
    app.name_filter.set("Any")
    app.old_category_filter.set("")
    app.barcode_filter.set("Any")
    app.category_assignment_filter.set("Any")
    app.price_operator.set("=")
    app.min_price.set("")
    app.max_price.set("")
    app.stock_operator.set("Any")
    app.stock_value.set("")
    app.stock_upper.set("")
    app._category_filter_after_id = None


def _set_pos_session(app: ProductInitializationApp, session: ImportSession) -> None:
    app.controller = gui_module.AppController()
    app.odin_inventory_text.set("")
    app.generic_inventory_text.set("")
    app.controller.set_session(session, phase=gui_module.AppPhase.POS_REVIEW)


def _set_final_session(app: ProductInitializationApp, session: ImportSession) -> None:
    app.controller = gui_module.AppController()
    app.odin_inventory_text.set("")
    app.generic_inventory_text.set("")
    app.final_filter.set("")
    app.final_flag_filter.set("Any")
    app.controller.set_session(session, phase=gui_module.AppPhase.FINAL_REVIEW)


def _export_result(tmp_path) -> SessionExportResult:
    run_dir = tmp_path / "export-run"
    paths = SessionOutputPaths(
        final_import=run_dir / "Lunchtab Product Import.csv",
        core_catalogue=run_dir / "Core Catalogue.csv",
        category_audit=run_dir / "Product Category Audit.csv",
        naming_audit=run_dir / "BaseProductPosName Audit.csv",
        pos_profile_audit=run_dir / "POS Preference Profile.csv",
        session_audit=run_dir / "Session Review Audit.csv",
        deleted_audit=run_dir / "Deleted Product Audit.csv",
        manifest=run_dir / "run-manifest.json",
        summary=run_dir / "run-summary.md",
    )
    summary = SessionBuildSummary(
        parsed_rows=2,
        exported_rows=2,
        deleted_rows=0,
        edited_rows=0,
        category_count=1,
        pos_overrides=0,
        pos_light_edits=0,
        pos_moderate_edits=0,
        pos_heavy_overrides=0,
        duplicate_barcodes=0,
        duplicate_pos_names=0,
        core_catalogue_rows=0,
        output_paths=paths,
    )
    return SessionExportResult(run_dir=run_dir, summary=summary)


def _assert_widgets_inside_root(root: tk.Tk, widgets: tuple[tk.Widget, ...]) -> None:
    root_left = root.winfo_rootx()
    root_top = root.winfo_rooty()
    root_right = root_left + root.winfo_width()
    root_bottom = root_top + root.winfo_height()
    if root.winfo_width() <= 1 or root.winfo_height() <= 1:
        pytest.skip("Tk did not expose root geometry for layout test.")
    for widget in widgets:
        assert widget.winfo_ismapped(), f"{widget} is not mapped"
        widget_left = widget.winfo_rootx()
        widget_top = widget.winfo_rooty()
        widget_right = widget_left + widget.winfo_width()
        widget_bottom = widget_top + widget.winfo_height()
        assert root_left <= widget_left < widget_right <= root_right
        assert root_top <= widget_top < widget_bottom <= root_bottom


def _row(
    row_id: str,
    name: str,
    price: str,
    barcode: str,
    *,
    category: str = "",
    pos_name: str = "",
    status: str = "active",
    review_reason: str = "",
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
            category=category,
            stock=stock,
        ),
        old_category=category,
        category=category,
        pos_name=pos_name,
        status=status,  # type: ignore[arg-type]
        review_reason=review_reason,
        is_published=is_published,
        is_orderable=is_orderable,
        core_catalogue=core_catalogue,
    )
