---
name: github-workflow-standards
description: Enforce Odin-Lunchtab GitHub practices for issues, pull requests, CI, reviews, installer releases, version synchronization, checksums, upgrade testing, and private distribution. Use whenever inspecting or publishing this project through GitHub.
---

# Odin GitHub Workflow Standards

Apply the global `manage-github-workflows` skill first, then enforce these project rules.

- Confirm repository visibility and the approved internal audience before publishing anything.
  Do not make the repository, releases, or assets public without explicit authorization.
- Never upload Odin or Lunchtab source exports, processed student data, transfer reports,
  diagnostic logs containing records, or venue profiles/crosswalks containing identifiers.
- Use feature branches and reviewed pull requests. Require explicit authorization before every
  comment, label, assignment, push, PR, merge, tag, release, or asset upload workflow.
- For releases, synchronize the project version across `pyproject.toml`, `uv.lock`, installer
  fallback metadata, generated Windows version metadata, filenames, and documentation.
- Build installers on Windows x64 from a locked environment. Run tests, Ruff, the PyInstaller
  frozen-GUI smoke test, and manual fresh-install, upgrade, no-admin, and uninstall checks.
- Publish only the approved installer, SHA-256 checksum, release notes, and short user guide.
  ZIP output, automatic updates, and public hosting remain out of scope unless explicitly added.
- Name the installer `Odin-Lunchtab-Setup-<version>-x64.exe` and verify the uploaded checksum
  against the local release artifact.
- Record any Windows 10/11 manual checks that remain incomplete; do not describe the release as
  production-ready until required platform verification is done.
