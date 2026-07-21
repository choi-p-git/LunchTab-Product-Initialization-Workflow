# Release Notes

## v0.4.0 - Internal POC

This is an internal proof-of-concept build for operator validation. It is not a full `1.0.0`
production release.

### Added

- Guided six-step product import workflow from source parsing through export completion.
- Category assignment, edit review, POS-name review, final review, and export-complete GUI tabs.
- Optional Odin or generic inventory enrichment, with single-inventory-source validation.
- Barcode merge handling, deleted-row audit output, source hash metadata, and Core Catalogue export.
- POS-name preference learning, ranked suggestions, edit-effort metrics, and profile audits.
- POS profile inference from accepted final import CSVs, including in-app proposal generation after
  export.
- Operator quick-start, SOP draft, knowledge-base extracts, and business requirements roadmap.
- Widget-level and raw-data regression coverage for the guided workflow.

### Packaging

- Windows PyInstaller `onedir` bundle.
- Portable zip archive for no-install testing.
- Inno Setup per-user installer with Start Menu shortcut and optional desktop shortcut.
- Release script: `scripts\build-release.ps1`.

### Verification

- Full pytest suite.
- Ruff lint and targeted format checks.
- Source app smoke tests.
- Frozen executable smoke test.
- Portable zip extract/run smoke test.
- Silent installer install/run/uninstall smoke test.
