<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Mutation Testing with Infection

Operational guide for Infection (https://infection.github.io/), the de-facto mutation testing framework for PHP. Three modes, configuration, CI integration, and how to read the report.

## Why Mutation Testing for Modernization

Code coverage tells you which lines were executed by the test suite. It does not tell you whether those tests would catch a regression. Mutation testing closes that gap: Infection mutates source code (changes `>` to `>=`, `&&` to `||`, drops a return statement, etc.) and re-runs your tests. If the tests still pass, the mutant **escaped** — meaning your test suite does not actually verify that line's behavior.

This matters for modernization because:

- **Rector batch transforms** rewrite syntax. Coverage stays the same. Without mutation testing, you have no signal that the rewrites preserved semantics.
- **Refactoring to DTOs / readonly / enums** changes data flow. Tests that asserted on the old shape may pass against the new shape without actually checking the new invariants.
- **Adding strict types** can change behavior at boundaries (TypeError instead of silent coercion). Mutation testing catches the cases your tests don't.

When you make a large mechanical change and the test suite stays green, mutation MSI tells you whether that's because the change is safe — or because the tests don't check.

## Three Modes

### Diff Mode (default for PRs)

```bash
vendor/bin/infection \
  --git-diff-base=origin/main \
  --git-diff-lines \
  --with-uncovered \
  --threads=$(nproc) \
  --min-msi=0 \
  --min-covered-msi=0 \
  --logger-json=infection-diff.json
# The gate (escaped and not covered counts, missing log) is in the CI example under CI Integration.
```

Mutates **only** the lines changed in the current branch versus the merge base (Infection runs `git merge-base <base> HEAD` itself; in a shallow clone it falls back to the base ref, so check out the full history). Typical runtime: under a minute on a normal PR. High signal: every escaped mutant maps to code the developer just wrote or touched.

This is the default mode for PR gates. It scales: a 5000-line codebase with a 30-line PR runs in seconds.

**The PR gate is the escaped and not covered count, not an MSI percentage.** Over a handful of mutants one escape moves the score by tens of points, so the thresholds are zeroed (overriding `minMsi`/`minCoveredMsi` from `infection.json5`) and the run fails on any escaped or not covered mutant in the changed lines, read from `stats.escapedCount` and `stats.notCoveredCount` of the JSON log (`--logger-json` needs Infection 0.35.11; on older versions set `logs.json` in the config).

`--with-uncovered` is part of the gate. Without it Infection drops the nodes no test executes before it creates mutants: a method no test calls, added to a tested class, yields 0 mutants and the run passes. With it, those mutants are counted in `notCoveredCount`.

When the diff holds no source line to mutate, Infection prints "Could not find any modified …" or "No source file found for the filter applied …" (a changed file that `source.excludes` drops), exits 0 and writes no log; accept a missing log only then. "No source code from the diff was executed …" also comes with exit 0 and no log, with or without `--with-uncovered`, but it means that no test executed any line of the changed files. A new class without a test produces it, so treat it as a failure. A diff of declarations only (an interface, abstract method signatures, constants) produces the same message, because it has no executable line. Tell the two apart by reading the changed lines: a changed statement inside a function or method body means a test is missing; a diff of signatures and declarations alone is the case the gate cannot judge, and the reviewer confirms it.

The MSI thresholds gate the scheduled full run only. `modernize_loop.py --git-diff-base` applies exactly this rule.

`--git-diff-lines` (rather than `--git-diff-filter`) restricts mutation to the changed *lines*, not entire files. Without it, a one-line change pulls the whole file into mutation scope.

#### Generation scope

State which mutants a diff run creates; it decides the run's size, not only which survivors you read.

- **A change to production code only: `--git-diff-lines`.** Infection keeps a mutant when the line range of the mutated node overlaps a changed line range (Infection 0.32.7 and 0.35.12). `--git-diff-filter=AM` selects changed *files* and mutates every line in them: in a measured one-line edit of production code that was 25 mutants instead of 1. The two options exclude each other.
- **A one-line edit must not mutate an unrelated expression in the same file.** If the edit turns `if ($total > $threshold)` into `>=`, and the same method computes `$bonus = $rate * 2` on an unchanged line, a line-limited run mutates the `if` line only. A run that also mutates `* 2` was not limited to the change.
- **Widen the selection where the effect of a change does not sit in changed source lines:** a test-only change (no source line changed, so `--git-diff-lines` generates nothing; mutate the classes the changed tests cover, or leave them to the full run and say so), a shared fixture, base test case or PHPUnit/Infection configuration (run the affected directories or the full set), and an edit to one line of a multiline expression (only mutants whose own node touches a changed line are kept; widen to that file).
- **Count the generated mutants, not only the relevant survivors.** A file-wide run with no survivor in the changed lines reads like a passing line-limited run. Compare `stats.totalMutantsCount` in the JSON log with what the changed lines can produce.

### Full Mode (scheduled, not per-PR)

```bash
vendor/bin/infection --threads=$(nproc) --min-msi=70
```

Mutates the entire codebase. Runtime ranges from minutes (small libraries) to hours (large applications). Run nightly on `main`, on release branches, or on a manual trigger — never on every PR.

Use full mode to track MSI trend over time. Diff mode keeps PRs fast; full mode keeps the codebase honest.

### First-Time / Legacy Baseline

The first run on a legacy codebase is ugly. Realistic numbers: 30–50% MSI, hundreds of escaped mutants. Don't gate on this immediately.

Strategy:
1. Run full mode once. Record the MSI as the baseline.
2. Set `minCoveredMsi` slightly below the current value (e.g., baseline 42% → gate at 40%); in a default run it is the threshold that binds.
3. Exclude generated code, debug helpers, and anything you genuinely don't want mutated.
4. Each sprint, ratchet `minCoveredMsi` upward.

```bash
# Initial baseline run
vendor/bin/infection \
  --initial-tests-php-options="-d memory_limit=2G" \
  --threads=$(nproc)
```

Since Infection 0.31 uncovered code is not mutated by default; `--only-covered` was removed then, and Infection 0.35 rejects it as an unknown option. The default run skips mutants in lines no test executes, which for a legacy baseline gives a cleaner picture of what the *existing* tests check semantically. In a full run, add `--with-uncovered` only to measure how much code no test reaches; the PR diff run always passes it (see Diff Mode).

## Configuration

Sample `infection.json5`:

```json5
{
  $schema: "vendor/infection/infection/resources/schema.json",
  source: {
    directories: ["src"],
    excludes: [
      "DependencyInjection",
      "Migrations",
      "**/*Generated*"
    ]
  },
  timeout: 10,
  logs: {
    text: "infection.log",
    json: "infection.json",
    github: true,
    stryker: { badge: "main" }
  },
  mutators: {
    "@default": true,
    "Throw_": false
  },
  minCoveredMsi: 80,
  testFramework: "phpunit",
  testFrameworkOptions: "--testsuite=unit"
}
```

Key options:

- **`source.directories`** — what gets mutated. Usually just `src`. Don't include `tests`.
- **`source.excludes`** — patterns relative to each source directory. Common excludes: framework boilerplate (`DependencyInjection`), migrations, generated code, fixtures.
- **`timeout`** — per-mutant test run timeout in seconds. If your test suite has slow integration tests, raise this; otherwise keep it tight to avoid hanging on infinite-loop mutants.
- **`mutators`** — `@default` enables the standard set. Disable specific mutators that produce noise (`Throw_` mutates throw statements; often noisy in defensive code).
- **`minMsi`** vs **`minCoveredMsi`** — see below.
- **`testFrameworkOptions`** — passed through to PHPUnit. Restricting to `--testsuite=unit` is usually right; functional tests are slow and flaky under mutation pressure.

### `minMsi` vs `minCoveredMsi`

- **MSI (Mutation Score Indicator)**: killed mutants ÷ total mutants generated. It includes mutants in uncovered code only when the run passes `--with-uncovered` (Infection 0.31 and later); without the flag MSI equals Covered MSI, and `minMsi` and `minCoveredMsi` compare the same number.
- **Covered MSI**: killed mutants ÷ mutants in covered code. The pure measure of your test suite's mutation-killing ability.

The MSI thresholds gate the **scheduled full run** only; a PR diff run fails on any escaped or not covered mutant in the changed lines instead (see Diff Mode). In a default full run both keys compare the same number; `minMsi` differs from `minCoveredMsi` only with `--with-uncovered`.

A pair such as `minCoveredMsi: 80` and `minMsi: 70` only means something in a `--with-uncovered` full run, where the 10-point gap absorbs the uncovered helpers. In a default run the two compare the same number and `minCoveredMsi` alone binds; set only that one there (as the legacy ratchet above does).

## CI Integration

GitHub Actions, diff mode on PRs:

```yaml
- name: Mutation testing (PR diff)
  if: github.event_name == 'pull_request'
  run: |
    set -o pipefail
    vendor/bin/infection \
      --git-diff-base="origin/${BASE_REF}" \
      --git-diff-lines \
      --with-uncovered \
      --threads=$(nproc) \
      --min-msi=0 \
      --min-covered-msi=0 \
      --logger-json=infection-diff.json \
      --logger-github | tee infection-diff.out
    if [ ! -f infection-diff.json ]; then
      # No test executed a line of the changed files: a missing test, or a
      # diff of declarations only (see Diff Mode)
      if grep -q 'No source code from the diff was executed' infection-diff.out; then
        echo "::error::no test executed any line of the changed files"
        exit 1
      fi
      # No source line in the diff: Infection writes no log
      grep -qE 'Could not find any modified|No source file found for the filter applied' infection-diff.out
      exit
    fi
    # -e: a missing field is an error, not a zero
    escaped=$(jq -e '.stats.escapedCount' infection-diff.json)
    not_covered=$(jq -e '.stats.notCoveredCount' infection-diff.json)
    if [ "$escaped" != 0 ] || [ "$not_covered" != 0 ]; then
      echo "::error::$escaped escaped and $not_covered not covered mutant(s) in the changed lines"
      exit 1
    fi
  env:
    BASE_REF: ${{ github.base_ref }}
    INFECTION_BADGE_API_KEY: ${{ secrets.STRYKER_DASHBOARD_API_KEY }}
```

`--logger-github` annotates the PR diff with escaped mutants directly on the changed lines. The developer sees the missed test on the file view, not buried in the run log.

For nightly full mode, schedule a separate workflow:

```yaml
on:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:

jobs:
  mutation-full:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with: { fetch-depth: 0 }
      # ... PHP/Composer setup ...
      - run: vendor/bin/infection --threads=$(nproc) --min-msi=70
```

Don't run full mode on PRs — it will routinely time out, and the signal-to-cost ratio is bad.

## Common False-Positive Sources

Not every escaped mutant is a real test gap. Recognize the noise:

- **Log messages** — mutating the message string of a log call rarely affects behavior. Exclude logger calls or exclude `String_` mutators near them.
- **Debug-only branches** — code wrapped in `if ($this->debug)` won't be exercised in tests. Either cover it or exclude.
- **Defensive coding past the type system** — a `null` check on a `private int` property that is always initialized is unreachable. Mutation will detect this; the right fix is to remove the check, not to add a test.
- **Generated code** — DI containers, ORM proxies, hand-rolled but mechanically generated lookup tables. Always exclude.
- **Equivalent mutants** — a mutation that produces semantically identical code (e.g., changing the order of two commutative operations). Infection's mutator set tries to avoid these but a few slip through. Mark them with `@infection-ignore-all` or specific mutator annotations on the line.

```php
/** @infection-ignore-all */
private function logForDevelopers(string $msg): void
{
    $this->logger->debug($msg);
}
```

## Reading the Report

Infection produces three views:

1. **Console summary** — `Mutation Score Indicator (MSI): 76%` and counts of killed / escaped / errored / timed-out / not covered mutants.
2. **Text log** (`infection.log`) — one entry per escaped mutant, with a unified diff of the mutation and the file:line.
3. **JSON log** (`infection.json`) — same data, machine-readable.

A typical entry:

```
1) src/Order/Pricing.php:42    [M] Greater
--- Original
+++ New
@@ @@
-        if ($cart->subtotal() > $threshold) {
+        if ($cart->subtotal() >= $threshold) {
             return $this->discounted($cart);
         }
```

Read this as: "I changed `>` to `>=`. Your tests passed anyway. Therefore, your tests don't distinguish behavior at the threshold boundary."

Two interpretations:

- **The code is buggy** (off-by-one at the boundary, but no test catches it). Add a boundary test, possibly fix the operator.
- **The test doesn't check this case** (the threshold boundary doesn't matter for current behavior). Add a test that asserts the exact boundary, even if just to document the chosen semantics.

In both cases the action is the same: write the test. The mutant is killed and the suite is sharper.

## When Not to Gate on Infection

- **First week after introduction.** Let the team see the report before failing builds on it. Gate informationally first, enforced second.
- **Legacy code without a baseline.** Run, record, ratchet. Don't fail the first PR that touches a 10-year-old controller.
- **Very small modules.** A file with 3 mutants is unstable: one false positive moves MSI from 100% to 67%. Apply Infection at the package or directory level, not per-file.
- **Tests that are themselves under refactor.** Mutation testing on a moving test suite produces noise. Land the test changes first.
- **Integration-heavy code.** If 80% of your behavior lives in HTTP/database integration, unit-level mutation testing under-reports. Either accept that coverage is limited, or invest in a faster integration harness.

## Summary

Diff mode for PRs (fast, high signal), failing on any escaped or not covered mutant in the changed lines. Full mode nightly (trend tracking) with the MSI gate. Baseline first on legacy, ratchet up. Use `--logger-github` for actionable PR feedback. Treat escaped mutants as test gaps, not bugs — the fix is almost always a sharper test, occasionally a code fix when the mutant reveals an actual edge case.
