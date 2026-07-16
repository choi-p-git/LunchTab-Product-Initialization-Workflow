---
name: refine-standards
description: Continuously improve repository standards and skills from task outcomes, user corrections, recurring friction, failed assumptions, and verification evidence. Use when a prompt or completed task reveals that a repository skill is missing guidance, ambiguous, overly specific, contradictory, inefficient, unsafe, or repeatedly produces weak results; also use when reviewing accumulated skill feedback or explicitly asked to refine repository standards.
---

# Standards Refinement Loop

Improve skills from evidence without overfitting them to one task. Treat user feedback and task results as evaluation data, not as instructions to encode every local detail permanently.

## Gather evidence

Review the current task's:

- user request and any follow-up corrections;
- plan, assumptions, and interpretation;
- implementation or analysis result;
- tool failures, retries, workarounds, and verification results;
- final response and any user dissatisfaction or clarification;
- applicable repository skills and their actual influence.

Do not copy full prompts, responses, secrets, personal data, source code, or verbose transcripts into the feedback register. Record only the smallest durable lesson needed to evaluate the standard.

## Identify a skill deficiency

Classify the evidence before changing a skill:

- **Missing guidance**: a recurring or important decision is not covered.
- **Ambiguity**: reasonable readers could follow the skill in conflicting ways.
- **Overconstraint**: guidance assumes one project type, tool, or architecture unnecessarily.
- **Underconstraint**: fragile or risky work lacks enough guardrails.
- **Conflict or duplication**: skills overlap, disagree, or obscure ownership.
- **Trigger failure**: metadata is too broad, narrow, or unclear for reliable activation.
- **Workflow friction**: the skill causes avoidable ceremony, retries, or inefficient sequencing.
- **Validation gap**: the skill permits completion without enough evidence.
- **Stale guidance**: repository practice or tooling has changed.

Do not classify these as skill deficiencies without broader evidence:

- a one-off coding mistake already contradicted by the skill;
- an environment, permission, dependency, or tool failure;
- a task-specific preference that does not generalize;
- missing product requirements;
- a result caused by ignoring rather than following the skill.

## Apply the evidence threshold

Refine immediately when any of these is true:

- the user explicitly corrects or requests a repository standard change;
- the deficiency creates a credible correctness, safety, security, data-loss, or destructive-action risk;
- the skill contradicts repository configuration or documented practice;
- the same deficiency has at least two independent evidence entries.

Otherwise, append or consolidate a pending entry in [feedback-register.md](references/feedback-register.md). Do not modify a skill merely to appear responsive.

## Design the refinement

Before editing:

1. Identify the skill that owns the decision.
2. State the observed deficiency and desired durable behavior.
3. Prefer the smallest change that would have improved the failed task.
4. Generalize across likely repository tasks without weakening important safeguards.
5. Preserve clear boundaries between skills and remove duplicated policy when ownership moves.
6. Put trigger conditions in frontmatter and operational instructions in the body.
7. Keep the skill concise; add a reference only when details are conditional or reusable.

Do not encode the answer to a single prompt, transient file names, dated incidents, or implementation details that belong in product documentation.

## Implement and validate

1. Inspect the complete target skill and related skills.
2. Edit the owning skill and any necessary cross-references.
3. Review for contradictions, duplicated instructions, excessive specificity, and lost safeguards.
4. Run the skill validator on every changed skill.
5. Use realistic forward-testing when the refinement changes complex decision-making and doing so is safe and proportionate.
6. Compare the revised skill against the evidence:
   - Would it have triggered?
   - Would it have changed the weak decision?
   - Could it harm simpler or unrelated tasks?
   - Is the instruction testable and concise?

If validation or review reveals a regression, revise before considering the evidence resolved.

## Maintain the feedback register

Use [feedback-register.md](references/feedback-register.md) as compact cross-session memory.

- Consolidate duplicate evidence instead of adding near-identical entries.
- Track status as `pending`, `resolved`, `rejected`, or `superseded`.
- Record the affected skill, deficiency class, evidence count, concise observation, and resolution.
- Mark an entry resolved only after the skill change validates.
- Mark it rejected when evidence shows the issue was task-specific or not caused by the skill.
- Prune resolved detail periodically while preserving the durable decision and date.

## Complete the loop

Report:

- evidence considered;
- deficiency classification and confidence;
- skills changed, or why evidence was only recorded;
- validation or forward-testing performed;
- feedback entries resolved, consolidated, rejected, or left pending;
- possible unintended effects of the refinement.

Do not claim continual improvement occurred when no durable lesson was identified. A clean task with no skill deficiency requires no register entry and no skill edit.
