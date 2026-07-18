---
name: commit-message-diff
description: Draft accurate, up-to-date commit messages from cumulative Git diffs after several generation, refinement, or coding prompts. Use when the user asks to update, refresh, rewrite, or prepare a commit message; when preparing to commit after multi-turn implementation work; or when the current worktree has a large cumulative diff, especially 500 or more changed lines.
---

# Commit Message Diff

## Overview

Produce a commit message that reflects the complete current Git diff, not only the most recent prompt. Use the repository state as the source of truth and separate the user's unrelated work from the changes being committed.

## Workflow

1. Inspect repository state before drafting:

```bash
git status --short
git diff --stat
git diff --cached --stat
git diff --shortstat
git diff --cached --shortstat
```

2. Review the cumulative changes, including staged and unstaged work. If the diff is large, start with file-level summaries and inspect focused hunks:

```bash
git diff --name-status
git diff --cached --name-status
git diff -- <path>
git diff --cached -- <path>
```

3. Reconcile the diff with the conversation and verification evidence. Include durable outcomes, tests, documentation, workflow changes, and generated artifacts that are intended to be committed. Do not invent results from intent alone.

4. Identify scope boundaries:

- Call out unrelated modified or untracked files that should not shape the commit message.
- Treat ignored/private artifacts according to repository policy.
- If staged content differs from unstaged content, draft for the staged set when the commit is imminent; otherwise draft for the full intended change and state the assumption.
- If the diff mixes unrelated concerns, recommend splitting commits before suggesting a single broad message.

5. Draft a Conventional Commit message:

```text
type(scope): concise summary

- main behavior or artifact change
- supporting implementation, test, or documentation change
- verification or migration note when useful
```

Prefer `feat`, `fix`, `refactor`, `test`, `docs`, `build`, or `chore`. Keep the subject under roughly 72 characters when practical. Use a scope that matches the repository module, workflow, or artifact.

## Diff Reading Guidance

For large diffs, summarize by intent rather than mechanically listing files. Inspect enough representative hunks to understand behavior and risks:

- Entry points and public interfaces.
- Tests and fixtures that define expected behavior.
- Configuration, packaging, or workflow files.
- Generated or output files only when they are intentionally part of the change.

When a file has only formatting or mechanical churn, mention it only if it materially affects the commit's purpose.

## Output

Return the commit message first. Then add concise notes only when useful:

- `Scope assumption`: staged-only, full worktree, or named paths.
- `Excluded`: unrelated files seen but not represented.
- `Verification`: checks that actually passed, failed, or were not run.
