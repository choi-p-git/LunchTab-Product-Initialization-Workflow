from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from lunchtab_product_init.categories import (
    infer_categories,
    load_category_profile,
    save_category_profile,
)
from lunchtab_product_init.desktop import friendly_error, open_path
from lunchtab_product_init.gui_controller import AppController, AppPhase
from lunchtab_product_init.models import (
    BuildInputs,
    CategoryCatalogEntry,
    CategoryProfile,
    CategoryRule,
    ProductCandidate,
)
from lunchtab_product_init.ui_helpers import ScrollableFrame, size_and_center
from lunchtab_product_init.workflow import build_product_import

APP_TITLE = "Lunchtab Product Initialization"


class ProductInitializationApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.controller = AppController()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        root.title(APP_TITLE)
        size_and_center(root, 900, 680)

        self.product_template_text = tk.StringVar()
        self.recipe_list_text = tk.StringVar()
        self.odin_inventory_text = tk.StringVar()
        self.category_profile_text = tk.StringVar(value="Built-in current venue starter profile")
        self.output_text = tk.StringVar(value=str(self.controller.state.output_root))
        self.status_text = tk.StringVar(value=self.controller.state.message)
        self.details_text = tk.StringVar(value="")

        self._build()
        self._render()
        root.after(100, self._poll_events)

    def _build(self) -> None:
        scroller = ScrollableFrame(self.root, padding=22)
        scroller.pack(fill="both", expand=True)
        outer = scroller.content

        ttk.Label(outer, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Build an audited product import CSV from Lunchtab, recipe-list, and Odin exports.",
        ).pack(anchor="w", pady=(3, 20))

        files = ttk.LabelFrame(outer, text="Source files", padding=14)
        files.pack(fill="x")
        files.columnconfigure(1, weight=1)
        self._file_row(files, 0, "ProductData template", self.product_template_text, self._choose_template)
        self._file_row(files, 1, "Recipe list", self.recipe_list_text, self._choose_recipe)
        self._file_row(files, 2, "Odin inventory", self.odin_inventory_text, self._choose_odin)
        self._file_row(files, 3, "Category profile", self.category_profile_text, self._choose_profile)
        ttk.Button(files, text="Manage...", command=self._manage_profile).grid(row=3, column=3, pady=5)
        self._file_row(files, 4, "Save results in", self.output_text, self._choose_output)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=14)
        self.build_button = ttk.Button(actions, text="Build product import", command=self._start_build)
        self.build_button.grid(row=0, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        results = ttk.LabelFrame(outer, text="Status and results", padding=14)
        results.pack(fill="both", expand=True)
        ttk.Label(results, textvariable=self.status_text, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(results, textvariable=self.details_text, justify="left", wraplength=700).pack(
            anchor="w", pady=(10, 14)
        )
        result_actions = ttk.Frame(results)
        result_actions.pack(fill="x")
        self.open_folder_button = ttk.Button(
            result_actions, text="Open results folder", command=lambda: self._open_result("folder")
        )
        self.open_final_button = ttk.Button(
            result_actions, text="Open import CSV", command=lambda: self._open_result("final")
        )
        self.open_review_button = ttk.Button(
            result_actions, text="Open manual review", command=lambda: self._open_result("review")
        )
        self.open_audit_button = ttk.Button(
            result_actions, text="Open naming audit", command=lambda: self._open_result("naming")
        )
        self.open_category_audit_button = ttk.Button(
            result_actions, text="Open category audit", command=lambda: self._open_result("category")
        )
        for index, button in enumerate(
            [
                self.open_folder_button,
                self.open_final_button,
                self.open_review_button,
                self.open_audit_button,
                self.open_category_audit_button,
            ]
        ):
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 8, 0), pady=(0 if index < 2 else 8, 0))
        result_actions.columnconfigure(0, weight=1)
        result_actions.columnconfigure(1, weight=1)

        ttk.Label(
            outer,
            text="Source files are never changed. Low-confidence rows are written to manual review.",
            foreground="#555555",
        ).pack(anchor="w", pady=(14, 0))

    @staticmethod
    def _file_row(
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label, width=20).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, state="readonly").grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, pady=5)

    def _choose_template(self) -> None:
        selected = filedialog.askopenfilename(title="Select ProductData template", filetypes=[("CSV files", "*.csv")])
        if selected:
            self.product_template_text.set(selected)
            self.controller.select_product_template(Path(selected))
            self._render()

    def _choose_recipe(self) -> None:
        selected = filedialog.askopenfilename(title="Select recipe list", filetypes=[("CSV files", "*.csv")])
        if selected:
            self.recipe_list_text.set(selected)
            self.controller.select_recipe_list(Path(selected))
            self._render()

    def _choose_odin(self) -> None:
        selected = filedialog.askopenfilename(title="Select Odin inventory workbook", filetypes=[("Excel workbooks", "*.xlsx")])
        if selected:
            self.odin_inventory_text.set(selected)
            self.controller.select_odin_inventory(Path(selected))
            self._render()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose the parent folder for timestamped results")
        if selected:
            self.output_text.set(selected)
            self.controller.select_output_root(Path(selected))
            self._render()

    def _choose_profile(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select category profile",
            filetypes=[("JSON files", "*.json")],
        )
        if selected:
            try:
                load_category_profile(Path(selected))
            except Exception as error:
                messagebox.showerror(APP_TITLE, friendly_error(error))
                return
            self.category_profile_text.set(selected)
            self.controller.select_category_profile(Path(selected))
            self._render()

    def _manage_profile(self) -> None:
        current_path = self.controller.state.category_profile_path
        try:
            profile = load_category_profile(current_path)
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))
            return
        manager = CategoryProfileManager(self.root, profile)
        self.root.wait_window(manager)
        if manager.saved_path is not None:
            self.category_profile_text.set(str(manager.saved_path))
            self.controller.select_category_profile(manager.saved_path)
            self._render()

    def _start_build(self) -> None:
        state = self.controller.begin_build()
        self._render()
        inputs = BuildInputs(
            product_template_path=state.product_template_path,  # type: ignore[arg-type]
            recipe_list_path=state.recipe_list_path,  # type: ignore[arg-type]
            odin_inventory_path=state.odin_inventory_path,  # type: ignore[arg-type]
            output_root=state.output_root,
            category_profile_path=state.category_profile_path,
        )
        self._run_worker("built", lambda: build_product_import(inputs))

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
                if name == "built":
                    self.controller.build_succeeded(payload)  # type: ignore[arg-type]
                else:
                    self.controller.failed(friendly_error(payload))
                    messagebox.showerror(APP_TITLE, friendly_error(payload))
                self._render()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _open_result(self, target: str) -> None:
        result = self.controller.state.result
        if result is None:
            return
        targets = {
            "folder": result.run_dir,
            "final": result.summary.output_paths.final_import,
            "review": result.summary.output_paths.manual_review,
            "naming": result.summary.output_paths.naming_audit,
            "category": result.summary.output_paths.category_audit,
        }
        try:
            open_path(targets[target])
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _render(self) -> None:
        state = self.controller.state
        busy = state.phase == AppPhase.PROCESSING
        self.build_button.configure(state="normal" if state.can_build else "disabled")
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()
        self.status_text.set(state.message)
        if state.result:
            summary = state.result.summary
            self.details_text.set(
                f"Candidate rows: {summary.candidate_rows}\n"
                f"Auto-accepted rows: {summary.accepted_rows}\n"
                f"Manual-review rows: {summary.manual_review_rows}\n"
                f"Duplicate barcodes: {summary.duplicate_barcodes}\n"
                f"Duplicate generated POS names: {summary.duplicate_pos_names}\n\n"
                f"Category-review rows: {summary.category_review_rows}\n"
                f"\n"
                f"Saved to: {state.result.run_dir}"
            )
        else:
            self.details_text.set("")
        result_state = "normal" if state.result else "disabled"
        self.open_folder_button.configure(state=result_state)
        self.open_final_button.configure(state=result_state)
        self.open_review_button.configure(state=result_state)
        self.open_audit_button.configure(state=result_state)
        self.open_category_audit_button.configure(state=result_state)


