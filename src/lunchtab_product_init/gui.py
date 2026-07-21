from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from lunchtab_product_init.desktop import friendly_error, open_path
from lunchtab_product_init.gui_controller import (
    AppController,
    AppPhase,
    CategoryActionSelection,
    UndoEntry,
    deselect_shown_category_rows,
    final_review_audit_text,
    next_displayed_row_id,
    next_displayed_pos_row_id,
    select_category_action_rows,
    select_shown_category_rows,
    source_file_audits,
    toggle_category_row_selection,
    undo_button_text,
)
from lunchtab_product_init.pos_profile_inference import (
    PosProfileInferenceResult,
    infer_pos_profile_from_final_import,
)
from lunchtab_product_init.session_workflow import (
    ImportSession,
    VenueProfile,
    assign_category,
    apply_venue_profile,
    delete_rows,
    export_session,
    duplicate_name_edit_rows,
    filter_final_rows,
    filter_rows,
    filter_pos_rows,
    final_review_metadata,
    format_barcodes,
    load_venue_profile,
    mark_for_edit,
    merge_rows,
    next_edit_row,
    no_barcode_rows,
    parse_barcodes,
    parse_sources,
    prepare_edit_review,
    replace_pos_name,
    run_pos_generation,
    save_edit,
    save_final_review_edit,
    save_venue_profile,
    suggest_pos_names,
    validate_edit_name_for_row,
    validate_final_review_edit,
    validate_pos_name_for_row,
)
from lunchtab_product_init.ui_helpers import size_and_center
from lunchtab_product_init.workflow import write_generic_inventory_template

APP_TITLE = "Lunchtab Product Initialization"


class ProductInitializationApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.controller = AppController()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.category_selection: set[str] = set()
        self.category_undo_stack: list[UndoEntry] = []
        self.edit_undo_stack: list[UndoEntry] = []
        self.edit_selection: set[str] = set()
        self.edit_no_barcode_only = False
        self.edit_duplicate_name_only = False
        self.current_edit_row_id: str | None = None
        self.current_pos_row_id: str | None = None
        self._suppress_pos_selection_event = False
        self._category_filter_after_id: str | None = None
        self._tree_sort_state: dict[str, tuple[str, bool, tuple[str, ...]]] = {}

        root.title(APP_TITLE)
        size_and_center(root, 1120, 760)

        self.product_template_text = tk.StringVar()
        self.recipe_list_text = tk.StringVar()
        self.odin_inventory_text = tk.StringVar()
        self.generic_inventory_text = tk.StringVar()
        self.venue_profile_text = tk.StringVar()
        self.output_text = tk.StringVar(value=str(self.controller.state.output_root))
        self.status_text = tk.StringVar(value=self.controller.state.message)
        self.is_published = tk.BooleanVar(value=False)
        self.is_orderable = tk.BooleanVar(value=False)
        self.category_name = tk.StringVar()
        self.category_filter = tk.StringVar()
        self.name_filter = tk.StringVar(value="Any")
        self.old_category_filter = tk.StringVar()
        self.barcode_filter = tk.StringVar(value="Any")
        self.category_assignment_filter = tk.StringVar(value="Any")
        self.price_operator = tk.StringVar(value="=")
        self.min_price = tk.StringVar()
        self.max_price = tk.StringVar()
        self.stock_operator = tk.StringVar(value="Any")
        self.stock_value = tk.StringVar()
        self.stock_upper = tk.StringVar()
        self.selected_category = tk.StringVar()
        self.edit_name = tk.StringVar()
        self.edit_price = tk.StringVar()
        self.edit_barcode = tk.StringVar()
        self.edit_category = tk.StringVar()
        self.edit_validation = tk.StringVar()
        self.pos_name = tk.StringVar()
        self.pos_reason_filter = tk.StringVar(value="Any")
        self.pos_validation = tk.StringVar()
        self.final_filter = tk.StringVar()
        self.final_flag_filter = tk.StringVar(value="Any")
        self.audit_text = tk.StringVar()
        self.inline_category_combo: ttk.Combobox | None = None
        self.venue_profile: VenueProfile | None = None
        self.profile_inference_result: PosProfileInferenceResult | None = None
        self.profile_inference_running = False

        for variable in (self.edit_name, self.edit_price, self.edit_barcode, self.edit_category):
            variable.trace_add("write", lambda *_args: self._update_edit_action_state())
        self.pos_name.trace_add("write", lambda *_args: self._update_pos_action_state())
        self.final_filter.trace_add("write", lambda *_args: self._populate_final_rows())

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
        ttk.Label(header, textvariable=self.status_text).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )

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
        self._file_row(
            form, 0, "ProductData template", self.product_template_text, self._choose_template
        )
        self._file_row(form, 1, "Recipe list", self.recipe_list_text, self._choose_recipe)
        self._file_row(
            form, 2, "Odin inventory (optional)", self.odin_inventory_text, self._choose_odin
        )
        self._generic_inventory_row(form, 3)
        self._file_row(
            form, 4, "Venue profile", self.venue_profile_text, self._choose_venue_profile
        )
        self._file_row(form, 5, "Save results in", self.output_text, self._choose_output)
        ttk.Checkbutton(
            form,
            text="Set target CSV IsPublished to true",
            variable=self.is_published,
            command=self._set_import_flags,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Checkbutton(
            form,
            text="Set target CSV IsOrderable to true",
            variable=self.is_orderable,
            command=self._set_import_flags,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 0))
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
        self.category_undo_button = ttk.Button(
            tools, text="Undo", command=self._undo_category_action
        )
        self.category_undo_button.grid(row=0, column=3, padx=(10, 0))

        ttk.Label(tools, text="Keyword filter").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.category_filter_entry = ttk.Entry(tools, textvariable=self.category_filter, width=22)
        self.category_filter_entry.grid(row=1, column=1, padx=(6, 8), sticky="w", pady=(8, 0))
        self._bind_live_category_filter(self.category_filter_entry)
        ttk.Label(tools, text="Old category filter").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.old_category_combo = ttk.Combobox(
            tools,
            textvariable=self.old_category_filter,
            width=18,
        )
        self.old_category_combo.grid(row=1, column=3, padx=(6, 8), sticky="w", pady=(8, 0))
        self._bind_live_category_filter(self.old_category_combo)
        self.old_category_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_category_rows()
        )
        ttk.Label(tools, text="Price filter").grid(row=1, column=4, sticky="w", pady=(8, 0))
        self.price_operator_combo = ttk.Combobox(
            tools,
            textvariable=self.price_operator,
            values=("=", "<", ">", "<=", ">=", "range", "No price"),
            state="readonly",
            width=8,
        )
        self.price_operator_combo.grid(row=1, column=5, padx=(6, 4), sticky="w", pady=(8, 0))
        self.price_operator_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._price_operator_changed()
        )
        self.price_value_entry = ttk.Entry(tools, textvariable=self.min_price, width=10)
        self.price_value_entry.grid(row=1, column=6, padx=(0, 4), sticky="w", pady=(8, 0))
        self._bind_live_category_filter(self.price_value_entry)
        ttk.Label(tools, text="Upper bound").grid(row=1, column=7, sticky="w", pady=(8, 0))
        self.price_upper_entry = ttk.Entry(tools, textvariable=self.max_price, width=10)
        self.price_upper_entry.grid(row=1, column=8, padx=(6, 8), sticky="w", pady=(8, 0))
        self._bind_live_category_filter(self.price_upper_entry)
        ttk.Label(tools, text="Barcode filter").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.barcode_filter_combo = ttk.Combobox(
            tools,
            textvariable=self.barcode_filter,
            values=("Any", "No barcode", "SAGEMB", "Vendor"),
            state="readonly",
            width=12,
        )
        self.barcode_filter_combo.grid(row=2, column=1, padx=(6, 8), sticky="w", pady=(8, 0))
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
        ttk.Label(tools, text="Name filter").grid(row=2, column=4, sticky="w", pady=(8, 0))
        self.name_filter_combo = ttk.Combobox(
            tools,
            textvariable=self.name_filter,
            values=("Any", "Duplicate name"),
            state="readonly",
            width=16,
        )
        self.name_filter_combo.grid(row=2, column=5, padx=(6, 8), sticky="w", pady=(8, 0))
        self.name_filter_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_category_rows()
        )
        ttk.Label(tools, text="Inventory stock filter").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        self.stock_operator_combo = ttk.Combobox(
            tools,
            textvariable=self.stock_operator,
            values=("Any", "No stock", "0", "<", "<=", ">=", "range"),
            state="readonly",
            width=12,
        )
        self.stock_operator_combo.grid(row=3, column=1, padx=(6, 8), sticky="w", pady=(8, 0))
        self.stock_operator_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._stock_operator_changed()
        )
        ttk.Label(tools, text="Stock value").grid(row=3, column=2, sticky="w", pady=(8, 0))
        self.stock_value_entry = ttk.Entry(tools, textvariable=self.stock_value, width=10)
        self.stock_value_entry.grid(row=3, column=3, padx=(6, 8), sticky="w", pady=(8, 0))
        self._bind_live_category_filter(self.stock_value_entry)
        ttk.Label(tools, text="Upper stock").grid(row=3, column=4, sticky="w", pady=(8, 0))
        self.stock_upper_entry = ttk.Entry(tools, textvariable=self.stock_upper, width=10)
        self.stock_upper_entry.grid(row=3, column=5, padx=(6, 8), sticky="w", pady=(8, 0))
        self._bind_live_category_filter(self.stock_upper_entry)
        ttk.Button(tools, text="Clear filters", command=self._clear_category_filters).grid(
            row=2, column=6, sticky="w", pady=(8, 0)
        )

        self.category_tree = self._tree(
            body,
            ("selected", "name", "price", "barcode", "old_category", "category", "status"),
            ("Select", "Item Name", "Price", "Barcode", "Old Category", "Category", "Status"),
        )
        self._enable_tree_sort(self.category_tree, numeric_columns=("price",))
        self.category_tree.grid(row=1, column=0, sticky="nsew")
        category_tree = self._tree_widget(self.category_tree)
        category_tree.bind("<Button-1>", self._category_tree_click)
        category_tree.bind("<Double-1>", self._category_tree_double_click)
        category_tree.bind("<Delete>", self._category_tree_delete_key)
        category_tree.bind("<<TreeviewSelect>>", lambda _event: self._category_highlight_changed())

        actions = ttk.Frame(body)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        row_actions = ttk.Frame(actions)
        row_actions.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.select_all_category_button = ttk.Button(
            row_actions,
            text="Select all shown",
            command=self._select_all_category_rows,
        )
        self.select_all_category_button.pack(side="left")
        self.select_highlighted_category_button = ttk.Button(
            row_actions,
            text="Select highlighted",
            command=self._select_highlighted_category_rows,
        )
        self.select_highlighted_category_button.pack(side="left", padx=(8, 0))
        self.deselect_all_category_button = ttk.Button(
            row_actions,
            text="Deselect all shown",
            command=self._deselect_all_category_rows,
        )
        self.deselect_all_category_button.pack(side="left", padx=(8, 0))
        self.category_combo = ttk.Combobox(
            row_actions, textvariable=self.selected_category, state="readonly", width=24
        )
        self.category_combo.pack(side="left", padx=8)
        self.assign_category_button = ttk.Button(
            row_actions, text="Assign category", command=self._assign_category
        )
        self.assign_category_button.pack(side="left")
        self.mark_category_button = ttk.Button(
            row_actions, text="Mark for edit", command=self._mark_category_for_edit
        )
        self.mark_category_button.pack(side="left", padx=8)
        self.delete_category_button = ttk.Button(
            row_actions, text="Delete rows", command=self._delete_category_rows
        )
        self.delete_category_button.pack(side="left")
        workflow_actions = ttk.Frame(actions)
        workflow_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        workflow_actions.columnconfigure(0, weight=1)
        self.save_profile_button = ttk.Button(
            workflow_actions, text="Save venue profile...", command=self._save_profile
        )
        self.save_profile_button.grid(row=0, column=1, sticky="e")
        self.to_edit_button = ttk.Button(
            workflow_actions, text="Next: Edit review", command=self._go_to_edit
        )
        self.to_edit_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self._price_operator_changed()
        self._stock_operator_changed()

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
        ttk.Button(tools, text="Duplicate names", command=self._show_duplicate_name_edit_rows).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(tools, text="All review rows", command=self._show_all_edit_rows).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(tools, text="Select all shown", command=self._select_all_edit_rows).pack(
            side="left", padx=6
        )
        ttk.Button(tools, text="Toggle selected row", command=self._toggle_edit_selection).pack(
            side="left"
        )
        ttk.Button(tools, text="Delete selected", command=self._delete_edit_rows).pack(side="left")
        ttk.Button(tools, text="Merge selected...", command=self._open_merge_rows_dialog).pack(
            side="left", padx=(6, 0)
        )
        self.edit_undo_button = ttk.Button(tools, text="Undo", command=self._undo_edit_action)
        self.edit_undo_button.pack(side="left", padx=(6, 0))
        self.edit_tree = self._tree(
            left,
            ("selected", "name", "price", "barcode", "category", "reason"),
            ("Sel", "Item Name", "Price", "Barcode", "Category", "Reason"),
        )
        self._enable_tree_sort(self.edit_tree, numeric_columns=("price",))
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
            )
        ):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(form, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            entry.bind("<Return>", self._edit_entry_return)
            if row == 0:
                self.edit_name_entry = entry
            elif row == 1:
                self.edit_price_entry = entry
            else:
                self.edit_barcode_entry = entry
        ttk.Label(form, text="Category").grid(row=3, column=0, sticky="w", pady=4)
        self.edit_category_combo = ttk.Combobox(
            form,
            textvariable=self.edit_category,
            values=(),
        )
        self.edit_category_combo.grid(row=3, column=1, sticky="ew", pady=4)
        self.edit_category_combo.bind("<Return>", self._edit_entry_return)
        ttk.Label(form, textvariable=self.edit_validation, foreground="#a33").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        self.save_edit_button = ttk.Button(form, text="Save row edit", command=self._save_edit)
        self.save_edit_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(form, text="Delete current row", command=self._delete_current_edit_row).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        self.to_pos_button = ttk.Button(form, text="Next: POS names", command=self._go_to_pos)
        self.to_pos_button.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(16, 0))

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
        self._enable_tree_sort(self.pos_tree)
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
        self.replace_pos_button = ttk.Button(
            editor,
            text="Replace",
            command=lambda: self._replace_pos(advance=True),
        )
        self.replace_pos_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(editor, text="Suggestions").grid(row=3, column=0, sticky="w", pady=(14, 4))
        self.suggestion_frame = ttk.Frame(editor)
        self.suggestion_frame.grid(row=4, column=0, sticky="ew")
        self.to_final_button = ttk.Button(
            editor, text="Next: Final review", command=self._go_to_final
        )
        self.to_final_button.grid(row=5, column=0, sticky="ew", pady=(20, 0))

    def _build_final_tab(self) -> None:
        parent = self.tabs["final"]
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        filters = ttk.Frame(parent)
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="Find").grid(row=0, column=0, sticky="w")
        self.final_filter_entry = ttk.Entry(filters, textvariable=self.final_filter)
        self.final_filter_entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        self.final_filter_entry.bind(
            "<Return>", lambda _event: (self._populate_final_rows(), "break")[1]
        )
        ttk.Label(filters, text="Show").grid(row=0, column=2, sticky="w")
        self.final_flag_combo = ttk.Combobox(
            filters,
            textvariable=self.final_flag_filter,
            values=self._final_flag_filter_values(),
            state="readonly",
            width=18,
        )
        self.final_flag_combo.grid(row=0, column=3, sticky="w", padx=(6, 0))
        self.final_flag_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._populate_final_rows()
        )
        self.final_tree = self._tree(
            parent,
            ("name", "pos", "price", "barcode", "category", "published", "orderable", "core"),
            (
                "BaseProductName",
                "BaseProductPosName",
                "Price",
                "Barcode",
                "ProductCategories",
                "IsPublished",
                "IsOrderable",
                "Core Catalogue",
            ),
        )
        self._enable_tree_sort(self.final_tree, numeric_columns=("price",))
        self.final_tree.grid(row=1, column=0, sticky="nsew")
        bottom = ttk.Frame(parent)
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        self.final_audit_label = ttk.Label(bottom, textvariable=self.audit_text, justify="left")
        self.final_audit_label.grid(row=0, column=0, sticky="ew")
        bottom.bind("<Configure>", self._final_bottom_configured)
        final_actions = ttk.Frame(bottom)
        final_actions.grid(row=1, column=0, sticky="e", pady=(8, 0))
        self.final_save_profile_button = ttk.Button(
            final_actions,
            text="Save venue profile...",
            command=self._save_profile,
        )
        self.final_save_profile_button.grid(row=0, column=0, sticky="e", padx=(8, 0))
        self.edit_final_row_button = ttk.Button(
            final_actions,
            text="Edit selected row...",
            command=self._open_final_row_edit_dialog,
        )
        self.edit_final_row_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.export_button = ttk.Button(
            final_actions, text="Confirm and export", command=self._start_export
        )
        self.export_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _build_complete_tab(self) -> None:
        parent = self.tabs["complete"]
        panel = ttk.LabelFrame(parent, text="Export destinations", padding=14)
        panel.grid(row=0, column=0, sticky="new")
        panel.columnconfigure(0, weight=1)
        self.open_buttons = {
            "folder": ttk.Button(
                panel, text="Open results folder", command=lambda: self._open_result("folder")
            ),
            "final": ttk.Button(
                panel, text="Open import CSV", command=lambda: self._open_result("final")
            ),
            "core": ttk.Button(
                panel, text="Open Core Catalogue", command=lambda: self._open_result("core")
            ),
            "category": ttk.Button(
                panel, text="Open category audit", command=lambda: self._open_result("category")
            ),
            "naming": ttk.Button(
                panel, text="Open POS-name audit", command=lambda: self._open_result("naming")
            ),
            "deleted": ttk.Button(
                panel, text="Open deleted-row audit", command=lambda: self._open_result("deleted")
            ),
            "summary": ttk.Button(
                panel, text="Open run summary", command=lambda: self._open_result("summary")
            ),
        }
        for index, button in enumerate(self.open_buttons.values()):
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=6, pady=5)
            panel.columnconfigure(index % 2, weight=1)
        profile_panel = ttk.LabelFrame(parent, text="Venue profile proposal", padding=14)
        profile_panel.grid(row=1, column=0, sticky="new", pady=(12, 0))
        profile_panel.columnconfigure(0, weight=1)
        profile_panel.columnconfigure(1, weight=1)
        self.infer_profile_button = ttk.Button(
            profile_panel,
            text="Create POS profile proposal",
            command=self._start_profile_inference_from_export,
        )
        self.infer_profile_button.grid(row=0, column=0, sticky="ew", padx=6, pady=5)
        self.open_profile_proposal_button = ttk.Button(
            profile_panel,
            text="Open proposed profile",
            command=lambda: self._open_profile_inference_result("profile"),
        )
        self.open_profile_proposal_button.grid(row=0, column=1, sticky="ew", padx=6, pady=5)
        self.open_profile_inference_audit_button = ttk.Button(
            profile_panel,
            text="Open inference audit",
            command=lambda: self._open_profile_inference_result("audit"),
        )
        self.open_profile_inference_audit_button.grid(row=1, column=0, sticky="ew", padx=6, pady=5)
        self.open_profile_inference_folder_button = ttk.Button(
            profile_panel,
            text="Open proposal folder",
            command=lambda: self._open_profile_inference_result("folder"),
        )
        self.open_profile_inference_folder_button.grid(row=1, column=1, sticky="ew", padx=6, pady=5)

    @staticmethod
    def _file_row(
        parent, row: int, label: str, variable: tk.StringVar, command: Callable[[], None]
    ) -> None:
        ttk.Label(parent, text=label, width=22).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, state="readonly").grid(
            row=row, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, pady=5)

    def _generic_inventory_row(self, parent, row: int) -> None:
        label_frame = ttk.Frame(parent)
        label_frame.grid(row=row, column=0, sticky="w", pady=5)
        ttk.Label(label_frame, text="Generic inventory (optional)", width=22).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            label_frame, text="Template", command=self._open_generic_inventory_template
        ).grid(
            row=0,
            column=1,
            padx=(6, 0),
        )
        ttk.Entry(parent, textvariable=self.generic_inventory_text, state="readonly").grid(
            row=row,
            column=1,
            sticky="ew",
            padx=8,
            pady=5,
        )
        ttk.Button(parent, text="Browse...", command=self._choose_generic_inventory).grid(
            row=row,
            column=2,
            pady=5,
        )

    def _final_bottom_configured(self, event: tk.Event) -> None:
        if hasattr(self, "final_audit_label"):
            self.final_audit_label.configure(wraplength=max(320, event.width - 12))

    @staticmethod
    def _tree(parent, columns: tuple[str, ...], labels: tuple[str, ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=14, selectmode="extended"
        )
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

    def _enable_tree_sort(self, frame: ttk.Frame, *, numeric_columns: tuple[str, ...] = ()) -> None:
        tree = self._tree_widget(frame)
        columns = tuple(str(column) for column in tree["columns"])
        self._tree_sort_state[str(tree)] = ("", True, numeric_columns)
        for column in columns:
            label = str(tree.heading(column, "text"))
            tree.heading(
                column,
                text=label,
                command=lambda selected_column=column: self._sort_tree_by_column(
                    tree, selected_column
                ),
            )

    def _sort_tree_by_column(self, tree: ttk.Treeview, column: str) -> None:
        previous_column, previous_ascending, numeric_columns = self._tree_sort_state.get(
            str(tree),
            ("", True, ()),
        )
        ascending = not previous_ascending if previous_column == column else True
        self._tree_sort_state[str(tree)] = (column, ascending, numeric_columns)
        self._apply_tree_sort(tree)

    def _apply_tree_sort(self, tree: ttk.Treeview) -> None:
        column, ascending, numeric_columns = self._tree_sort_state.get(str(tree), ("", True, ()))
        if not column:
            return
        ordered = sorted(
            enumerate(tree.get_children("")),
            key=lambda indexed_item: self._tree_sort_key(
                tree.set(indexed_item[1], column),
                numeric=column in numeric_columns,
                original_index=indexed_item[0],
            ),
            reverse=not ascending,
        )
        for position, (_original_index, item_id) in enumerate(ordered):
            tree.move(item_id, "", position)

    @staticmethod
    def _tree_sort_key(
        value: str, *, numeric: bool, original_index: int
    ) -> tuple[int, float | str, int]:
        cleaned = str(value).strip()
        if numeric:
            try:
                return (0, float(cleaned.replace("$", "").replace(",", "")), original_index)
            except ValueError:
                return (1, cleaned.casefold(), original_index)
        return (0, cleaned.casefold(), original_index)

    def _tree_widget(self, frame: ttk.Frame) -> ttk.Treeview:
        return next(child for child in frame.winfo_children() if isinstance(child, ttk.Treeview))

    def _choose_template(self) -> None:
        self._choose_file(
            "Select ProductData template",
            [("CSV files", "*.csv")],
            self.product_template_text,
            self.controller.select_product_template,
        )

    def _choose_recipe(self) -> None:
        self._choose_file(
            "Select recipe list",
            [("CSV files", "*.csv")],
            self.recipe_list_text,
            self.controller.select_recipe_list,
        )

    def _choose_odin(self) -> None:
        self._choose_file(
            "Select Odin inventory workbook",
            [("Excel workbooks", "*.xlsx")],
            self.odin_inventory_text,
            self.controller.select_odin_inventory,
            clear_variables=(self.generic_inventory_text,),
        )

    def _choose_generic_inventory(self) -> None:
        self._choose_file(
            "Select generic inventory list",
            [("CSV files", "*.csv")],
            self.generic_inventory_text,
            self.controller.select_generic_inventory,
            clear_variables=(self.odin_inventory_text,),
        )

    def _open_generic_inventory_template(self) -> None:
        path = self.controller.state.output_root / "generic-inventory-template.csv"
        try:
            write_generic_inventory_template(path)
            open_path(path)
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

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

    def _choose_file(
        self,
        title: str,
        filetypes,
        variable: tk.StringVar,
        setter,
        *,
        clear_variables: tuple[tk.StringVar, ...] = (),
    ) -> None:
        selected = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if selected:
            variable.set(selected)
            for clear_variable in clear_variables:
                clear_variable.set("")
            setter(Path(selected))
            self._render()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose the parent folder for timestamped results")
        if selected:
            self.output_text.set(selected)
            self.controller.select_output_root(Path(selected))
            self._render()

    def _set_import_flags(self) -> None:
        self.controller.set_import_flags(
            is_published=bool(self.is_published.get()),
            is_orderable=bool(self.is_orderable.get()),
        )
        self._render()

    def _start_parse(self) -> None:
        self.controller.begin_parse()
        self.profile_inference_result = None
        self.profile_inference_running = False
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
        self.profile_inference_result = None
        self.profile_inference_running = False
        inputs = self.controller.build_inputs()
        session = state.session
        if session is None:
            raise RuntimeError("Parse source files before exporting.")
        self._run_worker("exported", lambda: export_session(session, inputs))
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
                    self.category_undo_stack.clear()
                    self.edit_undo_stack.clear()
                elif name == "exported":
                    self.controller.export_succeeded(payload)  # type: ignore[arg-type]
                elif name == "profile_inferred":
                    self.profile_inference_running = False
                    self.profile_inference_result = payload  # type: ignore[assignment]
                    self.controller.set_message("POS profile proposal export complete.")
                    result = payload  # type: ignore[assignment]
                    messagebox.showinfo(
                        APP_TITLE,
                        f"POS profile proposal written to {result.run_dir}",
                    )
                else:
                    self.profile_inference_running = False
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
            self._push_category_undo("Add category")
            self._set_category_session(next_session)
        self.category_name.set("")
        self.category_entry.focus_set()
        self._render()

    def _refresh_category_rows(self) -> None:
        if self._category_filter_after_id is not None:
            self.root.after_cancel(self._category_filter_after_id)
            self._category_filter_after_id = None
        self._populate_category_rows()

    def _clear_category_filters(self) -> None:
        if self._category_filter_after_id is not None:
            self.root.after_cancel(self._category_filter_after_id)
            self._category_filter_after_id = None
        self.category_filter.set("")
        self.old_category_filter.set("")
        self.barcode_filter.set("Any")
        self.category_assignment_filter.set("Any")
        self.name_filter.set("Any")
        self.price_operator.set("=")
        self.min_price.set("")
        self.max_price.set("")
        self.stock_operator.set("Any")
        self.stock_value.set("")
        self.stock_upper.set("")
        self.price_value_entry.configure(state="normal")
        self.price_upper_entry.configure(state="disabled")
        self.stock_value_entry.configure(state="disabled")
        self.stock_upper_entry.configure(state="disabled")
        self._populate_category_rows()

    def _bind_live_category_filter(self, widget: tk.Widget) -> None:
        widget.bind("<KeyRelease>", self._category_filter_key_released)
        widget.bind("<Return>", lambda _event: (self._refresh_category_rows(), "break")[1])

    def _category_filter_key_released(self, event: tk.Event) -> None:
        if event.keysym in {
            "Return",
            "Escape",
            "Tab",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
        }:
            return
        widget = event.widget
        if self.root.focus_get() is not widget:
            return
        self._schedule_category_filter_refresh()

    def _schedule_category_filter_refresh(self) -> None:
        if self._category_filter_after_id is not None:
            self.root.after_cancel(self._category_filter_after_id)
        self._category_filter_after_id = self.root.after(500, self._run_category_filter_refresh)

    def _run_category_filter_refresh(self) -> None:
        self._category_filter_after_id = None
        self._populate_category_rows()

    def _toggle_category_selection(self) -> None:
        tree = self._tree_widget(self.category_tree)
        row_id = self._selected_iid(tree)
        if not row_id:
            return
        self._toggle_category_row(row_id)

    def _toggle_category_row(self, row_id: str) -> None:
        self.category_selection = set(
            toggle_category_row_selection(self.category_selection, row_id)
        )
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
            self._push_category_undo(f"Set category to {category}")
            self._set_category_session(next_session)
        self._close_inline_category_dropdown()
        self._render()

    def _close_inline_category_dropdown(self) -> None:
        if self.inline_category_combo is not None:
            self.inline_category_combo.destroy()
            self.inline_category_combo = None

    def _select_all_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection = set(
            select_shown_category_rows(self.category_selection, tree.get_children(""))
        )
        self._populate_category_rows()

    def _select_highlighted_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection = set(
            select_shown_category_rows(self.category_selection, tree.selection())
        )
        self._populate_category_rows()

    def _deselect_all_category_rows(self) -> None:
        tree = self._tree_widget(self.category_tree)
        self.category_selection = set(
            deselect_shown_category_rows(self.category_selection, tree.get_children(""))
        )
        self._populate_category_rows()

    def _category_action_selection(self) -> CategoryActionSelection:
        tree = self._tree_widget(self.category_tree)
        return select_category_action_rows(self.category_selection, tree.selection())

    def _assign_category(self) -> None:
        session = self.controller.state.session
        action = self._category_action_selection()
        if session is None or not action.row_ids:
            return
        category = self.selected_category.get() or self.category_name.get()
        next_session = assign_category(session, set(action.row_ids), category)
        if next_session != session:
            self._push_category_undo(
                f"Assign {len(action.row_ids)} row{'' if len(action.row_ids) == 1 else 's'}"
            )
            self._set_category_session(next_session)
            self.category_selection.clear()
            self._render()

    def _mark_category_for_edit(self) -> None:
        session = self.controller.state.session
        action = self._category_action_selection()
        if session is None or not action.row_ids:
            return
        next_session = mark_for_edit(session, set(action.row_ids))
        if next_session != session:
            self._push_category_undo(
                f"Mark {len(action.row_ids)} row{'' if len(action.row_ids) == 1 else 's'} for edit"
            )
            self._set_category_session(next_session)
            self.category_selection.clear()
            self._render()

    def _delete_category_rows(self) -> None:
        session = self.controller.state.session
        action = self._category_action_selection()
        if session is None or not action.row_ids:
            return
        if action.needs_delete_confirmation:
            count = len(action.row_ids)
            if not messagebox.askyesno(
                APP_TITLE,
                f"Delete {count} highlighted row{'s' if count != 1 else ''} from this import?",
            ):
                return
        next_session = delete_rows(session, set(action.row_ids))
        if next_session != session:
            self._push_category_undo(
                f"Delete {len(action.row_ids)} row{'' if len(action.row_ids) == 1 else 's'}"
            )
            self._set_category_session(next_session)
            self.category_selection.clear()
            self._render()

    def _push_category_undo(self, label: str) -> None:
        session = self.controller.state.session
        if session is None:
            return
        self.category_undo_stack.append(UndoEntry(session=session, label=label))

    def _undo_category_action(self) -> None:
        if not self.category_undo_stack:
            return
        self._set_category_session(self.category_undo_stack.pop().session)
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
        self.price_upper_entry.configure(
            state="normal" if range_enabled and not no_price else "disabled"
        )
        if not range_enabled:
            self.max_price.set("")
        if no_price:
            self.min_price.set("")
        self._populate_category_rows()

    def _stock_operator_changed(self) -> None:
        operator = self.stock_operator.get()
        range_enabled = operator == "range"
        fixed_zero = operator == "0"
        no_stock = operator in {"Any", "No stock"}
        if fixed_zero:
            self.stock_value.set("0")
        elif no_stock:
            self.stock_value.set("")
        if not range_enabled:
            self.stock_upper.set("")
        self.stock_value_entry.configure(state="disabled" if no_stock or fixed_zero else "normal")
        self.stock_upper_entry.configure(state="normal" if range_enabled else "disabled")
        self._populate_category_rows()

    def _go_to_edit(self) -> None:
        session = self.controller.state.session
        if session is not None:
            self.controller.set_session(prepare_edit_review(session))
        self.controller.go_to_edit_review()
        self.edit_undo_stack.clear()
        self.edit_no_barcode_only = False
        self.edit_duplicate_name_only = False
        self._load_next_edit_row()
        self._render()

    def _show_no_barcode_rows(self) -> None:
        self.edit_no_barcode_only = True
        self.edit_duplicate_name_only = False
        self.edit_selection.clear()
        self._populate_edit_rows()

    def _show_duplicate_name_edit_rows(self) -> None:
        self.edit_no_barcode_only = False
        self.edit_duplicate_name_only = True
        self.edit_selection.clear()
        self._populate_edit_rows()

    def _show_all_edit_rows(self) -> None:
        self.edit_no_barcode_only = False
        self.edit_duplicate_name_only = False
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
        self._push_edit_undo(
            f"Delete {len(self.edit_selection)} edit row{'' if len(self.edit_selection) == 1 else 's'}"
        )
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
            self._push_edit_undo(
                f"Merge {len(source_ids)} row{'' if len(source_ids) == 1 else 's'}"
            )
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
        ttk.Button(actions, text="Cancel", command=dialog.destroy).grid(
            row=0, column=2, sticky="e", padx=(8, 0)
        )
        target_combo.bind("<<ComboboxSelected>>", refresh_preview)
        refresh_preview()
        size_and_center(dialog, 980, 480)
        target_combo.focus_set()

    @staticmethod
    def _merge_row_label(row) -> str:
        return f"{row.row_id} - {row.item_name or '(missing name)'}"

    @staticmethod
    def _merge_preview_rows(
        rows, target_row_id: str
    ) -> tuple[tuple[str, str, str, str, str, str, str], ...]:
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
        edit_errors = self._edit_input_errors()
        if edit_errors:
            self.edit_validation.set("; ".join(edit_errors))
            self._update_edit_action_state()
            return
        current_row_id = self.current_edit_row_id
        displayed_before = self._displayed_edit_row_ids()
        next_session = self._preview_edit_save(session)
        saved_row = self._row_from_session(next_session, current_row_id)
        if saved_row is None:
            return
        if not self._edit_form_changed():
            if saved_row.status != "edit_complete":
                messagebox.showwarning(
                    APP_TITLE,
                    f"Row still needs review: {saved_row.review_reason or 'invalid edit values'}",
                )
                return
            if not messagebox.askyesno(
                APP_TITLE,
                "Save this valid row without changing any fields?",
            ):
                return
        if saved_row.status != "edit_complete":
            messagebox.showwarning(
                APP_TITLE,
                f"Row still needs review: {saved_row.review_reason or 'invalid edit values'}",
            )
            return
        if next_session == session:
            return
        self._push_edit_undo("Save row edit")
        self._set_edit_session(next_session)
        self._render()
        self._load_next_displayed_edit_row(current_row_id, displayed_before)

    def _edit_entry_return(self, _event: tk.Event) -> str:
        if str(self.save_edit_button.cget("state")) != "disabled":
            self._save_edit()
        return "break"

    def _push_edit_undo(self, label: str) -> None:
        session = self.controller.state.session
        if session is None:
            return
        self.edit_undo_stack.append(UndoEntry(session=session, label=label))

    def _undo_edit_action(self) -> None:
        if not self.edit_undo_stack:
            return
        previous_row_id = self.current_edit_row_id
        self._set_edit_session(self.edit_undo_stack.pop().session)
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
        errors = self._edit_input_errors()
        self.edit_validation.set("; ".join(errors))
        state = "disabled"
        if session is not None and self.current_edit_row_id is not None and not errors:
            row = self._row(self.current_edit_row_id)
            if self._edit_form_changed() or (row is not None and row.status == "needs_edit"):
                state = "normal"
        self.save_edit_button.configure(state=state)

    def _edit_input_errors(self) -> list[str]:
        session = self.controller.state.session
        if session is None or self.current_edit_row_id is None:
            return []
        return validate_edit_name_for_row(
            session,
            self.current_edit_row_id,
            self.edit_name.get(),
        )

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
        next_row_id = next_displayed_pos_row_id(
            previous_row_id, previous_displayed_row_ids, displayed
        )
        if next_row_id is None:
            self.current_pos_row_id = None
            self.pos_name.set("")
            self.pos_validation.set("")
            self._refresh_suggestions()
            return
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

    def _start_profile_inference_from_export(self) -> None:
        result = self.controller.state.result
        if result is None or self.profile_inference_running:
            return
        final_import = result.summary.output_paths.final_import
        profile_path = self._loaded_profile_path()
        output_root = result.run_dir / "POS Profile Inference"
        self.profile_inference_running = True
        self._render()
        self._run_worker(
            "profile_inferred",
            lambda: infer_pos_profile_from_final_import(
                final_import,
                existing_profile_path=profile_path,
                output_root=output_root,
            ),
        )

    def _loaded_profile_path(self) -> Path | None:
        value = self.venue_profile_text.get().strip()
        if not value:
            return None
        path = Path(value)
        return path if path.exists() else None

    def _open_result(self, target: str) -> None:
        result = self.controller.state.result
        if result is None:
            return
        paths = result.summary.output_paths
        targets = {
            "folder": result.run_dir,
            "final": paths.final_import,
            "core": paths.core_catalogue,
            "category": paths.category_audit,
            "naming": paths.naming_audit,
            "deleted": paths.deleted_audit,
            "summary": paths.summary,
        }
        try:
            open_path(targets[target])
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _open_profile_inference_result(self, target: str) -> None:
        result = self.profile_inference_result
        if result is None:
            return
        targets = {
            "folder": result.run_dir,
            "profile": result.summary.output_paths.proposed_profile,
            "audit": result.summary.output_paths.inference_audit,
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
        self.edit_final_row_button.configure(
            state="normal" if state.session is not None else "disabled"
        )
        self.export_button.configure(state="normal" if state.can_export else "disabled")
        self.infer_profile_button.configure(
            state="normal"
            if state.result is not None and not self.profile_inference_running
            else "disabled"
        )
        profile_result_state = "normal" if self.profile_inference_result is not None else "disabled"
        self.open_profile_proposal_button.configure(state=profile_result_state)
        self.open_profile_inference_audit_button.configure(state=profile_result_state)
        self.open_profile_inference_folder_button.configure(state=profile_result_state)
        self._update_pos_action_state()
        self._update_undo_buttons()
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

    def _update_undo_buttons(self) -> None:
        self.category_undo_button.configure(
            text=undo_button_text(self.category_undo_stack),
            state="normal" if self.category_undo_stack else "disabled",
        )
        self.edit_undo_button.configure(
            text=undo_button_text(self.edit_undo_stack),
            state="normal" if self.edit_undo_stack else "disabled",
        )

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
            name_filter=self._selected_name_filter(),
            old_category=self.old_category_filter.get(),
            barcode_filter=self._selected_barcode_filter(),
            category_assignment=self._selected_category_assignment_filter(),
            price_operator=self.price_operator.get(),  # type: ignore[arg-type]
            price_value=self.min_price.get(),
            price_upper=self.max_price.get(),
            stock_operator=self.stock_operator.get(),  # type: ignore[arg-type]
            stock_value=self.stock_value.get(),
            stock_upper=self.stock_upper.get(),
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
        self._apply_tree_sort(tree)

    def _populate_edit_rows(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.edit_tree)
        self._clear(tree)
        if session is None:
            return
        self.edit_category_combo.configure(values=session.category_names)
        if self.edit_no_barcode_only:
            rows = no_barcode_rows(session)
        elif self.edit_duplicate_name_only:
            rows = duplicate_name_edit_rows(session)
        else:
            rows = session.edit_queue
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
        self._apply_tree_sort(tree)
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

    def _selected_name_filter(self) -> str:
        value = self.name_filter.get()
        return "" if value == "Any" else value

    def _selected_pos_reason_filter(self) -> str:
        value = self.pos_reason_filter.get()
        return "" if value == "Any" else value

    def _selected_final_flag_filter(self) -> str:
        value = self.final_flag_filter.get()
        return "" if value == "Any" else value

    @staticmethod
    def _final_flag_filter_values() -> tuple[str, ...]:
        return (
            "Any",
            "Published",
            "Unpublished",
            "Orderable",
            "Not orderable",
            "Core Catalogue",
            "Not Core Catalogue",
        )

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
            tree.insert(
                "",
                "end",
                iid=row.row_id,
                values=(row.item_name, row.pos_name, row.status, row.review_reason),
            )
        self._apply_tree_sort(tree)
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
        self.final_flag_combo.configure(values=self._final_flag_filter_values())
        for row in filter_final_rows(
            session,
            keyword=self.final_filter.get(),
            flag_filter=self._selected_final_flag_filter(),
        ):
            tree.insert(
                "",
                "end",
                iid=row.row_id,
                values=(
                    row.item_name,
                    row.pos_name,
                    row.price,
                    row.barcode,
                    row.category,
                    "true" if row.is_published else "false",
                    "true" if row.is_orderable else "false",
                    "true" if row.core_catalogue else "false",
                ),
            )
        self._apply_tree_sort(tree)
        metadata = final_review_metadata(session)
        self.audit_text.set(
            final_review_audit_text(
                metadata,
                source_files=source_file_audits(self.controller.state),
            )
        )

    def _open_final_row_edit_dialog(self) -> None:
        session = self.controller.state.session
        tree = self._tree_widget(self.final_tree)
        row_id = self._selected_iid(tree)
        if session is None or row_id is None:
            messagebox.showwarning(APP_TITLE, "Select a final review row to edit.")
            return
        row = self._row(row_id)
        if row is None or row.status == "deleted":
            messagebox.showwarning(APP_TITLE, "Select an active final review row to edit.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit final review row")
        dialog.transient(self.root)
        dialog.grab_set()
        size_and_center(dialog, 920, 600)
        dialog.columnconfigure(0, weight=3)
        dialog.columnconfigure(1, weight=2)
        dialog.rowconfigure(0, weight=1)
        self.final_edit_dialog = dialog

        preview = ttk.LabelFrame(dialog, text="Selected row", padding=8)
        preview.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        preview_tree = ttk.Treeview(preview, columns=("field", "value"), show="headings", height=12)
        preview_tree.heading("field", text="Field")
        preview_tree.heading("value", text="Value")
        preview_tree.column("field", width=160, stretch=False)
        preview_tree.column("value", width=420)
        y_scroll = ttk.Scrollbar(preview, orient="vertical", command=preview_tree.yview)
        x_scroll = ttk.Scrollbar(preview, orient="horizontal", command=preview_tree.xview)
        preview_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        preview_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        for field, value in (
            ("BaseProductName", row.item_name),
            ("BaseProductPosName", row.pos_name),
            ("Price", row.price),
            ("Barcode", row.barcode),
            ("ProductCategories", row.category),
            ("IsPublished", "true" if row.is_published else "false"),
            ("IsOrderable", "true" if row.is_orderable else "false"),
            ("Core Catalogue", "true" if row.core_catalogue else "false"),
            ("Status", row.status),
            ("ReviewReason", row.review_reason),
            ("Source", row.candidate.source),
            ("OldCategory", row.old_category),
            ("Stock", row.candidate.stock),
        ):
            preview_tree.insert("", "end", values=(field, value))

        editor = ttk.LabelFrame(dialog, text="Edit values", padding=12)
        editor.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        editor.columnconfigure(1, weight=1)
        vars_by_field = {
            "item_name": tk.StringVar(value=row.item_name),
            "pos_name": tk.StringVar(value=row.pos_name),
            "price": tk.StringVar(value=row.price),
            "barcode": tk.StringVar(value=row.barcode),
            "category": tk.StringVar(value=row.category),
            "is_published": tk.BooleanVar(value=row.is_published),
            "is_orderable": tk.BooleanVar(value=row.is_orderable),
            "core_catalogue": tk.BooleanVar(value=row.core_catalogue),
        }
        self.final_edit_vars = vars_by_field
        fields = (
            ("Item name", "item_name"),
            ("POS name", "pos_name"),
            ("Price", "price"),
            ("Barcode", "barcode"),
            ("Category", "category"),
        )
        for index, (label, key) in enumerate(fields):
            ttk.Label(editor, text=label).grid(row=index, column=0, sticky="w", pady=5)
            if key == "category":
                entry = ttk.Combobox(
                    editor, textvariable=vars_by_field[key], values=session.category_names
                )
            else:
                entry = ttk.Entry(editor, textvariable=vars_by_field[key])
            entry.grid(row=index, column=1, sticky="ew", padx=(8, 0), pady=5)
        flag_start = len(fields)
        for offset, (label, key) in enumerate(
            (
                ("IsPublished", "is_published"),
                ("IsOrderable", "is_orderable"),
                ("Core Catalogue", "core_catalogue"),
            )
        ):
            ttk.Checkbutton(editor, text=label, variable=vars_by_field[key]).grid(
                row=flag_start + offset,
                column=0,
                columnspan=2,
                sticky="w",
                pady=3,
            )
        validation = tk.StringVar()
        self.final_edit_validation = validation
        ttk.Label(editor, textvariable=validation, foreground="#8a1f11", wraplength=320).grid(
            row=flag_start + 3,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )
        actions = ttk.Frame(editor)
        actions.grid(row=flag_start + 4, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        save_button = ttk.Button(
            actions, text="Save", command=lambda: self._save_final_row_edit(row_id)
        )
        save_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Cancel edit", command=dialog.destroy).grid(
            row=0, column=1, sticky="ew"
        )
        self.final_edit_save_button = save_button

        def refresh_validation(*_args) -> None:
            current_session = self.controller.state.session
            if current_session is None:
                errors = ["session is not available"]
            else:
                errors = validate_final_review_edit(
                    current_session,
                    row_id,
                    item_name=vars_by_field["item_name"].get(),
                    pos_name=vars_by_field["pos_name"].get(),
                    price=vars_by_field["price"].get(),
                    barcode=vars_by_field["barcode"].get(),
                    category=vars_by_field["category"].get(),
                    is_published=bool(vars_by_field["is_published"].get()),
                    is_orderable=bool(vars_by_field["is_orderable"].get()),
                    core_catalogue=bool(vars_by_field["core_catalogue"].get()),
                )
            validation.set("; ".join(errors))
            save_button.configure(state="disabled" if errors else "normal")

        for variable in vars_by_field.values():
            variable.trace_add("write", refresh_validation)
        refresh_validation()
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind(
            "<Return>",
            lambda _event: (
                self._save_final_row_edit(row_id)
                if str(save_button.cget("state")) != "disabled"
                else "break"
            ),
        )

    def _save_final_row_edit(self, row_id: str) -> str | None:
        session = self.controller.state.session
        if session is None or not hasattr(self, "final_edit_vars"):
            return "break"
        values = self.final_edit_vars
        errors = validate_final_review_edit(
            session,
            row_id,
            item_name=values["item_name"].get(),
            pos_name=values["pos_name"].get(),
            price=values["price"].get(),
            barcode=values["barcode"].get(),
            category=values["category"].get(),
            is_published=bool(values["is_published"].get()),
            is_orderable=bool(values["is_orderable"].get()),
            core_catalogue=bool(values["core_catalogue"].get()),
        )
        if errors:
            self.final_edit_validation.set("; ".join(errors))
            self.final_edit_save_button.configure(state="disabled")
            return "break"
        if not messagebox.askyesno(APP_TITLE, "Save edits to this final review row?"):
            return "break"
        try:
            updated_session = save_final_review_edit(
                session,
                row_id,
                item_name=values["item_name"].get(),
                pos_name=values["pos_name"].get(),
                price=values["price"].get(),
                barcode=values["barcode"].get(),
                category=values["category"].get(),
                is_published=bool(values["is_published"].get()),
                is_orderable=bool(values["is_orderable"].get()),
                core_catalogue=bool(values["core_catalogue"].get()),
            )
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))
            return "break"
        self.controller.set_session(
            updated_session,
            phase=AppPhase.FINAL_REVIEW,
            message="Final review row edited. Review the final upload data and export when ready.",
        )
        self._render()
        final_tree = self._tree_widget(self.final_tree)
        if final_tree.exists(row_id):
            final_tree.selection_set(row_id)
            final_tree.focus(row_id)
            final_tree.see(row_id)
        dialog = getattr(self, "final_edit_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        return "break"

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
        self._focus_edit_name(select_all=True)

    def _focus_edit_name(self, *, select_all: bool = False) -> None:
        def focus() -> None:
            if not hasattr(self, "edit_name_entry") or not self.edit_name_entry.winfo_exists():
                return
            self.edit_name_entry.focus_set()
            if select_all:
                self.edit_name_entry.selection_range(0, tk.END)
                self.edit_name_entry.icursor(tk.END)

        self.edit_name_entry.after_idle(focus)

    def _select_edit_tree_row(self, row_id: str) -> None:
        tree = self._tree_widget(self.edit_tree)
        current_selection = tree.selection()
        if current_selection:
            tree.selection_remove(current_selection)
        tree.selection_set(row_id)
        tree.focus(row_id)
        tree.see(row_id)

    def _displayed_edit_row_ids(self) -> list[str]:
        tree = self._tree_widget(self.edit_tree)
        return [str(row_id) for row_id in tree.get_children("")]

    def _load_next_displayed_edit_row(
        self,
        previous_row_id: str,
        previous_displayed_row_ids: list[str],
    ) -> None:
        displayed = self._displayed_edit_row_ids()
        next_row_id = next_displayed_row_id(previous_row_id, previous_displayed_row_ids, displayed)
        if next_row_id is None:
            self.current_edit_row_id = None
            self.edit_name.set("")
            self.edit_price.set("")
            self.edit_barcode.set("")
            self.edit_category.set("")
            self._update_edit_action_state()
            return
        self._select_edit_tree_row(next_row_id)
        self._load_edit_row(next_row_id)

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
        return validate_pos_name_for_row(
            session,
            self.current_pos_row_id,
            self._clean_edit_text(self.pos_name.get()),
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
