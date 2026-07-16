---
name: git-workflow-standards
description: Enforce safe local Git practices for the Odin-Lunchtab repository, including feature branches, focused diffs, uv verification, release-sensitive files, and protection of generated or personal data. Use when inspecting history, creating branches, staging, committing, resolving conflicts, or preparing this project for a pull request.
---

# Odin Git Workflow Standards

Apply the global `manage-git-workflows` skill first, then enforce these project rules.

- Confirm `.git` is complete with `git rev-parse` before any Git operation. Do not initialize or
  repair repository metadata without explicit authorization.
- Use `type/short-description` branches, such as `feat/email-rules` or
  `fix/dry-run-spinner`, and merge through a reviewed pull request.
- Never stage source exports, files under `Raw Data` or `Processed Data`, local profiles,
  diagnostic logs, build caches, `.venv`, or user-generated transfer reports.
- Treat `pyproject.toml`, `uv.lock`, PyInstaller specs, installer definitions, build scripts,
  README release instructions, and version metadata as one release-sensitive change set when
  applicable.
- Run commands through `uv`. Before a normal code commit, run focused tests plus:

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check
```

- Add `uv sync --locked`, frozen smoke tests, and installer checks when dependencies, packaging,
  or release inputs change.
- Preserve unrelated work. Require explicit authorization before branch creation, staging,
  committing, history rewriting, or pushing.
