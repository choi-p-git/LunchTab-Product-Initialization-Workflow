from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from lunchtab_product_init.desktop import friendly_error, open_path
from lunchtab_product_init.pos_name_controller import PosNameAppController, PosNameAppPhase
from lunchtab_product_init.pos_name_workflow import run_pos_name_automation
from lunchtab_product_init.ui_helpers import ScrollableFrame, size_and_center

APP_TITLE = "BaseProductPosName Automation"


class BaseProductPosNameApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.controller = PosNameAppController()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        root.title(APP_TITLE)
        size_and_center(root, 760, 520)

        self.input_text = tk.StringVar()
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
            text="Generate BaseProductPosName values for an existing Lunchtab target CSV.",
        ).pack(anchor="w", pady=(3, 20))

        files = ttk.LabelFrame(outer, text="Files", padding=14)
        files.pack(fill="x")
        files.columnconfigure(1, weight=1)
        self._file_row(files, 0, "Target CSV", self.input_text, self._choose_input)
        self._file_row(files, 1, "Save results in", self.output_text, self._choose_output)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=14)
        self.process_button = ttk.Button(
            actions, text="Run BaseProductPosName automation", command=self._start_process
        )
        self.process_button.grid(row=0, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        results = ttk.LabelFrame(outer, text="Status and results", padding=14)
        results.pack(fill="both", expand=True)
        ttk.Label(results, textvariable=self.status_text, font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        ttk.Label(results, textvariable=self.details_text, justify="left", wraplength=650).pack(
            anchor="w", pady=(10, 14)
        )
        result_actions = ttk.Frame(results)
        result_actions.pack(fill="x")
        self.open_folder_button = ttk.Button(
            result_actions, text="Open results folder", command=lambda: self._open_result("folder")
        )
        self.open_processed_button = ttk.Button(
            result_actions,
            text="Open processed CSV",
            command=lambda: self._open_result("processed"),
        )
        self.open_audit_button = ttk.Button(
            result_actions, text="Open naming audit", command=lambda: self._open_result("audit")
        )
        for index, button in enumerate(
            [self.open_folder_button, self.open_processed_button, self.open_audit_button]
        ):
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            result_actions.columnconfigure(index, weight=1)

        ttk.Label(
            outer,
            text="The selected CSV must exactly match the Lunchtab target CSV header.",
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
        ttk.Label(parent, text=label, width=16).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, state="readonly").grid(
            row=row, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, pady=5)

    def _choose_input(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Lunchtab target CSV", filetypes=[("CSV files", "*.csv")]
        )
        if selected:
            self.input_text.set(selected)
            self.controller.select_input_csv(Path(selected))
            self._render()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose the parent folder for timestamped results")
        if selected:
            self.output_text.set(selected)
            self.controller.select_output_root(Path(selected))
            self._render()

    def _start_process(self) -> None:
        state = self.controller.begin_process()
        self._render()
        input_path = state.input_csv_path
        output_root = state.output_root
        if input_path is None:
            self.controller.failed("Select a Lunchtab target CSV before processing.")
            self._render()
            return
        self._run_worker(
            "processed",
            lambda: run_pos_name_automation(input_path, output_root),
        )

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
                if name == "processed":
                    self.controller.process_succeeded(payload)  # type: ignore[arg-type]
                else:
                    message = friendly_error(payload)
                    self.controller.failed(message)
                    messagebox.showerror(APP_TITLE, message)
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
            "processed": result.summary.output_paths.processed_csv,
            "audit": result.summary.output_paths.naming_audit,
        }
        try:
            open_path(targets[target])
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _render(self) -> None:
        state = self.controller.state
        busy = state.phase == PosNameAppPhase.PROCESSING
        self.process_button.configure(state="normal" if state.can_process else "disabled")
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()
        self.status_text.set(state.message)
        if state.result:
            summary = state.result.summary
            self.details_text.set(
                f"Total rows: {summary.total_rows}\n"
                f"Ready rows: {summary.ok_rows}\n"
                f"Skipped rows: {summary.skipped_rows}\n"
                f"Review rows: {summary.review_rows}\n"
                f"Duplicate generated POS names: {summary.duplicate_pos_names}\n\n"
                f"Saved to: {state.result.run_dir}"
            )
        else:
            self.details_text.set("")
        result_state = "normal" if state.result else "disabled"
        self.open_folder_button.configure(state=result_state)
        self.open_processed_button.configure(state=result_state)
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
    BaseProductPosNameApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
