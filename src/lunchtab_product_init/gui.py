from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from lunchtab_product_init.desktop import friendly_error, open_path
from lunchtab_product_init.gui_controller import AppController, AppPhase
from lunchtab_product_init.session_workflow import (
    ImportSession,
    assign_category,
    delete_rows,
    export_session,
    filter_rows,
    mark_for_edit,
    next_edit_row,
    no_barcode_rows,
    parse_sources,
    replace_pos_name,
    run_pos_generation,
    save_edit,
    save_venue_profile,
    suggest_pos_names,
)
from lunchtab_product_init.ui_helpers import size_and_center

APP_TITLE = "Lunchtab Product Initialization"


class ProductInitializationApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.controller = AppController()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.category_selection: set[str] = set()
        self.category_undo_stack: list[ImportSession] = []
        self.edit_selection: set[str] = set()
        self.edit_no_barcode_only = False
        self.current_edit_row_id: str | None = None
        self.current_pos_row_id: str | None = None

        root.title(APP_TITLE)
        size_and_center(root, 1120, 760)

        self.product_template_text = tk.StringVar()
        self.recipe_list_text = tk.StringVar()
        self.odin_inventory_text = tk.StringVar()
        self.output_text = tk.StringVar(value=str(self.controller.state.output_root))
        self.status_text = tk.StringVar(value=self.controller.state.message)
        self.is_orderable = tk.BooleanVar(value=False)
        self.category_name = tk.StringVar()
        self.category_filter = tk.StringVar()
        self.price_operator = tk.StringVar(value="=")
        self.min_price = tk.StringVar()
        self.max_price = tk.StringVar()
        self.selected_category = tk.StringVar()
        self.edit_name = tk.StringVar()
        self.edit_price = tk.StringVar()
        self.edit_barcode = tk.StringVar()
        self.edit_category = tk.StringVar()
        self.pos_name = tk.StringVar()
        self.pos_validation = tk.StringVar()
        self.audit_text = tk.StringVar()

        self._build()
        self._render()
        root.after(100, self._poll_events)

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(16, 14, 16, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 17, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, textvariable=self.status_text).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.tabs: dict[str, ttk.Frame] = {}
        for key, label in (
            ("parse", "1 Parse Sources"),
            ("categories", "2 Categories"),
            ("edit", "3 Edit Review"),
            ("pos", "4 POS Names"),
            ("final", "5 Final Review"),
            ("complete", "6 Export Complete"),
        ):
            frame = ttk.Frame(self.notebook, padding=12)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            self.tabs[key] = frame
            self.notebook.add(frame, text=label)

        self._build_parse_tab()
        self._build_categories_tab()
        self._build_edit_tab()
        self._build_pos_tab()
        self._build_final_tab()
        self._build_complete_tab()

        footer = ttk.Frame(self.root, padding=(16, 0, 16, 14))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 12))

    def _build_parse_tab(self) -> None:
        parent = self.tabs["parse"]
        form = ttk.LabelFrame(parent, text="Source files", padding=14)
        form.grid(row=0, column=0, sticky="new")
        form.columnconfigure(1, weight=1)
        self._file_row(form, 0, "ProductData template", self.product_template_text, self._choose_template)
        self._file_row(form, 1, "Recipe list", self.recipe_list_text, self._choose_recipe)
        self._file_row(form, 2, "Odin inventory", self.odin_inventory_text, self._choose_odin)
        self._file_row(form, 3, "Save results in", self.output_text, self._choose_output)
        ttk.Checkbutton(
            form,
            text="Set target CSV IsOrderable to true",
            variable=self.is_orderable,
            command=self._set_is_orderable,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
        actions = ttk.Frame(parent)
        actions.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        self.parse_button = ttk.Button(actions, text="Parse sources", command=self._start_parse)
        self.parse_button.grid(row=0, column=0, sticky="ew")

    def _build_categories_tab(self) -> None:
        parent = self.tabs["categories"]
        body = ttk.Frame(parent)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        tools = ttk.Frame(body)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tools.columnconfigure(8, weight=1)
        ttk.Label(tools, text="New category").grid(row=0, column=0, sticky="w")
        self.category_entry = ttk.Entry(tools, textvariable=self.category_name, width=22)
        self.category_entry.grid(row=0, column=1, padx=(6, 8), sticky="w")
        self.category_entry.bind("<Return>", lambda _event: (self._add_category(), "break")[1])
        ttk.Button(tools, text="Add", command=self._add_category).grid(row=0, column=2, sticky="w")
        ttk.Button(tools, text="Undo", command=self._undo_category_action).grid(row=0, column=3, padx=(10, 0))

        ttk.Label(tools, text="Keyword filter").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(tools, textvariable=self.category_filter, width=22).grid(
            row=1, column=1, padx=(6, 8), sticky="w", pady=(8, 0)
        )
        ttk.Label(tools, text="Price filter").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.price_operator_combo = ttk.Combobox(
            tools,
            textvariable=self.price_operator,
            values=("=", "<", ">", "<=", ">=", "range", "No price"),
            state="readonly",
            width=8,
        )
        self.price_operator_combo.grid(row=1, column=3, padx=(6, 4), sticky="w", pady=(8, 0))
        self.price_operator_combo.bind("<<ComboboxSelected>>", lambda _event: self._price_operator_changed())
        self.price_value_entry = ttk.Entry(tools, textvariable=self.min_price, width=10)
        self.price_value_entry.grid(row=1, column=4, padx=(0, 4), sticky="w", pady=(8, 0))
        ttk.Label(tools, text="Upper bound").grid(row=1, column=5, sticky="w", pady=(8, 0))
        self.price_upper_entry = ttk.Entry(tools, textvariable=self.max_price, width=10)
        self.price_upper_entry.grid(row=1, column=6, padx=(6, 8), sticky="w", pady=(8, 0))
        ttk.Button(tools, text="Apply filter", command=self._refresh_category_rows).grid(
            row=1, column=7, sticky="w", pady=(8, 0)
        )

        self.category_tree = self._tree(
            body,
            ("selected", "name", "price", "barcode", "category", "status"),
            ("Select", "Item Name", "Price", "Barcode", "Category", "Status"),
        )
        self.category_tree.grid(row=1, column=0, sticky="nsew")
        self._tree_widget(self.category_tree).bind("<Button-1>", self._category_tree_click)
        self._tree_widget(self.category_tree).bind("<Double-1>", self._category_tree_double_click)

        actions = ttk.Frame(body)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Select all shown", command=self._select_all_category_rows).pack(side="left")
        ttk.Button(actions, text="Deselect all shown", command=self._deselect_all_category_rows).pack(side="left", padx=(8, 0))
        self.category_combo = ttk.Combobox(actions, textvariable=self.selected_category, state="readonly", width=24)
        self.category_combo.pack(side="left", padx=8)
        ttk.Button(actions, text="Assign category", command=self._assign_category).pack(side="left")
        ttk.Button(actions, text="Mark for edit", command=self._mark_category_for_edit).pack(side="left", padx=8)
        ttk.Button(actions, text="Delete rows", command=self._delete_category_rows).pack(side="left")
        self.save_profile_button = ttk.Button(actions, text="Save venue profile...", command=self._save_profile)
        self.save_profile_button.pack(side="right")
        self.to_edit_button = ttk.Button(actions, text="Next: Edit review", command=self._go_to_edit)
        self.to_edit_button.pack(side="right", padx=8)
        self._price_operator_changed()

    def _build_edit_tab(self) -> None:
        parent = self.tabs["edit"]
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        split = ttk.PanedWindow(parent, orient="horizontal")
        split.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(split, padding=(0, 0, 8, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        split.add(left, weight=2)
        tools = ttk.Frame(left)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(tools, text="No barcode", command=self._show_no_barcode_rows).pack(side="left")
        ttk.Button(tools, text="All review rows", command=self._show_all_edit_rows).pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="Select all shown", command=self._select_all_edit_rows).pack(side="left", padx=6)
        ttk.Button(tools, text="Toggle selected row", command=self._toggle_edit_selection).pack(side="left")
        ttk.Button(tools, text="Delete selected", command=self._delete_edit_rows).pack(side="left")
        self.edit_tree = self._tree(
            left,
            ("selected", "name", "price", "barcode", "category", "reason"),
            ("Sel", "Item Name", "Price", "Barcode", "Category", "Reason"),
        )
        self.edit_tree.grid(row=1, column=0, sticky="nsew")
        self.edit_tree.bind("<Double-1>", lambda _event: self._load_selected_edit_row())

        form = ttk.LabelFrame(split, text="Row edit", padding=12)
        form.columnconfigure(1, weight=1)
        split.add(form, weight=1)
        for row, (label, variable) in enumerate(
            (
                ("Name", self.edit_name),
                ("Price", self.edit_price),
                ("Barcode", self.edit_barcode),
                ("Category", self.edit_category),
            )
        ):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        self.save_edit_button = ttk.Button(form, text="Save row edit", command=self._save_edit)
        self.save_edit_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(form, text="Delete current row", command=self._delete_current_edit_row).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        self.to_pos_button = ttk.Button(form, text="Next: POS names", command=self._go_to_pos)
        self.to_pos_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 0))

    def _build_pos_tab(self) -> None:
        parent = self.tabs["pos"]
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        split = ttk.PanedWindow(parent, orient="horizontal")
        split.grid(row=0, column=0, sticky="nsew")
        left = ttk.Frame(split, padding=(0, 0, 8, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        split.add(left, weight=2)
        self.pos_tree = self._tree(
            left,
            ("name", "pos", "status", "reason"),
            ("Item Name", "BaseProductPosName", "Status", "Reason"),
        )
        self.pos_tree.grid(row=0, column=0, sticky="nsew")
        self.pos_tree.bind("<Double-1>", lambda _event: self._load_selected_pos_row())

        editor = ttk.LabelFrame(split, text="POS-name steering", padding=12)
        editor.columnconfigure(0, weight=1)
        split.add(editor, weight=1)
        ttk.Entry(editor, textvariable=self.pos_name).grid(row=0, column=0, sticky="ew")
        ttk.Label(editor, textvariable=self.pos_validation, foreground="#8a1f11").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.replace_pos_button = ttk.Button(editor, text="Replace", command=self._replace_pos)
        self.replace_pos_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(editor, text="Suggestions").grid(row=3, column=0, sticky="w", pady=(14, 4))
        self.suggestion_frame = ttk.Frame(editor)
        self.suggestion_frame.grid(row=4, column=0, sticky="ew")
        self.to_final_button = ttk.Button(editor, text="Next: Final review", command=self._go_to_final)
        self.to_final_button.grid(row=5, column=0, sticky="ew", pady=(20, 0))

    def _build_final_tab(self) -> None:
        parent = self.tabs["final"]
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        self.final_tree = self._tree(
            parent,
            ("name", "pos", "price", "barcode", "category"),
            ("BaseProductName", "BaseProductPosName", "Price", "Barcode", "ProductCategories"),
        )
        self.final_tree.grid(row=0, column=0, sticky="nsew")
        bottom = ttk.Frame(parent)
        bottom.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.audit_text, justify="left").grid(row=0, column=0, sticky="w")
        self.export_button = ttk.Button(bottom, text="Confirm and export", command=self._start_export)
        self.export_button.grid(row=0, column=1, sticky="e")

    def _build_complete_tab(self) -> None:
        parent = self.tabs["complete"]
        panel = ttk.LabelFrame(parent, text="Export destinations", padding=14)
        panel.grid(row=0, column=0, sticky="new")
        panel.columnconfigure(0, weight=1)
        self.open_buttons = {
            "folder": ttk.Button(panel, text="Open results folder", command=lambda: self._open_result("folder")),
            "final": ttk.Button(panel, text="Open import CSV", command=lambda: self._open_result("final")),
            "category": ttk.Button(panel, text="Open category audit", command=lambda: self._open_result("category")),
            "naming": ttk.Button(panel, text="Open POS-name audit", command=lambda: self._open_result("naming")),
            "deleted": ttk.Button(panel, text="Open deleted-row audit", command=lambda: self._open_result("deleted")),
            "summary": ttk.Button(panel, text="Open run summary", command=lambda: self._open_result("summary")),
        }
        for index, button in enumerate(self.open_buttons.values()):
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=6, pady=5)
            panel.columnconfigure(index % 2, weight=1)

    @staticmethod
    def _file_row(parent, row: int, label: str, variable: tk.StringVar, command: Callable[[], None]) -> None:
        ttk.Label(parent, text=label, width=22).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, state="readonly").grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, pady=5)

    @staticmethod
    def _tree(parent, columns: tuple[str, ...], labels: tuple[str, ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        for column, label in zip(columns, labels, strict=True):
            tree.heading(column, text=label)
            tree.column(column, width=90 if column in {"selected", "price", "status"} else 170)
        y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        return frame

    def _tree_widget(self, frame: ttk.Frame) -> ttk.Treeview:
        return next(child for child in frame.winfo_children() if isinstance(child, ttk.Treeview))

    def _choose_template(self) -> None:
        self._choose_file("Select ProductData template", [("CSV files", "*.csv")], self.product_template_text, self.controller.select_product_template)

    def _choose_recipe(self) -> None:
        self._choose_file("Select recipe list", [("CSV files", "*.csv")], self.recipe_list_text, self.controller.select_recipe_list)

    def _choose_odin(self) -> None:
        self._choose_file("Select Odin inventory workbook", [("Excel workbooks", "*.xlsx")], self.odin_inventory_text, self.controller.select_odin_inventory)

    def _choose_file(self, title: str, filetypes, variable: tk.StringVar, setter) -> None:
        selected = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if selected:
            variable.set(selected)
            setter(Path(selected))
            self._render()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose the parent folder for timestamped results")
        if selected:
            self.output_text.set(selected)
            self.controller.select_output_root(Path(selected))
            self._render()

    def _set_is_orderable(self) -> None:
        self.controller.set_is_orderable(bool(self.is_orderable.get()))
        self._render()

    def _start_parse(self) -> None:
        self.controller.begin_parse()
        inputs = self.controller.build_inputs()
        self._run_worker("parsed", lambda: parse_sources(inputs))
        self._render()

    def _start_export(self) -> None:
        state = self.controller.begin_export()
        inputs = self.controller.build_inputs()
        session = state.session
        if session is None:
            raise RuntimeError("Parse source files before exporting.")
        self._run_worker("exported", lambda: export_session(session, inputs, is_orderable=state.is_orderable))
        self._render()

    def _run_worker(self, event_name: str, operation: Callable[[], object]) -> None:
        def work() -> None:
            try:
                self.events.put((event_name, operation()))
            except Exception as error:
                self.events.put(("error", error))

        threading.Thread(target=work, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                name, payload = self.events.get_nowait()
                if name == "parsed":
                    self.controller.parse_succeeded(payload)  # type: ignore[arg-type]
                elif name == "exported":
                    self.controller.export_succeeded(payload)  # type: ignore[arg-type]
                else:
                    message = friendly_error(payload)
                    self.controller.failed(message)
                    messagebox.showerror(APP_TITLE, message)
                self._render()
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._poll_events)

    def _add_category(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        from lunchtab_product_init.session_workflow import add_category

        next_session = add_category(session, self.category_name.get())
        if next_session != session:
            self._push_category_undo()
            self.controller.set_session(next_session)
        self.category_name.set("")
        self.category_entry.focus_set()
        self._render()

    def _refresh_category_rows(self) -> None:
        self._populate_category_rows()

    def _toggle_category_selection(self) -> None:
        tree = self._tree_widget(self.category_tree)
        row_id = self._selected_iid(tree)
        if not row_id:
            return
        self._toggle_category_row(row_id)

    def _toggle_category_row(self, row_id: str) -> None:
        if row_id in self.category_selection:
            self.category_selection.remove(row_id)
        else:
            self.category_selection.add(row_id)
        self._populate_category_rows()

    def _category_tree_click(self, event: tk.Event) -> str | None:
        tree = self._tree_widget(self.category_tree)
        if tree.identify("region", event.x, event.y) != "cell":
            return None
        if tree.identify_column(event.x) != "#1":
            return None
        row_id = tree.identify_row(event.y)
        if row_id:
            tree.selection_set(row_id)
            self._toggle_category_row(row_id)
            return "break"
        return None

    def _category_tree_double_click(self, event: tk.Event) -> str | None:
        tree = self._tree_widget(self.category_tree)
        row_id = tree.identify_row(event.y) or self._selected_iid(tree)
        if row_id:
            tree.selection_set(row_id)
            self._toggle_category_row(row_id)
            return "break"
        return None

    def _select_all_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection.update(tree.get_children(""))
        self._populate_category_rows()

    def _deselect_all_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection.difference_update(tree.get_children(""))
        self._populate_category_rows()

    def _assign_category(self) -> None:
        session = self.controller.state.session
        if session is None or not self.category_selection:
            return
        category = self.selected_category.get() or self.category_name.get()
        next_session = assign_category(session, set(self.category_selection), category)
        if next_session != session:
            self._push_category_undo()
            self.controller.set_session(next_session)
            self.category_selection.clear()
            self._render()

    def _mark_category_for_edit(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        next_session = mark_for_edit(session, set(self.category_selection))
        if next_session != session:
            self._push_category_undo()
            self.controller.set_session(next_session)
            self.category_selection.clear()
            self._render()

    def _delete_category_rows(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        next_session = delete_rows(session, set(self.category_selection))
        if next_session != session:
            self._push_category_undo()
            self.controller.set_session(next_session)
            self.category_selection.clear()
            self._render()

    def _push_category_undo(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        self.category_undo_stack.append(session)

    def _undo_category_action(self) -> None:
        if not self.category_undo_stack:
            return
        self.controller.set_session(self.category_undo_stack.pop())
        self.category_selection.clear()
        self._render()

    def _price_operator_changed(self) -> None:
        range_enabled = self.price_operator.get() == "range"
        no_price = self.price_operator.get() == "No price"
        self.price_value_entry.configure(state="disabled" if no_price else "normal")
        self.price_upper_entry.configure(state="normal" if range_enabled and not no_price else "disabled")
        if not range_enabled:
            self.max_price.set("")
        if no_price:
            self.min_price.set("")
        self._populate_category_rows()

    def _go_to_edit(self) -> None:
        self.controller.go_to_edit_review()
        self._load_next_edit_row()
        self._render()

    def _show_no_barcode_rows(self) -> None:
        self.edit_no_barcode_only = True
        self.edit_selection.clear()
        self._populate_edit_rows()

    def _show_all_edit_rows(self) -> None:
        self.edit_no_barcode_only = False
        self._populate_edit_rows()

    def _select_all_edit_rows(self) -> None:
        tree = self._tree_widget(self.edit_tree)
        self.edit_selection.update(tree.get_children(""))
        self._populate_edit_rows()

    def _toggle_edit_selection(self) -> None:
        row_id = self._selected_iid(self._tree_widget(self.edit_tree))
        if not row_id:
            return
        if row_id in self.edit_selection:
            self.edit_selection.remove(row_id)
        else:
            self.edit_selection.add(row_id)
        self._populate_edit_rows()

    def _load_selected_edit_row(self) -> None:
        row_id = self._selected_iid(self._tree_widget(self.edit_tree))
        if row_id:
            self._load_edit_row(row_id)

    def _delete_edit_rows(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        self.controller.set_session(delete_rows(session, set(self.edit_selection), "edit review deletion"))
        self.edit_selection.clear()
        self._load_next_edit_row()
        self._render()

    def _delete_current_edit_row(self) -> None:
        if self.current_edit_row_id:
            self.edit_selection = {self.current_edit_row_id}
            self._delete_edit_rows()

    def _save_edit(self) -> None:
        session = self.controller.state.session
        if session is None or self.current_edit_row_id is None:
            return
        self.controller.set_session(
            save_edit(
                session,
                self.current_edit_row_id,
                item_name=self.edit_name.get(),
                price=self.edit_price.get(),
                barcode=self.edit_barcode.get(),
                category=self.edit_category.get(),
            )
        )
        self._load_next_edit_row()
        self._render()

    def _go_to_pos(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        self.controller.set_session(run_pos_generation(session))
        self.controller.go_to_pos_review()
        self._render()

    def _load_selected_pos_row(self) -> None:
        row_id = self._selected_iid(self._tree_widget(self.pos_tree))
        if row_id:
            self.current_pos_row_id = row_id
            row = self._row(row_id)
            self.pos_name.set(row.pos_name if row else "")
            self._refresh_suggestions()
            self._render()

    def _replace_pos(self) -> None:
        session = self.controller.state.session
        if session is None or self.current_pos_row_id is None:
            return
        self.controller.set_session(replace_pos_name(session, self.current_pos_row_id, self.pos_name.get()))
        self._refresh_suggestions()
        self._render()

    def _go_to_final(self) -> None:
        self.controller.go_to_final_review()
        self._render()

    def _save_profile(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        selected = filedialog.asksaveasfilename(
            title="Save venue profile",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not selected:
            return
        try:
            save_venue_profile(session, Path(selected))
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))
            return
        messagebox.showinfo(APP_TITLE, f"Venue profile saved to {selected}")

    def _open_result(self, target: str) -> None:
        result = self.controller.state.result
        if result is None:
            return
        paths = result.summary.output_paths
        targets = {
            "folder": result.run_dir,
            "final": paths.final_import,
            "category": paths.category_audit,
            "naming": paths.naming_audit,
            "deleted": paths.deleted_audit,
            "summary": paths.summary,
        }
        try:
            open_path(targets[target])
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _render(self) -> None:
        state = self.controller.state
        busy = state.phase in {AppPhase.PARSING, AppPhase.EXPORTING}
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()
        self.status_text.set(state.message)
        self.parse_button.configure(state="normal" if state.can_parse and not busy else "disabled")
        self.to_edit_button.configure(state="normal" if state.can_leave_categories else "disabled")
        self.to_pos_button.configure(state="normal" if state.can_leave_edit_review else "disabled")
        self.to_final_button.configure(state="normal" if state.can_leave_pos_review else "disabled")
        self.export_button.configure(state="normal" if state.can_export else "disabled")
        self.replace_pos_button.configure(state="normal" if self.current_pos_row_id else "disabled")
        if state.phase == AppPhase.CATEGORIZING:
            self.notebook.select(self.tabs["categories"])
        elif state.phase == AppPhase.EDIT_REVIEW:
            self.notebook.select(self.tabs["edit"])
        elif state.phase == AppPhase.POS_REVIEW:
            self.notebook.select(self.tabs["pos"])
        elif state.phase == AppPhase.FINAL_REVIEW:
            self.notebook.select(self.tabs["final"])
        elif state.phase == AppPhase.COMPLETE:
            self.notebook.select(self.tabs["complete"])
        self._populate_category_rows()
        self._populate_edit_rows()
        self._populate_pos_rows()
        self._populate_final_rows()

    def _populate_category_rows(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.category_tree)
        self._clear(tree)
        if session is None:
            return
        rows = filter_rows(
            session,
            keyword=self.category_filter.get(),
            price_operator=self.price_operator.get(),  # type: ignore[arg-type]
            price_value=self.min_price.get(),
            price_upper=self.max_price.get(),
        )
        self.category_combo.configure(values=session.category_names)
        for row in rows:
            tree.insert(
                "",
                "end",
                iid=row.row_id,
                values=(
                    "[x]" if row.row_id in self.category_selection else "[ ]",
                    row.item_name,
                    row.price,
                    row.barcode,
                    row.category,
                    row.status,
                ),
            )

    def _populate_edit_rows(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.edit_tree)
        self._clear(tree)
        if session is None:
            return
        rows = no_barcode_rows(session) if self.edit_no_barcode_only else session.edit_queue
        for row in rows:
            tree.insert(
                "",
                "end",
                iid=row.row_id,
                values=(
                    "X" if row.row_id in self.edit_selection else "",
                    row.item_name,
                    row.price,
                    row.barcode,
                    row.category,
                    row.review_reason,
                ),
            )

    def _populate_pos_rows(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.pos_tree)
        self._clear(tree)
        if session is None:
            return
        for row in session.active_rows:
            tree.insert("", "end", iid=row.row_id, values=(row.item_name, row.pos_name, row.status, row.review_reason))
        if self.current_pos_row_id:
            row = self._row(self.current_pos_row_id)
            self.pos_validation.set(row.review_reason if row else "")

    def _populate_final_rows(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.final_tree)
        self._clear(tree)
        if session is None:
            self.audit_text.set("")
            return
        for row in session.active_rows:
            tree.insert("", "end", iid=row.row_id, values=(row.item_name, row.pos_name, row.price, row.barcode, row.category))
        self.audit_text.set(
            f"Parsed rows: {len(session.rows)}    Deleted rows: {len(session.deleted_rows)}    "
            f"Active rows: {len(session.active_rows)}    Categories: {len(session.category_names)}    "
            f"POS overrides: {sum(1 for row in session.rows if row.pos_overridden)}    "
            f"IsOrderable: {'true' if self.controller.state.is_orderable else 'false'}"
        )

    def _load_next_edit_row(self) -> None:
        session = self.controller.state.session
        row = next_edit_row(session) if session else None
        if row is None:
            self.current_edit_row_id = None
            self.edit_name.set("")
            self.edit_price.set("")
            self.edit_barcode.set("")
            self.edit_category.set("")
            return
        self._load_edit_row(row.row_id)

    def _load_edit_row(self, row_id: str) -> None:
        row = self._row(row_id)
        if row is None:
            return
        self.current_edit_row_id = row_id
        self.edit_name.set(row.item_name)
        self.edit_price.set(row.price)
        self.edit_barcode.set(row.barcode)
        self.edit_category.set(row.category)

    def _refresh_suggestions(self) -> None:
        for child in self.suggestion_frame.winfo_children():
            child.destroy()
        session = self.controller.state.session
        if session is None or self.current_pos_row_id is None:
            return
        for suggestion in suggest_pos_names(session, self.current_pos_row_id):
            ttk.Button(
                self.suggestion_frame,
                text=suggestion,
                command=lambda value=suggestion: self.pos_name.set(value),
            ).pack(fill="x", pady=2)

    def _row(self, row_id: str):
        session = self.controller.state.session
        if session is None:
            return None
        return next((row for row in session.rows if row.row_id == row_id), None)

    @staticmethod
    def _clear(tree: ttk.Treeview) -> None:
        for item in tree.get_children(""):
            tree.delete(item)

    @staticmethod
    def _selected_iid(tree: ttk.Treeview) -> str | None:
        selected = tree.selection()
        return str(selected[0]) if selected else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-test", action="store_true")
    return parser


def main() -> None:
    args, _ = build_parser().parse_known_args()
    if args.smoke_test:
        return
    root = tk.Tk()
    ProductInitializationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
