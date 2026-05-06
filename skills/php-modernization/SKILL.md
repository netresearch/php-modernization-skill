---
name: php-modernization
description: "Use when modernizing PHP code: PHP 8.1-8.5 features, PSR/PHP-FIG/PER-CS compliance, PHPStan/Rector/PHP-CS-Fixer/PHPat tooling, DTOs/enums/readonly/property hooks, type safety. Triggers: PHP modernization, type safety, PHPStan, Rector, PHP-CS-Fixer, enum, DTO, readonly, strict_types, property hooks, PHP 8.4, PHP 8.5."
license: "(MIT AND CC-BY-SA-4.0)"
compatibility: "Requires php 8.1+, composer."
metadata:
  version: "1.16.0"
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

Modernize PHP to current standards: PHP 8.1-8.5, PSR/PHP-FIG, PER-CS, PHPStan max, type safety.

## Agent contract

When invoked, follow this decision flow:

1. **Discover state**: Run `uv run skills/php-modernization/scripts/verify_php_project.py --root . --format json --summary` first. This returns archetype, tooling status, top findings, and `agent_actions[]`.
2. **Drill in only when needed**: For a specific finding, run `... --check PM-XX` for full detail. Do not load full `--format json` output unless triaging more than 3 findings.
3. **Apply changes via the orchestrator**: For Rector/PHP-CS-Fixer/PHPStan workflows, run `uv run skills/php-modernization/scripts/modernize_loop.py --mode dry-run`. Review the structured transcript before applying.
4. **Read references on demand**: Use the routing table below. Do not pre-load references.

## Reference routing

| Need | Read |
|---|---|
| PHP 8.0-8.3 baseline | `references/php8-features.md` |
| PHP 8.4 (hooks, asymmetric visibility, lazy objects) | `references/php-8.4.md` |
| PHP 8.5 (pipe, array_first/last, `#[\NoDiscard]`) | `references/php-8.5.md` |
| PSR / PER-CS | `references/psr-per-compliance.md` |
| PHPStan config | `references/phpstan-compliance.md` |
| Static analysis overview | `references/static-analysis-tools.md` |
| PHP-CS-Fixer deprecations | `references/php-cs-fixer-deprecations.md` |
| DTOs / VOs / typed inputs | `references/type-safety.md`, `references/request-dtos.md` |
| Adapter / registry | `references/adapter-registry-pattern.md` |
| Multi-version compat | `references/multi-version-adapters.md` |
| Symfony as PSR exemplar | `references/symfony-patterns.md` |
| Doctrine edges | `references/doctrine-modernization-edges.md` |
| Immutability boundaries | `references/immutability-boundaries.md` |
| Mutation testing | `references/mutation-testing.md` |
| Migration planning | `references/migration-strategies.md` |

## Hard guardrails

- **Never** apply `readonly` to a Doctrine `#[ORM\Entity]`, `#[ORM\Embeddable]`, or `#[ORM\MappedSuperclass]` — see `references/immutability-boundaries.md`.
- **Never** run Rector transforms without `--dry-run` first and reviewing the diff.
- **Never** raise PHPStan level without regenerating + committing the baseline in the same change. Baseline policy is shrink, not delete.
- **Never** apply blanket `final` to test-double targets or framework extension points without confirmation.
- **Never** edit `@generated` files or files under `var/cache/`, `vendor/`, `node_modules/`, `.Build/`.

## Required tooling baseline

PHPStan level 9 min (10/max recommended). PHP-CS-Fixer `@PER-CS`, no deprecated aliases. Rector with version-set matching project PHP. PHPat where layer boundaries exist. `composer audit` on every verify run. Infection in PR-diff mode (recommended).

## Migration checklist (used by the orchestrator)

- [ ] `declare(strict_types=1)` everywhere
- [ ] PER Coding Style (`@PER-CS`), no deprecated aliases
- [ ] PHPStan level 9+ (`treatPhpDocTypesAsCertain: false`); level 10 for new projects
- [ ] PHPat tests for layer boundaries
- [ ] Return + parameter types on all methods
- [ ] DTOs over arrays; backed enums over status constants
- [ ] PSR interfaces in type-hints, not implementations
- [ ] `#[Override]` (8.3+), `#[SensitiveParameter]` (8.2+), typed constants (8.3+)
- [ ] readonly on DTOs/VOs/events only — see `references/immutability-boundaries.md`
- [ ] PHP 8.4 property hooks where mutable state needs validation
- [ ] `array_find` / `array_any` / `array_all` over manual loops (PHP 8.4)
- [ ] Pipe operator `|>` for transform pipelines (PHP 8.5)

---

> Source: https://github.com/netresearch/php-modernization-skill