class CategoryProfileManager(tk.Toplevel):
    def __init__(self, parent: tk.Tk, profile: CategoryProfile) -> None:
        super().__init__(parent)
        self.profile = profile
        self.saved_path: Path | None = None
        self.title("Category Profile")
        self.transient(parent)
        self.geometry("860x620")
        self.minsize(760, 520)
        self._build()
        self._refresh()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        ttk.Label(outer, text=self.profile.name, font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
        notebook = ttk.Notebook(outer)
        notebook.grid(row=1, column=0, sticky="nsew")
        catalog_tab = ttk.Frame(notebook, padding=10)
        rules_tab = ttk.Frame(notebook, padding=10)
        test_tab = ttk.Frame(notebook, padding=10)
        notebook.add(catalog_tab, text="Categories")
        notebook.add(rules_tab, text="Rules")
        notebook.add(test_tab, text="Test")
        self._build_catalog_tab(catalog_tab)
        self._build_rules_tab(rules_tab)
        self._build_test_tab(test_tab)
        actions = ttk.Frame(outer)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Export...", command=self._export).pack(side="right")
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right", padx=(0, 8))

    def _build_catalog_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        columns = ("name", "role", "policy", "enabled", "notes")
        self.catalog_tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        labels = ("Name", "Role", "Spending Policy", "Enabled", "Notes")
        for column, label in zip(columns, labels, strict=True):
            self.catalog_tree.heading(column, text=label)
            self.catalog_tree.column(column, width=130 if column != "notes" else 260)
        self.catalog_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.catalog_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.catalog_tree.configure(yscrollcommand=scrollbar.set)
        ttk.Button(parent, text="Add category", command=self._add_category).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

    def _build_rules_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        columns = ("id", "type", "pattern", "categories", "confidence", "priority", "enabled")
        self.rules_tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        labels = ("Rule ID", "Type", "Pattern", "Categories", "Confidence", "Priority", "Enabled")
        for column, label in zip(columns, labels, strict=True):
            self.rules_tree.heading(column, text=label)
            self.rules_tree.column(column, width=130 if column != "categories" else 230)
        self.rules_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.rules_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.rules_tree.configure(yscrollcommand=scrollbar.set)
        ttk.Button(parent, text="Add rule", command=self._add_rule).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

    def _build_test_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self.test_name = tk.StringVar()
        self.test_source_category = tk.StringVar()
        self.test_barcode = tk.StringVar()
        self.test_result = tk.StringVar()
        rows = (
            ("Item name", self.test_name),
            ("Source category", self.test_source_category),
            ("Barcode", self.test_barcode),
        )
        for row, (label, variable) in enumerate(rows):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Test rules", command=self._test_rules).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(parent, textvariable=self.test_result, justify="left", wraplength=700).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def _refresh(self) -> None:
        for row in self.catalog_tree.get_children():
            self.catalog_tree.delete(row)
        for entry in self.profile.catalog:
            self.catalog_tree.insert(
                "",
                "end",
                values=(entry.name, entry.role, entry.spending_policy, entry.enabled, entry.notes),
            )
        for row in self.rules_tree.get_children():
            self.rules_tree.delete(row)
        for rule in sorted(self.profile.rules, key=lambda item: (item.priority, item.rule_id)):
            self.rules_tree.insert(
                "",
                "end",
                values=(
                    rule.rule_id,
                    rule.rule_type,
                    rule.pattern,
                    ";".join(rule.categories),
                    rule.confidence,
                    rule.priority,
                    rule.enabled,
                ),
            )

    def _add_category(self) -> None:
        name = simpledialog.askstring("Add category", "Category name", parent=self)
        if not name:
            return
        role = simpledialog.askstring("Add category", "Role: food, policy, or hybrid", parent=self)
        if role not in {"food", "policy", "hybrid"}:
            messagebox.showerror(APP_TITLE, "Role must be food, policy, or hybrid.")
            return
        policy = simpledialog.askstring(
            "Add category",
            "Spending policy: none, restrictable, or exempt",
            parent=self,
        )
        if policy not in {"none", "restrictable", "exempt"}:
            messagebox.showerror(APP_TITLE, "Spending policy must be none, restrictable, or exempt.")
            return
        entry = CategoryCatalogEntry(name=name.strip(), role=role, spending_policy=policy)
        self.profile = CategoryProfile(
            self.profile.schema_version,
            self.profile.name,
            (*self.profile.catalog, entry),
            self.profile.rules,
        )
        self._refresh()

    def _add_rule(self) -> None:
        rule_id = simpledialog.askstring("Add rule", "Rule ID", parent=self)
        if not rule_id:
            return
        rule_type = simpledialog.askstring(
            "Add rule",
            "Rule type: barcode, item_name, source_category, phrase, or token",
            parent=self,
        )
        if rule_type not in {"barcode", "item_name", "source_category", "phrase", "token"}:
            messagebox.showerror(APP_TITLE, "Invalid rule type.")
            return
        pattern = simpledialog.askstring("Add rule", "Pattern", parent=self)
        categories = simpledialog.askstring(
            "Add rule",
            "Target categories separated by semicolons",
            parent=self,
        )
        confidence = simpledialog.askinteger("Add rule", "Confidence 0-100", parent=self, initialvalue=90)
        priority = simpledialog.askinteger("Add rule", "Priority", parent=self, initialvalue=300)
        if not pattern or not categories or confidence is None or priority is None:
            return
        rule = CategoryRule(
            rule_id=rule_id.strip(),
            rule_type=rule_type,
            pattern=pattern.strip(),
            categories=tuple(category.strip() for category in categories.split(";") if category.strip()),
            confidence=confidence,
            priority=priority,
        )
        self.profile = CategoryProfile(
            self.profile.schema_version,
            self.profile.name,
            self.profile.catalog,
            (*self.profile.rules, rule),
        )
        self._refresh()

    def _test_rules(self) -> None:
        candidate = ProductCandidate(
            source="test",
            source_key="test",
            item_name=self.test_name.get(),
            price="",
            barcode=self.test_barcode.get(),
            category=self.test_source_category.get(),
        )
        try:
            result = infer_categories(candidate, self.profile)
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))
            return
        self.test_result.set(
            "Categories: "
            + "; ".join(result.categories)
            + "\n"
            + f"Status: {result.status}\n"
            + f"Confidence: {result.confidence} ({result.confidence_band})\n"
            + f"Matched rules: {' | '.join(result.matched_rules) or 'None'}\n"
            + f"Reason: {result.reason or 'Ready'}"
        )

    def _export(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Export category profile",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not selected:
            return
        try:
            save_category_profile(self.profile, Path(selected))
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))
            return
        self.saved_path = Path(selected)
        messagebox.showinfo(APP_TITLE, f"Category profile saved to {selected}")


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
