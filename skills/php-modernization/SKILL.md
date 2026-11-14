---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
name: php-modernization
description: "Use when modernizing PHP code: PHP 8.1-8.5 features, PSR/PHP-FIG/PER-CS compliance, PHPStan/Rector/PHP-CS-Fixer/PHPat tooling, DTOs/enums/readonly/property hooks, type safety. Triggers: PHP modernization, type safety, PHPStan, Rector, PHP-CS-Fixer, enum, DTO, readonly, strict_types, property hooks, PHP 8.4, PHP 8.5."
license: "(MIT AND CC-BY-SA-4.0)"
compatibility: "Requires uv (runs the scripts on Python 3.11 or later), php 8.1+, composer."
metadata:
  version: "1.24.2"
  repository: "https://github.com/netresearch/php-modernization-skill"
  author: "Netresearch DTT GmbH"
allowed-tools:
  - "Bash(php:*)"
  - "Bash(composer:*)"
  - "Bash(uv:*)"
  - "Bash(vendor/bin/*)"
  - "Bash(.Build/bin/*)"
  - "Read"
  - "Write"
  - "Glob"
  - "Grep"
---

# PHP Modernization

## Agent contract

1. **Discover**: `uv run ${CLAUDE_SKILL_DIR}/scripts/introspect.py` (cheap), or `verify_php_project.py --summary` (full, with `agent_actions[]`). Then read the project's own commands — `composer.json` scripts, `Makefile`, DDEV/Docker wrappers, CI config. They fix the runtime, the config and the paths; use them over a bare `vendor/bin/*` call. Exception: when you must add a flag (`--dry-run`, `--only`, a path), run the command the script wraps with the flag written out, in the same runtime — Composer aliases can drop `--`-forwarded flags.
2. **Drill**: `... --check PM-XX` per finding. Full output when triaging >3.
3. **Use the project's tools, and run them.** Naming a tool is not using it. A check you did not run is reported as not run.

   | Concern | Tool (the one the project has) |
   |---|---|
   | PHP refactoring | Rector (+ TYPO3/Symfony sets) |
   | Fluid, TypoScript, FlexForm/XML, YAML migration | Fractor — not for PHP code |
   | Types, `match` completeness (`match.unhandled`), version floor (`phpVersion`) | PHPStan |
   | Coding standard | PHPCS/PHPCBF **or** PHP-CS-Fixer — whichever is configured |
   | Syntax | `php -l` / the project's lint, under the lowest supported PHP |
   | Behaviour | PHPUnit (the project's suite) |
   | Test strength on the changed lines | Infection, where installed |

4. **Decide what the tools cannot.** Before each change, answer from callers, data flow and tests:
   - Which intent becomes clearer?
   - Which observable behaviour must stay (return values, comparisons, exceptions, stored and external values, public signatures)?
   - Which existing rule or tool makes the change?
   - Which check shows the result is right — and which behaviour test pins the decision?

   The verifier runs mechanical checks only. The `llm_review` checkpoints in `checkpoints.yaml` (enums PM-21, PHP 8 features and `match` PM-22, `readonly` PM-40, …) are yours; a green verifier does not cover them.
5. **Apply in bounded steps**: baseline tests → `modernize_loop.py --mode dry-run` or `rector process <path> --only=<rule> --dry-run` → review the diff against step 4 → apply → formatter → lint, PHPStan, tests → the same dry-run again proposes nothing → commit. Details: `references/migration-strategies.md`.
6. **References**: load on demand; do not pre-load.

## Reference routing

| Need | Read |
|---|---|
| PHP 8.0-8.3 baseline | `references/php8-features.md` |
| PHP 8.4 | `references/php-8.4.md` |
| PHP 8.5 | `references/php-8.5.md` |
| PSR / PER-CS | `references/psr-per-compliance.md` |
| PHPStan config | `references/phpstan-compliance.md` |
| Static analysis | `references/static-analysis-tools.md` |
| PHP-CS-Fixer deprecations | `references/php-cs-fixer-deprecations.md` |
| DTOs / VOs / inputs | `references/type-safety.md`, `references/request-dtos.md` |
| Adapter / registry | `references/adapter-registry-pattern.md` |
| Multi-version compat | `references/multi-version-adapters.md`, `references/composer-package-metadata.md` |
| Symfony patterns | `references/symfony-patterns.md` |
| PSR-15 middleware | `references/psr15-middleware-architecture.md` |
| Doctrine edges | `references/doctrine-modernization-edges.md` |
| API Platform | `references/api-platform-edges.md` |
| Immutability | `references/immutability-boundaries.md` |
| Contracts & invariants | `references/contracts-and-invariants.md` |
| Mutation testing | `references/mutation-testing.md` |
| Lexing PHP as tokens, across versions | `references/lexing-php-across-versions.md` |
| Migration planning | `references/migration-strategies.md` |
| Public API inventory vs consumers | `references/public-api-inventory.md` |
| PHPUnit 12→13, mock vs stub | `references/phpunit-modernization.md` |
| Multi-agent dispatch hazards | `references/multi-agent-pitfalls.md` |
| Reading a PHP config file without running it | `references/reading-php-config-safely.md` |

## Hard guardrails

- Never apply `readonly` to Doctrine entities or mapped-superclasses (embeddables: see `references/doctrine-modernization-edges.md`).
- Never apply Rector (or `modernize_loop.py --mode apply --confirm`) before a `--dry-run` of the same scope and a review of its diff. Rector diffs can change behaviour (loose `switch` → strict `match`, `readonly` over mutable members). Pass `--dry-run` on the Rector command itself (the one the project's script runs, in its runtime), never through a Composer alias with `--`: depending on the configuration the alias drops it.
- Never raise PHPStan level without regenerating + committing the baseline. Shrink, never delete.
- Never apply blanket `final` to mock targets or extension points without confirmation.
- Never edit `@generated` files or files under `var/cache/`, `vendor/`, `node_modules/`, `.Build/`.
- Never `git checkout --` files outside your scope in shared trees — use `git stash` / `git diff`.
- Never trust a warm PHPStan cache after vendor change: `rm -rf /tmp/phpstan-* var/cache/phpstan` first.
- Never mass-substitute `createMock` → `createStub` — promote to `expects(...)->method(...)->with(...)`.

## Migration checklist

- [ ] `declare(strict_types=1)` everywhere
- [ ] `@PER-CS`, no deprecated aliases
- [ ] PHPStan ≥9 (`treatPhpDocTypesAsCertain: false`); 10 for new
- [ ] PHPat for layer boundaries
- [ ] Return + parameter types on all methods
- [ ] DTOs over arrays; backed enums for closed value sets (open sets stay validated strings)
- [ ] PSR interfaces in type-hints
- [ ] `#[Override]` (8.3+), `#[SensitiveParameter]` (8.2+), typed constants (8.3+)
- [ ] readonly on DTOs/VOs/events only
- [ ] Property hooks (8.4); `array_find/any/all` (8.4); pipe `|>` (8.5)
- [ ] PHPUnit 12+: stubs use `createStub`, mocks `createMock` + `expects` (no `self::any()` in 13)
- [ ] Rector `withComposerBased(symfony: true)` (per-version `SymfonySetList::SYMFONY_*` are `@deprecated`)
