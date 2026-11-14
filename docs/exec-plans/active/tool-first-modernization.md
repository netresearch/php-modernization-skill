<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Tool-first modernization with explicit judgement

Status: active. Base: `1bfccd5` (version 1.24.2).

## Goal

The skill makes the agent do two things, and each one is checked on its own:

1. **Use the project's own tools.** The agent finds the commands and tools the
   project already has, runs them, works through their findings and runs them
   again after a change. A check it did not run is reported as not run.
2. **Decide what the tools cannot decide.** Whether five status strings are
   one closed set of values, whether an object may be immutable, whether a
   `default` is a contract or hides a missing case: the agent answers these
   from callers, data flow and tests, and pins each answer with a behaviour
   test where one can be written.

No own PHP analysis or refactoring engine is built. A new rule, if one is ever
needed, belongs in the tool that owns the concern (a Rector rule, a PHPCS
sniff, a PHPStan rule) and upstream where it is generally useful.

## Measured before planning

Measured in a scratch Composer project with rector/rector 2.8.4,
phpstan/phpstan 2.3.5, squizlabs/php_codesniffer 4.0.4,
phpcompatibility/php-compatibility 10.0.0-alpha2, a9f/typo3-fractor 1.1.0 and
phpunit/phpunit 13.4.7, PHP 8.5.12.

| Claim | Result |
|---|---|
| `ChangeSwitchToMatchRector`, `ReadOnlyPropertyRector`, `ReadOnlyClassRector`, the MyCLabs and Spatie enum rules exist | Present in `rules/Php80`, `Php81`, `Php82` |
| `rector process --only=<FQCN>` exists | Present; repeatable |
| `ChangeSwitchToMatchRector` keeps behaviour | **No.** On a parameter with no type and no docblock, `switch ($code) { case 200: … }` became `match ($code) { 200 => … }`. `switch` compares with `==`, `match` with `===`, so the input `"200"` now reaches `default`. With `@param int\|string $code` Rector left the `switch` alone. |
| `ReadOnlyClassRector` is safe on value objects | **No.** A class holding a mutable `\DateTime` became `final readonly class`; the object is still mutable through the getter. |
| Rector dry-run exit codes | `0` no change, `2` changes proposed. The orchestrator reports `2` as a failure. |
| PHPStan reports a missing enum case in `match` | Yes, identifier `match.unhandled` |
| PHPStan catches `readonly class` on a PHP 8.1 floor | Yes, with `phpVersion: 80100` ("Readonly classes are supported only on PHP 8.2 and later."). `php -l` on PHP 8.5 does not. |
| PHPCompatibility as the version check | The only release for PHPCS 4 is `10.0.0-alpha2` (2025-11-28); the last stable, 9.3.5, dates from 2019 and needs PHPCS 3. Use it where the project already has it; otherwise PHPStan `phpVersion` plus a lint under the floor version. |
| PHPCS / PHPCBF exit codes (PHPCS 4) | `phpcs`: `0` clean, `1` only fixable findings, `2` findings that need a human. `phpcbf`: `0` when it fixed everything. |
| Fractor | Package `a9f/typo3-fractor`; handles Fluid, TypoScript, XML/FlexForms, XLIFF, YAML, `.htaccess`. Not for PHP code. |

Measured in the repository at `1bfccd5`:

- `introspect.py` detects PHPStan, Rector, PHP-CS-Fixer, PHPat, Infection and
  Psalm. It does not detect PHPCS/PHPCBF, Fractor, a linter, PHPUnit, Composer
  scripts or the source directories.
- The verifier fails PM-04 and PM-05 (severity `error`) on a project that uses
  PHPCS instead of PHP-CS-Fixer.
- `verify_php_project.py --check PM-21` prints an empty `checks[]` with the
  summary of the whole project and its exit code. PM-21 is an `llm_review`
  checkpoint; the verifier runs 14 of the mechanical checkpoints and none of
  the review checkpoints, and the report does not say so.
