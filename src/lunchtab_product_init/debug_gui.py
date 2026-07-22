from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from lunchtab_product_init.debug_fixture import (
    STAGE_LABELS,
    DebugFixtureError,
    DebugStagePreset,
    build_debug_stage,
    build_profile_edit_session,
    default_debug_output_root,
    default_fixture_paths,
    validate_debug_fixture,
)
from lunchtab_product_init.desktop import friendly_error, open_path
from lunchtab_product_init.gui import APP_TITLE, ProductInitializationApp
from lunchtab_product_init.gui_controller import AppPhase
from lunchtab_product_init.pos_profile_inference import (
    PosProfileInferenceResult,
    infer_pos_profile_from_final_import,
)
from lunchtab_product_init.session_workflow import load_venue_profile
from lunchtab_product_init.ui_helpers import size_and_center

DEBUG_TITLE = f"{APP_TITLE} - Dev Debug Launcher"


class DebugLauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.launched_windows: list[tk.Toplevel] = []
        self.profile_inference_result: PosProfileInferenceResult | None = None
        self.profile_inference_running = False

        root.title(DEBUG_TITLE)
        size_and_center(root, 780, 520)

        self.load_default_profile = tk.BooleanVar(value=True)
        self.alternate_profile_text = tk.StringVar()
        self.final_import_text = tk.StringVar()
        self.inference_profile_text = tk.StringVar()
        self.output_text = tk.StringVar(value=str(default_debug_output_root()))
        self.status_text = tk.StringVar(value="Validate fixture or launch a debug preset.")

        self._build()
        self._poll_events()

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        panel = ttk.Frame(self.root, padding=14)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        banner = ttk.Label(
            panel,
            text="Developer debug mode. Fixtures are read-only; generated artifacts use debug-output.",
            font=("", 10, "bold"),
        )
        banner.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        files = ttk.LabelFrame(panel, text="Inputs", padding=10)
        files.grid(row=1, column=0, sticky="ew")
        files.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            files,
            text="Load default fixture profile",
            variable=self.load_default_profile,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self._file_row(
            files,
            1,
            "Alternate profile",
            self.alternate_profile_text,
            self._choose_alternate_profile,
        )
        self._file_row(
            files,
            2,
            "Processed final CSV",
            self.final_import_text,
            self._choose_final_import,
        )
        self._file_row(
            files,
            3,
            "Inference profile",
            self.inference_profile_text,
            self._choose_inference_profile,
        )
        ttk.Label(files, text="Debug output").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(files, textvariable=self.output_text).grid(
            row=4, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(files, text="Browse...", command=self._choose_output_root).grid(
            row=4, column=2, pady=4
        )

        actions = ttk.LabelFrame(panel, text="Stage presets", padding=10)
        actions.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        for index in range(3):
            actions.columnconfigure(index, weight=1)
        stages: tuple[DebugStagePreset, ...] = (
            "step1",
            "step2",
            "step3",
            "step4",
            "step5",
            "step6",
        )
        for index, stage in enumerate(stages):
            ttk.Button(
                actions,
                text=STAGE_LABELS[stage],
                command=lambda value=stage: self._launch_stage(value),
            ).grid(row=index // 3, column=index % 3, sticky="ew", padx=5, pady=5)
        ttk.Button(
            actions,
            text="Open Step 4 Profile Editor",
            command=self._launch_profile_editor,
        ).grid(row=2, column=0, sticky="ew", padx=5, pady=(12, 5))
        ttk.Button(
            actions,
            text="Run POS Profile Inference",
            command=self._start_profile_inference,
        ).grid(row=2, column=1, sticky="ew", padx=5, pady=(12, 5))
        ttk.Button(actions, text="Open debug output", command=self._open_debug_output).grid(
            row=2, column=2, sticky="ew", padx=5, pady=(12, 5)
        )
        self.open_profile_button = ttk.Button(
            actions,
            text="Open inferred profile",
            command=lambda: self._open_profile_result("profile"),
        )
        self.open_profile_button.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        self.open_audit_button = ttk.Button(
            actions,
            text="Open inference audit",
            command=lambda: self._open_profile_result("audit"),
        )
        self.open_audit_button.grid(row=3, column=1, sticky="ew", padx=5, pady=5)
        self.open_profile_folder_button = ttk.Button(
            actions,
            text="Open inference folder",
            command=lambda: self._open_profile_result("folder"),
        )
        self.open_profile_folder_button.grid(row=3, column=2, sticky="ew", padx=5, pady=5)

        bottom = ttk.Frame(panel)
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_text).grid(row=0, column=0, sticky="ew")
        ttk.Button(bottom, text="Validate fixture", command=self._validate_fixture).grid(
            row=0, column=1, sticky="e", padx=(8, 0)
        )
        self._update_profile_result_buttons()

    @staticmethod
    def _file_row(
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, pady=4)

    def _choose_alternate_profile(self) -> None:
        self._choose_file(self.alternate_profile_text, "Load alternate venue profile", "*.json")

    def _choose_final_import(self) -> None:
        self._choose_file(self.final_import_text, "Load processed final import CSV", "*.csv")

    def _choose_inference_profile(self) -> None:
        self._choose_file(self.inference_profile_text, "Load inference profile", "*.json")

    def _choose_file(self, variable: tk.StringVar, title: str, pattern: str) -> None:
        selected = filedialog.askopenfilename(title=title, filetypes=[("Supported files", pattern)])
        if selected:
            variable.set(selected)

    def _choose_output_root(self) -> None:
        selected = filedialog.askdirectory(title="Select debug output folder")
        if selected:
            self.output_text.set(selected)

    def _validate_fixture(self) -> None:
        try:
            paths = validate_debug_fixture()
        except Exception as error:
            messagebox.showerror(DEBUG_TITLE, friendly_error(error))
            self.status_text.set(f"Fixture validation failed: {error}")
            return
        self.status_text.set(f"Fixture validated: {paths.fixture_dir}")

    def _launch_stage(self, stage: DebugStagePreset) -> None:
        try:
            profile_path = self._alternate_profile_path()
            result = build_debug_stage(
                stage,
                profile_path=profile_path,
                load_default_profile=self.load_default_profile.get(),
                output_root=self._output_root(),
            )
            app = self._new_product_app()
            self._configure_product_app(app, stage=stage, session_result=result)
        except Exception as error:
            messagebox.showerror(DEBUG_TITLE, friendly_error(error))
            self.status_text.set(f"{STAGE_LABELS[stage]} failed: {error}")
            return
        self.status_text.set(f"Launched {STAGE_LABELS[stage]}.")

    def _launch_profile_editor(self) -> None:
        try:
            session = build_profile_edit_session(
                profile_path=self._alternate_profile_path(),
                load_default_profile=self.load_default_profile.get(),
            )
            app = self._new_product_app()
            self._configure_common_paths(app)
            app.controller.set_session(
                session,
                phase=AppPhase.POS_REVIEW,
                message="Debug profile editor loaded at Step 4.",
            )
            self._configure_loaded_profile(app)
            app._render()
            app.notebook.select(app.tabs["pos"])
        except Exception as error:
            messagebox.showerror(DEBUG_TITLE, friendly_error(error))
            self.status_text.set(f"Profile editor launch failed: {error}")
            return
        self.status_text.set("Launched Step 4 profile editor.")

    def _start_profile_inference(self) -> None:
        if self.profile_inference_running:
            return
        try:
            final_import = self._final_import_path()
            profile_path = self._inference_profile_path()
            output_root = self._output_root() / "profile-inference"
        except Exception as error:
            messagebox.showerror(DEBUG_TITLE, friendly_error(error))
            return
        self.profile_inference_running = True
        self.profile_inference_result = None
        self.status_text.set("Running POS profile inference...")
        self._update_profile_result_buttons()

        def worker() -> None:
            try:
                result = infer_pos_profile_from_final_import(
                    final_import,
                    existing_profile_path=profile_path,
                    output_root=output_root,
                )
            except Exception as error:  # pragma: no cover - exercised through GUI path
                self.events.put(("profile_error", error))
            else:
                self.events.put(("profile_complete", result))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                name, payload = self.events.get_nowait()
                if name == "profile_complete":
                    self.profile_inference_running = False
                    self.profile_inference_result = payload  # type: ignore[assignment]
                    self.status_text.set("POS profile inference complete.")
                    self._update_profile_result_buttons()
                    result = self.profile_inference_result
                    if result is not None:
                        messagebox.showinfo(
                            DEBUG_TITLE, f"Profile proposal written to {result.run_dir}"
                        )
                elif name == "profile_error":
                    self.profile_inference_running = False
                    self.profile_inference_result = None
                    self.status_text.set(f"POS profile inference failed: {payload}")
                    self._update_profile_result_buttons()
                    messagebox.showerror(DEBUG_TITLE, friendly_error(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _new_product_app(self) -> ProductInitializationApp:
        window = tk.Toplevel(self.root)
        self.launched_windows.append(window)
        return ProductInitializationApp(window)

    def _configure_product_app(
        self,
        app: ProductInitializationApp,
        *,
        stage: DebugStagePreset,
        session_result,
    ) -> None:
        self._configure_common_paths(app)
        phase = {
            "step1": AppPhase.CATEGORIZING,
            "step2": AppPhase.EDIT_REVIEW,
            "step3": AppPhase.POS_REVIEW,
            "step4": AppPhase.FINAL_REVIEW,
            "step5": AppPhase.FINAL_REVIEW,
            "step6": AppPhase.COMPLETE,
        }[stage]
        app.controller.set_session(
            session_result.session,
            phase=phase,
            message=f"Debug preset loaded: {STAGE_LABELS[stage]}.",
        )
        if session_result.result is not None:
            app.controller.export_succeeded(session_result.result)
        self._configure_loaded_profile(app)
        app._render()
        if stage == "step1":
            app.notebook.select(app.tabs["categories"])
        elif stage == "step2":
            app.notebook.select(app.tabs["edit"])
        elif stage == "step3":
            app.notebook.select(app.tabs["pos"])
            app._load_first_pos_row()
        elif stage in {"step4", "step5"}:
            app.notebook.select(app.tabs["final"])
        else:
            app.notebook.select(app.tabs["complete"])

    def _configure_common_paths(self, app: ProductInitializationApp) -> None:
        paths = default_fixture_paths()
        output_root = self._output_root()
        app.controller.select_product_template(paths.product_template)
        app.controller.select_recipe_list(paths.recipe_list)
        app.controller.select_generic_inventory(paths.generic_inventory)
        app.controller.select_output_root(output_root)
        app.product_template_text.set(str(paths.product_template))
        app.recipe_list_text.set(str(paths.recipe_list))
        app.odin_inventory_text.set("")
        app.generic_inventory_text.set(str(paths.generic_inventory))
        app.output_text.set(str(output_root))

    def _configure_loaded_profile(self, app: ProductInitializationApp) -> None:
        profile_path = self._alternate_profile_path()
        if profile_path is None and self.load_default_profile.get():
            profile_path = default_fixture_paths().venue_profile
        if profile_path is None:
            app.venue_profile = None
            app.venue_profile_text.set("")
            return
        app.venue_profile = load_venue_profile(profile_path)
        app.venue_profile_text.set(str(profile_path))

    def _alternate_profile_path(self) -> Path | None:
        value = self.alternate_profile_text.get().strip()
        if not value:
            return None
        path = Path(value)
        if not path.exists():
            raise DebugFixtureError(f"Alternate profile does not exist: {path}")
        return path

    def _inference_profile_path(self) -> Path | None:
        value = self.inference_profile_text.get().strip()
        if value:
            path = Path(value)
            if not path.exists():
                raise DebugFixtureError(f"Inference profile does not exist: {path}")
            return path
        alternate = self._alternate_profile_path()
        if alternate is not None:
            return alternate
        return default_fixture_paths().venue_profile if self.load_default_profile.get() else None

    def _final_import_path(self) -> Path:
        value = self.final_import_text.get().strip()
        if value:
            path = Path(value)
            if not path.exists():
                raise DebugFixtureError(f"Processed final import CSV does not exist: {path}")
            return path
        return default_fixture_paths().final_import

    def _output_root(self) -> Path:
        value = self.output_text.get().strip()
        return Path(value) if value else default_debug_output_root()

    def _open_debug_output(self) -> None:
        self._output_root().mkdir(parents=True, exist_ok=True)
        self._open_path(self._output_root())

    def _open_profile_result(self, target: str) -> None:
        result = self.profile_inference_result
        if result is None:
            return
        targets = {
            "profile": result.summary.output_paths.proposed_profile,
            "audit": result.summary.output_paths.inference_audit,
            "folder": result.run_dir,
        }
        self._open_path(targets[target])

    def _open_path(self, path: Path) -> None:
        try:
            open_path(path)
        except Exception as error:
            messagebox.showerror(DEBUG_TITLE, friendly_error(error))

    def _update_profile_result_buttons(self) -> None:
        state = "normal" if self.profile_inference_result is not None else "disabled"
        self.open_profile_button.configure(state=state)
        self.open_audit_button.configure(state=state)
        self.open_profile_folder_button.configure(state=state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-test", action="store_true")
    return parser


def main() -> None:
    args, _ = build_parser().parse_known_args()
    if args.smoke_test:
        validate_debug_fixture()
        return
    root = tk.Tk()
    DebugLauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
