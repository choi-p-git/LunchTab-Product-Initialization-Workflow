from __future__ import annotations

import tkinter as tk

import pytest

from lunchtab_product_init import gui as gui_module
from lunchtab_product_init.gui import ProductInitializationApp
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.session_workflow import ImportSession, SessionRow


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


def test_inventory_file_selection_clears_alternate_inventory_source(app, monkeypatch) -> None:
    selections = iter(("C:/source/inventory.xlsx", "C:/source/inventory.csv"))
    monkeypatch.setattr(gui_module.filedialog, "askopenfilename", lambda **_kwargs: next(selections))

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
    app._category_filter_after_id = None


def _row(row_id: str, name: str, price: str, barcode: str, *, category: str = "") -> SessionRow:
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
        old_category=category,
        category=category,
    )
