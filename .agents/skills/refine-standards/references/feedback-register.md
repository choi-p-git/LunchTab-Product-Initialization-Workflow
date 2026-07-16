# Skill Feedback Register

Store distilled, repository-relevant evidence for standards refinement. Do not store full prompts, responses, secrets, personal data, or source-code excerpts.

## Entry format

### YYYY-MM-DD - concise deficiency

- Status: pending | resolved | rejected | superseded
- Skill: skill-name
- Class: missing-guidance | ambiguity | overconstraint | underconstraint | conflict | trigger | friction | validation | stale
- Evidence count: 1
- Observation: One or two sentences describing the durable problem.
- Desired behavior: The outcome a refined skill should produce.
- Resolution: Pending, or a concise description of the validated change.

## Active entries

No active entries.

## Resolved decisions

### 2026-06-23 - testing taxonomy overfit web applications

- Status: resolved
- Skill: testing-standards
- Class: overconstraint
- Evidence count: 1
- Observation: The initial testing taxonomy assumed service, API, persistence, and route layers that do not fit every repository.
- Desired behavior: Select detailed tests from observable contracts, code boundaries, dependencies, and risk while keeping framework-specific routes optional.
- Resolution: Replaced the fixed web-layer taxonomy with generic code-area, contract, dependency-boundary, and risk dimensions; retained Recipe Collection selectors as an example.
