---
name: tkinter-gui-standards
description: Enforce Odin-Lunchtab repository standards for Tkinter/ttk interface changes, responsive windows, worker-thread processing, GUI tests, privacy-conscious diagnostics, PyInstaller builds, and Windows installer verification. Use whenever changing or reviewing this project's desktop GUI or GUI packaging.
---

# Odin Tkinter GUI Standards

Apply the global `build-tkinter-guis` skill first, then enforce these project rules.

- Keep reconciliation and managed-run logic independent of widgets.
- Keep controller/state logic separate from presentation and derive action enablement from state.
- Run validation, dry runs, processing, and other file work in daemon workers. Return results
  through queues and poll with `after()`; never touch Tk from workers.
- Show an indeterminate progress indicator and disable duplicate actions for every worker flow.
  Reset both on success and failure.
- Use shared helpers in `ui_helpers.py` for sizing, scrolling, tooltips, tables, and responsive
  button groups.
- Keep primary actions in sticky bottom bars. Ensure they remain mapped and reachable at
  1366x768 with Windows display scaling.
- Give data tables horizontal and vertical scrollbars and make long result/form regions
  scrollable.
- Keep diagnostics under `%LOCALAPPDATA%\Odin Lunchtab\logs`; never log student rows, names,
  identifiers, balances, or absolute source paths.
- Add focused controller/widget tests and run the full pytest and Ruff checks for shared GUI
  changes.
- For packaging changes, build the windowed PyInstaller `onedir` bundle on Windows x64 and run
  the frozen smoke test. Verify Tcl/Tk collection before changing dependencies.
- Preserve the CLI, profile schema compatibility, and existing reconciliation behavior unless
  the task explicitly changes them.
