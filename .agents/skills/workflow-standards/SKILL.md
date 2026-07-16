---
name: workflow-standards
description: Enforce repository workflow standards for analysis, coding, refactoring, debugging, testing, and documentation tasks. Use when inspecting or changing repository files, verifying behavior, or preparing a completion summary.
---

# Workflow Standards

Keep the workflow proportional to the task. Use a brief plan for small, low-risk changes and a more explicit plan for broad, risky, or multi-step work.

## Begin the task

1. Inspect the relevant files, configuration, tests, and repository state.
2. Preserve unrelated existing changes and work around them when possible.
3. Determine whether the request is analysis-only or authorizes file changes.
4. For implementation work, state:
   - the intended outcome;
   - the files likely to change;
   - the planned verification.
5. Update the plan when discoveries materially change the scope or approach.

Do not modify files for analysis, review, diagnosis, or status requests unless the user also asks for changes.

## Make changes

1. Follow all applicable repository-specific skills and conventions.
2. Keep changes focused on the requested outcome.
3. Prefer existing project patterns over introducing unnecessary abstractions.
4. Add or update tests when behavior changes and practical coverage is available.
5. Update documentation when behavior, interfaces, setup, or workflows change.
6. Do not overwrite unrelated user changes.
7. Do not commit, push, or use destructive Git operations unless explicitly authorized.

## Private analysis artifacts

Treat business-analysis skills and artifacts as proprietary/private by default.

- Keep `.agents/skills/business-analysis/`, `business analysis/`, and `business-analysis/`
  ignored unless the user explicitly asks to publish or track them.
- Do not stage business-analysis skill files or generated business-analysis artifacts during normal
  workflow, feature, documentation, or release commits.
- If business-analysis content is useful for the repository, distill the shareable conclusions into
  non-private docs or configuration instead of committing the source skill/artifact package.

## Verify the result

1. Review the final diff for correctness, scope, and unintended changes.
2. Run the narrowest relevant checks first.
3. Expand verification when the change affects shared or high-risk behavior.
4. Report each relevant command and whether it passed or failed.
5. If verification cannot be run, explain why and identify the remaining uncertainty.
6. Never claim a check passed unless it was executed successfully.

Verification may include targeted tests, broader test suites, linting, formatting, type checks, builds, imports, or focused manual checks according to the change.

## Complete the task

Lead with the outcome, then report:

- files changed and their purpose;
- verification performed and results;
- unresolved issues or risks, or state that none were identified.

When files changed, suggest a Conventional Commit message unless the user asks not to:

```text
type(scope): short description

- concise summary of the main change
- concise summary of supporting work
```

Choose the type that best matches the work, such as `feat`, `fix`, `refactor`, `test`, `docs`, `build`, or `chore`. Keep the scope concise and repository-relevant.

## Refine repository standards

At task completion, briefly evaluate whether the prompt, result, user feedback, retries, or verification exposed a durable deficiency in an applicable repository skill.

- Use `refine-standards` when the user explicitly requests a standards change, a serious correctness or safety gap appears, repository guidance is contradicted, or repeated evidence suggests a durable problem.
- Record weaker evidence for later corroboration rather than rewriting a skill after every task.
- Do nothing when the issue was task-specific, environmental, already covered by the skill, or caused by not following it.

Before concluding, confirm that each applicable item is complete:

- [ ] Requested outcome delivered
- [ ] Unrelated existing changes preserved
- [ ] Relevant behavior verified
- [ ] Tests or checks executed, or omission explained
- [ ] Documentation updated when required
- [ ] Remaining risks reported
- [ ] Commit message suggested when files changed
- [ ] Durable skill deficiencies refined or recorded when evidence warranted
