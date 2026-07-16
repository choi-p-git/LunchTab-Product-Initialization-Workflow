---
name: testing-standards
description: Enforce repository testing standards for planning coverage, writing reliable tests, selecting focused or broad test scopes, isolating state, diagnosing failures, and reporting results. Use when changing behavior, fixing bugs, adding or reviewing tests, modifying fixtures or test configuration, choosing regression coverage, or deciding how much verification a code change requires.
---

# Testing Standards

Test observable behavior at the narrowest useful scope, then expand according to the dependencies and risks affected by the change. Adapt the workflow to the repository's size, architecture, and available tooling.

## Inspect the test system

Before planning or running tests, inspect:

- test configuration and runner commands;
- shared fixtures, helpers, setup, and teardown;
- existing tests for the affected code and its consumers;
- repository documentation for test commands, markers, and scope selectors;
- files, processes, services, devices, data, or environment state used by tests.

Reuse established fixtures, factories, naming, and assertion patterns. Do not invent markers or command options that the repository has not configured.

## Classify the change

Classify coverage using dimensions that fit the repository:

1. **Code area**: the function, module, command, component, feature, or subsystem affected.
2. **Observable contract**: the input, output, state change, file, message, error, or user-visible result that must remain correct.
3. **Dependency boundary**:
   - isolated logic with no external state;
   - collaboration between local modules or components;
   - interaction with files, databases, processes, networks, devices, frameworks, or external services;
   - end-to-end behavior across the application's normal entry point.
4. **Risk**: likelihood and consequence of failure, including data loss, security, compatibility, performance, packaging, or operational impact.

Use repository markers or selectors when they express these dimensions. Recipe Collection's module/relation scopes are one useful example, not a required taxonomy.

## Plan coverage

For each behavior change or bug fix:

1. Identify the observable contract being changed.
2. Identify the smallest code boundary that owns that contract.
3. Add consumer or integration coverage when behavior crosses a dependency boundary.
4. Cover the primary success path.
5. Cover relevant invalid input, empty state, limits, errors, and recovery paths.
6. Add a regression test that fails before a bug fix and passes afterward when practical.
7. Preserve unrelated behavior rather than rewriting broad snapshots or fixtures.

Use this routing guide:

| Change | Minimum coverage | Expand when |
| --- | --- | --- |
| Pure transformation or calculation | Direct focused test | Consumers depend on formatting, precision, or edge behavior |
| Module or component behavior | Tests through its public interface | Other components depend on the changed contract |
| File, process, database, device, or network interaction | Isolated boundary test using safe test resources | Real integration behavior differs materially from a substitute |
| Command, UI, API, or other entry point | Focused entry-point test | Internal behavior or downstream state also changed |
| Shared fixture, configuration, dependency, or build setting | Direct configuration test and affected code areas | The impact may be repository-wide |
| Workflow spanning components | Focused integration or end-to-end path | Failure is critical, destructive, or difficult to detect |

Do not duplicate the same detailed assertions at every boundary. Test combinations where their rules are owned, and use broader tests to prove wiring and externally visible contracts.

## Write reliable tests

1. Name tests after observable behavior and conditions, not implementation details.
2. Keep each test focused on one contract, even when multiple assertions describe that contract.
3. Prefer public interfaces over private helpers unless the helper itself owns a complex pure contract.
4. Use explicit inputs and expected outputs.
5. Keep tests deterministic:
   - control time, randomness, identifiers, and environment values;
   - avoid network and production services unless the test is explicitly an integration test;
   - avoid dependence on execution order or pre-existing local data.
6. Isolate mutable state with temporary resources, test doubles, dependency injection, monkeypatching, or repository fixtures.
7. Clean generated artifacts without deleting unrelated files.
8. Assert meaningful outputs, state changes, files, messages, errors, or interactions instead of incidental implementation details.

Apply technology-specific checks only when relevant:

- For commands, verify exit behavior, output, errors, arguments, and generated artifacts.
- For files or persistence, use disposable data and verify creation, updates, failure handling, and compatibility.
- For APIs or user interfaces, verify the public response and resulting state through supported test interfaces.
- For integrations, replace external systems when testing local behavior and use real integration tests only when their added fidelity is necessary.

## Select and run tests

Use the repository's configured runner. For Python/uv projects, follow the Python/uv standards. Run focused tests first, for example:

```powershell
uv run pytest -q path/to/relevant_test.py
```

When repository-specific selectors exist, combine them with relevant test files. Recipe Collection, for example, supports:

```powershell
uv run pytest -q tests/test_inventory_service.py tests/test_routes.py --module-scope inventory --relation-scope service,api
```

Escalate in this order:

1. New or changed tests only.
2. The owning code area.
3. Consumers and affected dependency boundaries.
4. Neighboring components that share the changed contract.
5. The full suite when required.

Run the full suite for:

- runtime, dependency, test-runner, plugin, or tooling changes;
- shared fixtures, global hooks, selectors, or test configuration changes;
- shared contracts, public interfaces, build configuration, or cross-cutting infrastructure;
- broad refactors, release checks, explicit regression requests, or uncertain blast radius.

## Diagnose failures

When a test fails:

1. Re-run the smallest failing selection.
2. Determine whether the product code, test expectation, fixture, test isolation, or environment is wrong.
3. Inspect the first meaningful failure rather than treating later cascades as independent defects.
4. Fix product behavior when it violates the intended contract.
5. Change a test expectation only when the intended contract changed.
6. Do not weaken, skip, delete, or broadly mock a failing test merely to make the suite pass.
7. Re-run the focused selection, then the appropriate expanded scope.

If a failure appears flaky, identify and control the nondeterministic input. Do not report a retry-only pass as reliable without describing the instability.

## Complete verification

Report:

- test files added or changed;
- code areas, contracts, and dependency boundaries covered;
- exact commands executed;
- passed, failed, skipped, deselected, or not-run results;
- why the selected scope was sufficient;
- untested behavior, flaky tests, environmental limitations, or remaining risks.

Never claim that tests pass if they were not executed successfully. Distinguish test failures from environment or collection failures.
