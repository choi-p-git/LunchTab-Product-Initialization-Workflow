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
    VenueProfile,
    assign_category,
    apply_venue_profile,
    delete_rows,
    export_session,
    filter_rows,
    filter_pos_rows,
    format_barcodes,
    load_venue_profile,
    mark_for_edit,
    merge_rows,
    next_edit_row,
    no_barcode_rows,
    parse_barcodes,
    parse_sources,
    replace_pos_name,
    run_pos_generation,
    save_edit,
    save_venue_profile,
    suggest_pos_names,
    validate_pos_name,
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
        self.edit_undo_stack: list[ImportSession] = []
        self.edit_selection: set[str] = set()
        self.edit_no_barcode_only = False
        self.current_edit_row_id: str | None = None
        self.current_pos_row_id: str | None = None
        self._suppress_pos_selection_event = False

        root.title(APP_TITLE)
        size_and_center(root, 1120, 760)

        self.product_template_text = tk.StringVar()
        self.recipe_list_text = tk.StringVar()
        self.odin_inventory_text = tk.StringVar()
        self.venue_profile_text = tk.StringVar()
        self.output_text = tk.StringVar(value=str(self.controller.state.output_root))
        self.status_text = tk.StringVar(value=self.controller.state.message)
        self.is_orderable = tk.BooleanVar(value=False)
        self.category_name = tk.StringVar()
        self.category_filter = tk.StringVar()
        self.old_category_filter = tk.StringVar()
        self.barcode_filter = tk.StringVar(value="Any")
        self.category_assignment_filter = tk.StringVar(value="Any")
        self.price_operator = tk.StringVar(value="=")
        self.min_price = tk.StringVar()
        self.max_price = tk.StringVar()
        self.selected_category = tk.StringVar()
        self.edit_name = tk.StringVar()
        self.edit_price = tk.StringVar()
        self.edit_barcode = tk.StringVar()
        self.edit_category = tk.StringVar()
        self.pos_name = tk.StringVar()
        self.pos_reason_filter = tk.StringVar(value="Any")
        self.pos_validation = tk.StringVar()
        self.audit_text = tk.StringVar()
        self.inline_category_combo: ttk.Combobox | None = None
        self.venue_profile: VenueProfile | None = None

        for variable in (self.edit_name, self.edit_price, self.edit_barcode, self.edit_category):
            variable.trace_add("write", lambda *_args: self._update_edit_action_state())
        self.pos_name.trace_add("write", lambda *_args: self._update_pos_action_state())

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
        self._file_row(form, 3, "Venue profile", self.venue_profile_text, self._choose_venue_profile)
        self._file_row(form, 4, "Save results in", self.output_text, self._choose_output)
        ttk.Checkbutton(
            form,
            text="Set target CSV IsOrderable to true",
            variable=self.is_orderable,
            command=self._set_is_orderable,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))
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
        tools.columnconfigure(10, weight=1)
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
        ttk.Label(tools, text="Old category filter").grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )
        self.old_category_combo = ttk.Combobox(
            tools,
            textvariable=self.old_category_filter,
            width=18,
        )
        self.old_category_combo.grid(
            row=1, column=3, padx=(6, 8), sticky="w", pady=(8, 0)
        )
        self.old_category_combo.bind("<Return>", lambda _event: self._refresh_category_rows())
        self.old_category_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_category_rows())
        ttk.Label(tools, text="Price filter").grid(row=1, column=4, sticky="w", pady=(8, 0))
        self.price_operator_combo = ttk.Combobox(
            tools,
            textvariable=self.price_operator,
            values=("=", "<", ">", "<=", ">=", "range", "No price"),
            state="readonly",
            width=8,
        )
        self.price_operator_combo.grid(row=1, column=5, padx=(6, 4), sticky="w", pady=(8, 0))
        self.price_operator_combo.bind("<<ComboboxSelected>>", lambda _event: self._price_operator_changed())
        self.price_value_entry = ttk.Entry(tools, textvariable=self.min_price, width=10)
        self.price_value_entry.grid(row=1, column=6, padx=(0, 4), sticky="w", pady=(8, 0))
        ttk.Label(tools, text="Upper bound").grid(row=1, column=7, sticky="w", pady=(8, 0))
        self.price_upper_entry = ttk.Entry(tools, textvariable=self.max_price, width=10)
        self.price_upper_entry.grid(row=1, column=8, padx=(6, 8), sticky="w", pady=(8, 0))
        ttk.Button(tools, text="Apply filter", command=self._refresh_category_rows).grid(
            row=1, column=9, sticky="w", pady=(8, 0)
        )
        ttk.Label(tools, text="Barcode filter").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.barcode_filter_combo = ttk.Combobox(
            tools,
            textvariable=self.barcode_filter,
            values=("Any", "No barcode", "SAGEMB", "Vendor"),
            state="readonly",
            width=12,
        )
        self.barcode_filter_combo.grid(
            row=2, column=1, padx=(6, 8), sticky="w", pady=(8, 0)
        )
        self.barcode_filter_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_category_rows()
        )
        ttk.Label(tools, text="Category filter").grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.category_assignment_filter_combo = ttk.Combobox(
            tools,
            textvariable=self.category_assignment_filter,
            values=("Any", "No category", "Has category"),
            state="readonly",
            width=14,
        )
        self.category_assignment_filter_combo.grid(
            row=2, column=3, padx=(6, 8), sticky="w", pady=(8, 0)
        )
        self.category_assignment_filter_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_category_rows()
        )

        self.category_tree = self._tree(
            body,
            ("selected", "name", "price", "barcode", "old_category", "category", "status"),
            ("Select", "Item Name", "Price", "Barcode", "Old Category", "Category", "Status"),
        )
        self.category_tree.grid(row=1, column=0, sticky="nsew")
        category_tree = self._tree_widget(self.category_tree)
        category_tree.bind("<Button-1>", self._category_tree_click)
        category_tree.bind("<Double-1>", self._category_tree_double_click)
        category_tree.bind("<Delete>", self._category_tree_delete_key)
        category_tree.bind("<<TreeviewSelect>>", lambda _event: self._category_highlight_changed())

        actions = ttk.Frame(body)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Select all shown", command=self._select_all_category_rows).pack(side="left")
        ttk.Button(actions, text="Select highlighted", command=self._select_highlighted_category_rows).pack(side="left", padx=(8, 0))
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
        ttk.Button(tools, text="Merge selected...", command=self._open_merge_rows_dialog).pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="Undo", command=self._undo_edit_action).pack(side="left", padx=(6, 0))
        self.edit_tree = self._tree(
            left,
            ("selected", "name", "price", "barcode", "category", "reason"),
            ("Sel", "Item Name", "Price", "Barcode", "Category", "Reason"),
        )
        self.edit_tree.grid(row=1, column=0, sticky="nsew")
        edit_tree = self._tree_widget(self.edit_tree)
        edit_tree.bind("<<TreeviewSelect>>", lambda _event: self._edit_highlight_changed())
        edit_tree.bind("<Double-1>", self._edit_tree_double_click)

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
        left.rowconfigure(1, weight=1)
        split.add(left, weight=2)
        filters = ttk.Frame(left)
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(filters, text="Reason filter").pack(side="left")
        self.pos_reason_combo = ttk.Combobox(
            filters,
            textvariable=self.pos_reason_filter,
            values=("Any", "Needs review"),
            state="readonly",
            width=24,
        )
        self.pos_reason_combo.pack(side="left", padx=(6, 0))
        self.pos_reason_combo.bind("<<ComboboxSelected>>", lambda _event: self._populate_pos_rows())
        self.pos_tree = self._tree(
            left,
            ("name", "pos", "status", "reason"),
            ("Item Name", "BaseProductPosName", "Status", "Reason"),
        )
        self.pos_tree.grid(row=1, column=0, sticky="nsew")
        pos_tree = self._tree_widget(self.pos_tree)
        pos_tree.bind("<<TreeviewSelect>>", lambda _event: self._load_selected_pos_row())
        pos_tree.bind("<Double-1>", self._pos_tree_double_click)

        editor = ttk.LabelFrame(split, text="POS-name steering", padding=12)
        editor.columnconfigure(0, weight=1)
        split.add(editor, weight=1)
        self.pos_entry = ttk.Entry(editor, textvariable=self.pos_name)
        self.pos_entry.grid(row=0, column=0, sticky="ew")
        self.pos_entry.bind("<Return>", self._pos_entry_return)
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
        self.final_save_profile_button = ttk.Button(
            bottom,
            text="Save venue profile...",
            command=self._save_profile,
        )
        self.final_save_profile_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.export_button = ttk.Button(bottom, text="Confirm and export", command=self._start_export)
        self.export_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

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
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14, selectmode="extended")
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

    def _choose_venue_profile(self) -> None:
        selected = filedialog.askopenfilename(
            title="Load venue profile",
            filetypes=[("JSON files", "*.json")],
        )
        if not selected:
            return
        try:
            self.venue_profile = load_venue_profile(Path(selected))
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))
            return
        self.venue_profile_text.set(selected)
        self._render()

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
        venue_profile = self.venue_profile

        def parse_with_profile() -> ImportSession:
            session = parse_sources(inputs)
            if venue_profile is None:
                return session
            return apply_venue_profile(session, venue_profile)

        self._run_worker("parsed", parse_with_profile)
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
            self._set_category_session(next_session)
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
        row_id = tree.identify_row(event.y)
        if row_id and tree.identify_column(event.x) == "#6":
            tree.selection_set(row_id)
            self._show_inline_category_dropdown(row_id, focus=True, open_menu=True)
            return "break"
        row_id = tree.identify_row(event.y) or self._selected_iid(tree)
        if row_id:
            tree.selection_set(row_id)
            self._toggle_category_row(row_id)
            return "break"
        return None

    def _category_tree_delete_key(self, _event: tk.Event) -> str:
        self._delete_category_rows()
        return "break"

    def _category_highlight_changed(self) -> None:
        tree = self._tree_widget(self.category_tree)
        highlighted = tree.selection()
        self._close_inline_category_dropdown()
        if len(highlighted) == 1:
            self._show_inline_category_dropdown(str(highlighted[0]))

    def _show_inline_category_dropdown(
        self, row_id: str, *, focus: bool = False, open_menu: bool = False
    ) -> None:
        session = self.controller.state.session
        if session is None or not session.category_names:
            return
        self._close_inline_category_dropdown()
        tree = self._tree_widget(self.category_tree)
        bbox = tree.bbox(row_id, "#6")
        if not bbox:
            return
        cell_x, cell_y, width, height = bbox
        value = tk.StringVar(value=self._row(row_id).category if self._row(row_id) else "")
        combo = ttk.Combobox(
            tree,
            textvariable=value,
            values=session.category_names,
            state="readonly",
            width=max(14, width // 8),
        )
        combo.place(x=cell_x, y=cell_y, width=width, height=height)
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._apply_inline_category(row_id, value.get()),
        )
        combo.bind("<Escape>", lambda _event: self._close_inline_category_dropdown())
        combo.bind("<FocusOut>", lambda _event: self._close_inline_category_dropdown())
        self.inline_category_combo = combo
        if focus or open_menu:
            combo.focus_set()
        if open_menu:
            combo.after(50, lambda: combo.event_generate("<Down>"))

    def _apply_inline_category(self, row_id: str, category: str) -> None:
        session = self.controller.state.session
        if session is None:
            return
        next_session = assign_category(session, {row_id}, category)
        if next_session != session:
            self._push_category_undo()
            self._set_category_session(next_session)
        self._close_inline_category_dropdown()
        self._render()

    def _close_inline_category_dropdown(self) -> None:
        if self.inline_category_combo is not None:
            self.inline_category_combo.destroy()
            self.inline_category_combo = None

    def _select_all_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection.update(tree.get_children(""))
        self._populate_category_rows()

    def _select_highlighted_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection.update(str(row_id) for row_id in tree.selection())
        self._populate_category_rows()

    def _deselect_all_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection.difference_update(tree.get_children(""))
        self._populate_category_rows()

    def _category_action_row_ids(self) -> tuple[set[str], bool]:
        if self.category_selection:
            return set(self.category_selection), False
        tree = self._tree_widget(self.category_tree)
        return {str(row_id) for row_id in tree.selection()}, True

    def _assign_category(self) -> None:
        session = self.controller.state.session
        row_ids, _using_highlighted = self._category_action_row_ids()
        if session is None or not row_ids:
            return
        category = self.selected_category.get() or self.category_name.get()
        next_session = assign_category(session, row_ids, category)
        if next_session != session:
            self._push_category_undo()
            self._set_category_session(next_session)
            self.category_selection.clear()
            self._render()

    def _mark_category_for_edit(self) -> None:
        session = self.controller.state.session
        row_ids, _using_highlighted = self._category_action_row_ids()
        if session is None or not row_ids:
            return
        next_session = mark_for_edit(session, row_ids)
        if next_session != session:
            self._push_category_undo()
            self._set_category_session(next_session)
            self.category_selection.clear()
            self._render()

    def _delete_category_rows(self) -> None:
        session = self.controller.state.session
        row_ids, using_highlighted = self._category_action_row_ids()
        if session is None or not row_ids:
            return
        if using_highlighted and row_ids:
            count = len(row_ids)
            if not messagebox.askyesno(
                APP_TITLE,
                f"Delete {count} highlighted row{'s' if count != 1 else ''} from this import?",
            ):
                return
        next_session = delete_rows(session, row_ids)
        if next_session != session:
            self._push_category_undo()
            self._set_category_session(next_session)
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
        self._set_category_session(self.category_undo_stack.pop())
        self.category_selection.clear()
        self._render()

    def _set_category_session(self, session: ImportSession) -> None:
        self.controller.set_session(
            session,
            phase=AppPhase.CATEGORIZING,
            message="Category changes made. Continue through edit review and POS names before final review.",
        )

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
        self.edit_undo_stack.clear()
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

    def _edit_highlight_changed(self) -> None:
        tree = self._tree_widget(self.edit_tree)
        highlighted = tree.selection()
        if len(highlighted) == 1:
            self._load_edit_row(str(highlighted[0]))

    def _edit_tree_double_click(self, event: tk.Event) -> str | None:
        tree = self._tree_widget(self.edit_tree)
        row_id = tree.identify_row(event.y)
        if not row_id:
            return None
        tree.selection_set(row_id)
        tree.focus(row_id)
        self._load_edit_row(row_id)
        return "break"

    def _delete_edit_rows(self) -> None:
        session = self.controller.state.session
        if session is None or not self.edit_selection:
            return
        next_session = delete_rows(session, set(self.edit_selection), "edit review deletion")
        if next_session == session:
            return
        self._push_edit_undo()
        self._set_edit_session(next_session)
        self.edit_selection.clear()
        self._load_next_edit_row()
        self._render()

    def _delete_current_edit_row(self) -> None:
        if self.current_edit_row_id:
            self.edit_selection = {self.current_edit_row_id}
            self._delete_edit_rows()

    def _selected_edit_action_row_ids(self) -> set[str]:
        if self.edit_selection:
            return set(self.edit_selection)
        tree = self._tree_widget(self.edit_tree)
        return {str(row_id) for row_id in tree.selection()}

    def _open_merge_rows_dialog(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        row_ids = self._selected_edit_action_row_ids()
        if len(row_ids) < 2:
            messagebox.showwarning(APP_TITLE, "Select at least two rows to merge.")
            return
        rows = [row for row in session.rows if row.row_id in row_ids and row.status != "deleted"]
        if len(rows) < 2:
            messagebox.showwarning(APP_TITLE, "Select at least two active rows to merge.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Merge edit-review rows")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        target_by_label = {self._merge_row_label(row): row.row_id for row in rows}
        target_label = tk.StringVar(value=next(iter(target_by_label)))

        header = ttk.Frame(dialog, padding=12)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Merge into").grid(row=0, column=0, sticky="w")
        target_combo = ttk.Combobox(
            header,
            textvariable=target_label,
            values=tuple(target_by_label),
            state="readonly",
            width=56,
        )
        target_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        body = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text="Merge preview").grid(row=0, column=0, sticky="w")
        preview_frame = self._tree(
            body,
            columns=("role", "row_id", "item_name", "price", "barcode", "category", "action"),
            labels=("Role", "Row", "Name", "Price", "Barcode", "Category", "Merge Action"),
        )
        preview_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        preview_tree = self._tree_widget(preview_frame)
        preview_tree.configure(height=10, selectmode="browse")
        preview_tree.column("role", width=110, minwidth=90)
        preview_tree.column("row_id", width=90, minwidth=70)
        preview_tree.column("item_name", width=220, minwidth=140)
        preview_tree.column("price", width=80, minwidth=70, anchor="e")
        preview_tree.column("barcode", width=210, minwidth=130)
        preview_tree.column("category", width=140, minwidth=100)
        preview_tree.column("action", width=230, minwidth=160)

        actions = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)

        def refresh_preview(*_args) -> None:
            target_id = target_by_label[target_label.get()]
            self._clear(preview_tree)
            for index, values in enumerate(self._merge_preview_rows(rows, target_id)):
                preview_tree.insert("", "end", iid=f"preview-{index}", values=values)

        def confirm() -> None:
            target_id = target_by_label[target_label.get()]
            source_ids = {row.row_id for row in rows if row.row_id != target_id}
            try:
                next_session = merge_rows(session, target_id, source_ids)
            except Exception as error:
                messagebox.showerror(APP_TITLE, friendly_error(error), parent=dialog)
                return
            self._push_edit_undo()
            self._set_edit_session(next_session)
            self.edit_selection.clear()
            self.current_edit_row_id = target_id
            dialog.destroy()
            if self._row(target_id) is not None:
                self._load_edit_row(target_id)
            else:
                self._load_next_edit_row()
            self._render()

        ttk.Button(actions, text="Confirm merge", command=confirm).grid(row=0, column=1, sticky="e")
        ttk.Button(actions, text="Cancel", command=dialog.destroy).grid(row=0, column=2, sticky="e", padx=(8, 0))
        target_combo.bind("<<ComboboxSelected>>", refresh_preview)
        refresh_preview()
        size_and_center(dialog, 980, 480)
        target_combo.focus_set()

    @staticmethod
    def _merge_row_label(row) -> str:
        return f"{row.row_id} - {row.item_name or '(missing name)'}"

    @staticmethod
    def _merge_preview_rows(rows, target_row_id: str) -> tuple[tuple[str, str, str, str, str, str, str], ...]:
        target = next(row for row in rows if row.row_id == target_row_id)
        sources = [row for row in rows if row.row_id != target_row_id]
        source_barcodes = [barcode for row in sources for barcode in parse_barcodes(row.barcode)]
        merged_barcode = format_barcodes((*parse_barcodes(target.barcode), *source_barcodes))
        preview_rows = [
            (
                "Target",
                target.row_id,
                target.item_name or "(missing)",
                target.price or "(missing)",
                target.barcode or "(none)",
                target.category or "(missing)",
                "Keep row; update barcode field",
            )
        ]
        preview_rows.extend(
            (
                "Source",
                row.row_id,
                row.item_name or "(missing)",
                row.price or "(missing)",
                row.barcode or "(none)",
                row.category or "(missing)",
                f"Transfer barcode; delete into {target_row_id}",
            )
            for row in sources
        )
        preview_rows.append(
            (
                "Result",
                target.row_id,
                target.item_name or "(missing)",
                target.price or "(missing)",
                merged_barcode or "(none)",
                target.category or "(missing)",
                "Final target row after merge",
            )
        )
        return tuple(preview_rows)

    def _save_edit(self) -> None:
        session = self.controller.state.session
        if session is None or self.current_edit_row_id is None:
            return
        if not self._edit_form_changed():
            self._update_edit_action_state()
            return
        next_session = self._preview_edit_save(session)
        saved_row = self._row_from_session(next_session, self.current_edit_row_id)
        if saved_row is None:
            return
        if saved_row.status != "edit_complete":
            messagebox.showwarning(
                APP_TITLE,
                f"Row still needs review: {saved_row.review_reason or 'invalid edit values'}",
            )
            return
        if next_session == session:
            return
        self._push_edit_undo()
        self._set_edit_session(next_session)
        self._load_next_edit_row()
        self._render()

    def _push_edit_undo(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        self.edit_undo_stack.append(session)

    def _undo_edit_action(self) -> None:
        if not self.edit_undo_stack:
            return
        previous_row_id = self.current_edit_row_id
        self._set_edit_session(self.edit_undo_stack.pop())
        self.edit_selection.clear()
        if previous_row_id and self._row(previous_row_id) is not None:
            self._load_edit_row(previous_row_id)
        else:
            self._load_next_edit_row()
        self._render()

    def _set_edit_session(self, session: ImportSession) -> None:
        self.controller.set_session(
            session,
            phase=AppPhase.EDIT_REVIEW,
            message="Edit changes made. Continue through POS names before final review.",
        )

    def _edit_form_changed(self) -> bool:
        if self.current_edit_row_id is None:
            return False
        row = self._row(self.current_edit_row_id)
        if row is None:
            return False
        return (
            self._clean_edit_text(self.edit_name.get()) != row.item_name
            or self._clean_edit_text(self.edit_price.get()) != row.price
            or self._clean_edit_barcode(self.edit_barcode.get()) != row.barcode
            or self._clean_edit_text(self.edit_category.get()) != row.category
        )

    def _preview_edit_save(self, session: ImportSession) -> ImportSession:
        if self.current_edit_row_id is None:
            return session
        return save_edit(
            session,
            self.current_edit_row_id,
            item_name=self.edit_name.get(),
            price=self.edit_price.get(),
            barcode=self.edit_barcode.get(),
            category=self.edit_category.get(),
        )

    @staticmethod
    def _row_from_session(session: ImportSession, row_id: str):
        return next((row for row in session.rows if row.row_id == row_id), None)

    def _update_edit_action_state(self) -> None:
        if not hasattr(self, "save_edit_button"):
            return
        session = self.controller.state.session
        state = "disabled"
        if session is not None and self.current_edit_row_id is not None:
            if self._edit_form_changed():
                state = "normal"
        self.save_edit_button.configure(state=state)

    @staticmethod
    def _clean_edit_text(value: str) -> str:
        return " ".join(str(value or "").split())

    @staticmethod
    def _clean_edit_barcode(value: str) -> str:
        return "".join(str(value or "").split())

    def _go_to_pos(self) -> None:
        session = self.controller.state.session
        if session is None:
            return
        self.controller.set_session(
            run_pos_generation(session),
            phase=AppPhase.POS_REVIEW,
            message="Review and approve BaseProductPosName values.",
        )
        self.controller.go_to_pos_review()
        self._load_first_pos_row()
        self._render()

    def _load_selected_pos_row(self) -> None:
        if self._suppress_pos_selection_event:
            return
        row_id = self._selected_iid(self._tree_widget(self.pos_tree))
        if row_id:
            self._load_pos_row(row_id)

    def _pos_tree_double_click(self, event: tk.Event) -> str | None:
        tree = self._tree_widget(self.pos_tree)
        row_id = tree.identify_row(event.y)
        if not row_id:
            return None
        self._select_pos_tree_row(row_id)
        self._load_pos_row(row_id)
        return "break"

    def _load_first_pos_row(self) -> None:
        session = self.controller.state.session
        if session is None:
            self.current_pos_row_id = None
            self.pos_name.set("")
            self.pos_validation.set("")
            return
        row = next((row for row in session.active_rows if row.status == "pos_needs_review"), None)
        if row is None:
            row = next(iter(session.active_rows), None)
        if row is None:
            self.current_pos_row_id = None
            self.pos_name.set("")
            self.pos_validation.set("")
            return
        self._load_pos_row(row.row_id)

    def _load_pos_row(self, row_id: str, *, focus_entry: bool = True) -> None:
        self.current_pos_row_id = row_id
        row = self._row(row_id)
        self.pos_name.set(row.pos_name if row else "")
        self._refresh_suggestions()
        self._update_pos_action_state()
        if focus_entry:
            self._focus_pos_entry(select_all=True)

    def _replace_pos(self, *, advance: bool = False) -> None:
        session = self.controller.state.session
        if session is None or self.current_pos_row_id is None:
            return
        errors = self._pos_input_errors()
        if errors:
            self.pos_validation.set("; ".join(errors))
            self._update_pos_action_state()
            return
        current_row_id = self.current_pos_row_id
        displayed_before = self._displayed_pos_row_ids()
        self.controller.set_session(
            replace_pos_name(session, self.current_pos_row_id, self.pos_name.get()),
            phase=AppPhase.POS_REVIEW,
            message="Review and approve BaseProductPosName values.",
        )
        self._render()
        if advance:
            self._load_next_displayed_pos_row(current_row_id, displayed_before)
        else:
            self._refresh_suggestions()
            self._focus_pos_entry(select_all=True)

    def _pos_entry_return(self, _event: tk.Event) -> str:
        if str(self.replace_pos_button.cget("state")) != "disabled":
            self._replace_pos(advance=True)
        return "break"

    def _focus_pos_entry(self, *, select_all: bool = False) -> None:
        def focus() -> None:
            if not self.pos_entry.winfo_exists():
                return
            self.pos_entry.focus_set()
            if select_all:
                self.pos_entry.selection_range(0, tk.END)
                self.pos_entry.icursor(tk.END)

        self.pos_entry.after_idle(focus)

    def _select_pos_tree_row(self, row_id: str) -> None:
        tree = self._tree_widget(self.pos_tree)
        self._suppress_pos_selection_event = True
        try:
            current_selection = tree.selection()
            if current_selection:
                tree.selection_remove(current_selection)
            tree.selection_set(row_id)
            tree.focus(row_id)
            tree.see(row_id)
        finally:
            self._suppress_pos_selection_event = False

    def _displayed_pos_row_ids(self) -> list[str]:
        tree = self._tree_widget(self.pos_tree)
        return [str(row_id) for row_id in tree.get_children("")]

    def _load_next_displayed_pos_row(
        self,
        previous_row_id: str,
        previous_displayed_row_ids: list[str],
    ) -> None:
        displayed = self._displayed_pos_row_ids()
        if not displayed:
            self.current_pos_row_id = None
            self.pos_name.set("")
            self.pos_validation.set("")
            self._refresh_suggestions()
            return
        if previous_row_id in displayed:
            start_index = displayed.index(previous_row_id) + 1
            next_row_id = displayed[start_index] if start_index < len(displayed) else displayed[-1]
        else:
            old_index = (
                previous_displayed_row_ids.index(previous_row_id)
                if previous_row_id in previous_displayed_row_ids
                else -1
            )
            next_row_id = next(
                (
                    row_id
                    for row_id in previous_displayed_row_ids[old_index + 1 :]
                    if row_id in displayed
                ),
                displayed[min(max(old_index, 0), len(displayed) - 1)],
            )
        self._select_pos_tree_row(next_row_id)
        self._load_pos_row(next_row_id)

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
        self._update_edit_action_state()
        self.to_final_button.configure(state="normal" if state.can_leave_pos_review else "disabled")
        self.export_button.configure(state="normal" if state.can_export else "disabled")
        self._update_pos_action_state()
        self._sync_notebook_tab_states()
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

    def _sync_notebook_tab_states(self) -> None:
        unlocked = self._unlocked_tab_keys()
        for key, frame in self.tabs.items():
            self.notebook.tab(frame, state="normal" if key in unlocked else "disabled")

    def _unlocked_tab_keys(self) -> set[str]:
        state = self.controller.state
        unlocked = {"parse"}
        phase_order = {
            AppPhase.CATEGORIZING: ("categories",),
            AppPhase.EDIT_REVIEW: ("categories", "edit"),
            AppPhase.POS_REVIEW: ("categories", "edit", "pos"),
            AppPhase.FINAL_REVIEW: ("categories", "edit", "pos", "final"),
            AppPhase.EXPORTING: ("categories", "edit", "pos", "final"),
            AppPhase.COMPLETE: ("categories", "edit", "pos", "final", "complete"),
        }
        unlocked.update(phase_order.get(state.phase, ()))
        if state.result is not None:
            unlocked.add("complete")
        return unlocked

    def _populate_category_rows(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.category_tree)
        self._clear(tree)
        if session is None:
            return
        rows = filter_rows(
            session,
            keyword=self.category_filter.get(),
            old_category=self.old_category_filter.get(),
            barcode_filter=self._selected_barcode_filter(),
            category_assignment=self._selected_category_assignment_filter(),
            price_operator=self.price_operator.get(),  # type: ignore[arg-type]
            price_value=self.min_price.get(),
            price_upper=self.max_price.get(),
        )
        self.old_category_combo.configure(values=self._old_category_values(session))
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
                    row.old_category,
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
        shown_row_ids = []
        for row in rows:
            shown_row_ids.append(row.row_id)
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
        if self.current_edit_row_id in shown_row_ids:
            tree.selection_set(self.current_edit_row_id)
            tree.focus(self.current_edit_row_id)
            tree.see(self.current_edit_row_id)

    @staticmethod
    def _old_category_values(session) -> tuple[str, ...]:
        values = sorted({row.old_category for row in session.active_rows if row.old_category})
        if any(not row.old_category.strip() for row in session.active_rows):
            return ("", "No category", *values)
        return ("", *values)

    def _selected_barcode_filter(self) -> str:
        value = self.barcode_filter.get()
        return "" if value == "Any" else value

    def _selected_category_assignment_filter(self) -> str:
        value = self.category_assignment_filter.get()
        return "" if value == "Any" else value

    def _selected_pos_reason_filter(self) -> str:
        value = self.pos_reason_filter.get()
        return "" if value == "Any" else value

    @staticmethod
    def _pos_reason_filter_values(session: ImportSession) -> tuple[str, ...]:
        reasons = sorted(
            {row.review_reason for row in session.active_rows if row.review_reason},
            key=lambda value: value.casefold(),
        )
        return ("Any", "Needs review", *reasons)

    def _populate_pos_rows(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.pos_tree)
        self._clear(tree)
        if session is None:
            return
        self.pos_reason_combo.configure(values=self._pos_reason_filter_values(session))
        for row in filter_pos_rows(session, self._selected_pos_reason_filter()):
            tree.insert("", "end", iid=row.row_id, values=(row.item_name, row.pos_name, row.status, row.review_reason))
        if self.current_pos_row_id:
            row = self._row(self.current_pos_row_id)
            if row is not None and tree.exists(self.current_pos_row_id):
                self._select_pos_tree_row(self.current_pos_row_id)
        self._update_pos_action_state()

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
            self._update_edit_action_state()
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
        self._update_edit_action_state()

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
                command=lambda value=suggestion: self._use_pos_suggestion(value),
            ).pack(fill="x", pady=2)

    def _use_pos_suggestion(self, value: str) -> None:
        self.pos_name.set(value)
        self._update_pos_action_state()

    def _pos_input_errors(self) -> list[str]:
        session = self.controller.state.session
        if session is None or self.current_pos_row_id is None:
            return ["select a row"]
        return validate_pos_name(
            self._clean_edit_text(self.pos_name.get()),
            self.current_pos_row_id,
            session.rows,
        )

    def _update_pos_action_state(self) -> None:
        if not hasattr(self, "replace_pos_button"):
            return
        errors = self._pos_input_errors()
        self.pos_validation.set("; ".join(errors))
        self.replace_pos_button.configure(state="disabled" if errors else "normal")

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