- A failing PHPStan run in `tool_runs[]` does not change `summary.status`.
- `modernize_loop.py` runs PHP-CS-Fixer before Rector, has no lint and no
  PHPUnit step, and knows no PHPCS. The order dates from the commit that
  introduced the orchestrator (`10118ee`); no later commit argues for it.
- `SKILL.md` says "Never run Rector without `--dry-run`" while the
  orchestrator offers `--mode apply --confirm`; `AGENTS.md` and `README.md`
  say "without `--dry-run` first".
- `references/php8-features.md` shows a `match` over `SecretPlacement` that
  handles 3 of 7 cases under the comment "match() ensures all cases are
  handled!" — it throws `UnhandledMatchError` for the other four.
- The PM-20, PM-21 and PM-32 prompts tell the reviewer to look in `Classes/`
  only.
- `evals/run-ab-test.sh` records output size and duration only. Both arms pass
  `--disable-slash-commands`; with that flag the init event lists 0 skills in
  either arm (Claude Code 2.1.325), so neither arm has the skill to use. The shared
  runner in skill-repo-skill runs with `--tools ""` and supplies the
  `SKILL.md` text only, so neither can show that an agent produces correct
  PHP.

## Changes to the original plan

- **PHPCompatibility is optional**, for the reason in the table. The version
  floor is checked with PHPStan `phpVersion` and a lint under the floor
  runtime.
- **Rector is a proposal, never a verdict.** Two of the three named rules
  changed behaviour in the probe. The `match` and `readonly` checkpoints
  therefore review Rector's diff, not only hand-written code.
- **The report keeps its exit-code contract.** Review coverage is added as new
  fields (`review_coverage`, per-checkpoint `not_reviewed`); a CI job built on
  the shipped template sees the same exit codes as before. An unknown
  `--check` id exits 2.
- **"Dry-run changes nothing" is scoped.** The orchestrator writes its reports
  to `.build/php-modernization/`, and the tools write caches. The criterion is:
  no tracked file and no lock file changes, checked with
  `git status --porcelain`.
- **Eval case projects live in `evals/cases/`**, not in `fixtures/`, because
  `scripts/test_fixtures.py` treats every `fixtures/*` directory as a verifier
  golden snapshot.
- **No custom workflow file.** Skill repositories delegate CI to the shared
  reusable workflows, so the case self-test runs as a Python test that CI
  already executes.

## Work packages

Each package is one pull request from `main`.

1. **Judgement rules and corrected examples** (content only):
   `SKILL.md` tool-first workflow and the four questions per change,
   corrected Rector guardrail in every file that states it, PM-20/21/22/32/40
   prompts, `php8-features.md` (`SecretPlacement`, `switch` → `match`
   comparison semantics), `immutability-boundaries.md` (mutable members),
   `migration-strategies.md` (one bounded change at a time), this plan.
2. **Project tools in the profile, the verifier and the orchestrator**:
   detection of PHPCS/PHPCBF, Fractor, linter, PHPUnit, Composer scripts and
   source directories; PM-04/PM-05 accept a PHPCS project; review coverage in
   the report; unknown `--check` exits 2; orchestrator order Rector →
   formatter → lint → PHPStan → PHPUnit → Infection, Rector exit `2` reported
   as `changes`, scope and rule pass-through.
3. **Executable eval cases**: eight case projects with an acceptance suite, a
   known-good and a known-bad solution each; a checker that proves good
   passes and bad fails at the named check; the A/B runner extended to agent
   runs in isolated copies of a case.

## Acceptance

- A PHPCS project gets no PM-04/PM-05 failure for a missing PHP-CS-Fixer
  config.
- `--check PM-21` reports the checkpoint as `not_reviewed`, and an unknown id
  exits 2.
- Orchestrator dry-run leaves `git status --porcelain` of a case project
  empty apart from `.build/`.
- Every known-bad solution fails at its named check and at no build step;
  every known-good solution passes all checks.
- Agent eval results name model, skill commit, tools used and the check
  results per arm; a run where the "with skill" arm did not load the skill is
  invalid.
