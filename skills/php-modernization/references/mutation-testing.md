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
  --threads=$(nproc) \
  --min-msi=80
```

Mutates **only** the lines changed in the current branch versus the base. Typical runtime: under a minute on a normal PR. High signal: every escaped mutant maps to code the developer just wrote or touched.

This is the default mode for PR gates. It scales: a 5000-line codebase with a 30-line PR runs in seconds.

`--git-diff-lines` (rather than `--git-diff-filter`) restricts mutation to the changed *lines*, not entire files. Without it, a one-line change pulls the whole file into mutation scope.

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
2. Set `minMsi` slightly below the current value (e.g., baseline 42% → gate at 40%).
3. Exclude generated code, debug helpers, and anything you genuinely don't want mutated.
4. Each sprint, ratchet `minMsi` upward.

```bash
# Initial baseline run
vendor/bin/infection \
  --initial-tests-php-options="-d memory_limit=2G" \
  --threads=$(nproc) \
  --only-covered
```

`--only-covered` skips mutating uncovered code (the report would be misleading if you can't kill mutants in lines no test executes). For a legacy baseline, this gives you a cleaner picture of what your *existing* tests cover semantically.

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
  minMsi: 70,
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

- **MSI (Mutation Score Indicator)**: killed mutants ÷ total mutants generated. Includes mutants in uncovered code (which can never be killed by definition, so they always escape).
- **Covered MSI**: killed mutants ÷ mutants in covered code. The pure measure of your test suite's mutation-killing ability.

Gate on **`minCoveredMsi`** for PR diffs (you want the new code's tests to be sharp). Gate on **`minMsi`** for full runs (you also want overall coverage to grow).

A common pair: `minCoveredMsi: 80` and `minMsi: 70`. The 10-point gap absorbs the "we have a few uncovered helpers" reality without letting the suite degrade.

## CI Integration

GitHub Actions, diff mode on PRs:

```yaml
- name: Mutation testing (PR diff)
  if: github.event_name == 'pull_request'
  run: |
    vendor/bin/infection \
      --git-diff-base=origin/${{ github.base_ref }} \
      --git-diff-lines \
      --threads=$(nproc) \
      --min-msi=80 \
      --logger-github
  env:
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

Diff mode for PRs (fast, high signal). Full mode nightly (trend tracking). Baseline first on legacy, ratchet up. Gate on `minCoveredMsi` for PRs, on `minMsi` for full runs. Use `--logger-github` for actionable PR feedback. Treat escaped mutants as test gaps, not bugs — the fix is almost always a sharper test, occasionally a code fix when the mutant reveals an actual edge case.
