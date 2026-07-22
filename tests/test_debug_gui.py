from __future__ import annotations

import tkinter as tk

import pytest

from lunchtab_product_init import debug_gui as debug_gui_module
from lunchtab_product_init.debug_gui import DebugLauncherApp
from lunchtab_product_init.gui_controller import AppPhase


@pytest.fixture(scope="module")
def debug_app():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display is not available: {error}")
    root.withdraw()
    app = DebugLauncherApp(root)
    root.update_idletasks()
    try:
        yield app
    finally:
        root.destroy()


def test_debug_launcher_configures_stage_phase(debug_app, monkeypatch) -> None:
    captured = []

    def fake_new_product_app():
        app = debug_gui_module.ProductInitializationApp(tk.Toplevel(debug_app.root))
        captured.append(app)
        return app

    monkeypatch.setattr(debug_app, "_new_product_app", fake_new_product_app)

    debug_app._launch_stage("step4")

    assert captured[-1].controller.state.phase == AppPhase.FINAL_REVIEW
    assert captured[-1].controller.state.session is not None
    assert captured[-1].controller.state.session.can_export


def test_debug_launcher_profile_editor_opens_pos_phase(debug_app, monkeypatch) -> None:
    captured = []

    def fake_new_product_app():
        app = debug_gui_module.ProductInitializationApp(tk.Toplevel(debug_app.root))
        captured.append(app)
        return app

    monkeypatch.setattr(debug_app, "_new_product_app", fake_new_product_app)

    debug_app._launch_profile_editor()

    assert captured[-1].controller.state.phase == AppPhase.POS_REVIEW
    assert captured[-1].controller.state.session is not None
    assert captured[-1].controller.state.session.pos_preferences.abbreviation_options
