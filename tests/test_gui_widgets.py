from __future__ import annotations

import tkinter as tk

import pytest

from lunchtab_product_init import gui as gui_module
from lunchtab_product_init.gui import ProductInitializationApp
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS, ProductCandidate
from lunchtab_product_init.session_workflow import ImportSession, SessionRow


@pytest.fixture
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


class _Event:
    pass


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
