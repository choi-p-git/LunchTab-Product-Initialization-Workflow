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
from lunchtab_product_init.models import BuildInputs
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
        self._file_row(files, 3, "Save results in", self.output_text, self._choose_output)

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
        for index, button in enumerate(
            [self.open_folder_button, self.open_final_button, self.open_review_button, self.open_audit_button]
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

    def _start_build(self) -> None:
        state = self.controller.begin_build()
        self._render()
        inputs = BuildInputs(
            product_template_path=state.product_template_path,  # type: ignore[arg-type]
            recipe_list_path=state.recipe_list_path,  # type: ignore[arg-type]
            odin_inventory_path=state.odin_inventory_path,  # type: ignore[arg-type]
            output_root=state.output_root,
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
                f"Saved to: {state.result.run_dir}"
            )
        else:
            self.details_text.set("")
        result_state = "normal" if state.result else "disabled"
        self.open_folder_button.configure(state=result_state)
        self.open_final_button.configure(state=result_state)
        self.open_review_button.configure(state=result_state)
        self.open_audit_button.configure(state=result_state)


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
