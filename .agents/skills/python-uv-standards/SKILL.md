---
name: python-uv-standards
description: Enforce Python and uv project standards for environment setup, Python versions, dependency management, lockfiles, command execution, testing, linting, and reproducible builds. Use when creating or changing Python code, pyproject.toml, uv.lock, .python-version, requirements exports, test configuration, development tooling, packaging, or CI workflows in this repository.
---

# Python and uv Standards

Use `uv` as the project environment, dependency, and command runner. Follow repository-specific commands when they are more precise than the defaults below.

## Inspect the project

Before changing Python code or tooling, inspect:

- `pyproject.toml`;
- `.python-version`;
- `uv.lock`;
- repository workflow documentation;
- configured test, lint, type-check, build, and packaging commands.

Do not assume every Python repository is a packaged library. Preserve the existing application, package, or virtual-project model unless the task requires changing it.

## Manage Python versions

1. Declare supported Python versions with `project.requires-python`.
2. Keep `.python-version` compatible with that declaration and use it as the default local interpreter.
3. Treat a Python-version change as a compatibility change:
   - update both files;
   - regenerate `uv.lock`;
   - sync a clean environment;
   - run the full relevant test and tooling suite.
4. Use `uv python install <version>` when the required interpreter is unavailable.

Do not silently lower or raise the supported Python version merely to resolve a local environment problem.

## Manage dependencies

Use `pyproject.toml` as the dependency source of truth.

- Add runtime dependencies with `uv add <package>`.
- Remove runtime dependencies with `uv remove <package>`.
- Add development tools with `uv add --dev <package>`.
- Remove development tools with `uv remove --dev <package>`.
- Use named dependency groups when tools have a distinct purpose beyond the default `dev` workflow.
- Use environment markers for genuinely platform- or Python-specific dependencies.

Do not use `pip install` or `uv pip install` to make persistent project changes. Do not edit `.venv` directly. For a temporary tool or experiment, use `uvx` or `uv run --with <package>` without adding it to project dependencies.

Keep runtime libraries out of development groups and keep test, lint, formatting, type-check, and build tools out of runtime dependencies unless the application imports them at runtime.

## Maintain the lockfile

1. Commit `uv.lock` for applications and other repositories that require reproducible development, test, build, or deployment environments.
2. Let `uv` create and update the lockfile; never edit it manually.
3. Include `pyproject.toml` and `uv.lock` in the same change whenever dependency metadata changes.
4. Check lockfile consistency with:

   ```powershell
   uv lock --check
   ```

5. Upgrade intentionally:
   - use `uv lock --upgrade-package <package>` for a targeted upgrade;
   - use `uv lock --upgrade` only when a broad dependency refresh is intended.
6. Review dependency and lockfile diffs for unexpected packages, sources, or version changes.

Use `requirements.txt` only when an external tool requires it. Generate it from the lockfile rather than maintaining it independently:

```powershell
uv export --locked --format requirements.txt --output-file requirements.txt
```

Document why a generated requirements export exists and regenerate it whenever its source lockfile changes.

## Create and synchronize environments

- Use `uv sync` for initial setup and to make the editor environment match the project.
- Allow `uv run` to create or update `.venv` during ordinary local work.
- Do not require a separate `uv venv` step unless custom environment creation is specifically needed.
- Keep `.venv/`, Python caches, and tool caches out of version control.
- Use `uv sync --locked` in CI and reproducible build workflows so stale dependency metadata fails instead of rewriting the lockfile.

Prefer a clean sync after Python-version, dependency-source, build-system, or packaging changes.

## Run project commands

Run Python and installed project tools through `uv run`:

```powershell
uv run python path/to/script.py
uv run pytest
uv run ruff check .
```

Use the repository's documented entry point and environment-variable conventions. Do not rely on a manually activated virtual environment when documenting commands.

Use `uv run --locked` in CI or other verification that must not modify `uv.lock`. Avoid `--frozen` for normal validation because it skips checking whether the lockfile matches project metadata.

## Test proportionally

Use the `testing-standards` skill to plan coverage, select architectural layers, choose focused or full suites, write reliable tests, and diagnose failures.

This skill governs how Python test commands run: execute repository pytest commands through `uv run`, and use `uv run --locked` when verification must not update the lockfile.

## Run quality checks

Run only tools declared and configured by the repository. A typical verification sequence is:

```powershell
uv run pytest <focused-selection>
uv run ruff check .
uv run ruff format --check .
```

Run configured type checks, import smoke tests, builds, or packaging checks when relevant. Apply automatic formatting or lint fixes only when authorized by the task, and review their diff.

For dependency or tooling changes, verify at minimum:

```powershell
uv lock --check
uv sync --locked
uv run --locked pytest
```

Use the repository's focused or full pytest command in place of the generic example.

## Complete the task

Report:

- Python, dependency, or tooling files changed;
- `uv` commands executed;
- focused and expanded verification results;
- whether `uv.lock` or generated exports changed;
- compatibility, platform, build, or deployment risks.
