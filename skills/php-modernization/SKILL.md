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

1. **Discover**: `uv run skills/php-modernization/scripts/verify_php_project.py --root . --summary` — returns archetype, tooling, findings, `agent_actions[]`.
2. **Drill**: `... --check PM-XX` for one finding. Use full output only when triaging >3 findings.
3. **Apply**: `uv run skills/php-modernization/scripts/modernize_loop.py --mode dry-run` — review transcript before applying.
4. **References**: load on demand from the table below; do not pre-load.

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
| API Platform edges | `references/api-platform-edges.md` |
| Immutability boundaries | `references/immutability-boundaries.md` |
| Mutation testing | `references/mutation-testing.md` |
| Migration planning | `references/migration-strategies.md` |

## Hard guardrails

- Never apply `readonly` to Doctrine entities or mapped-superclasses (embeddables are a nuanced case, ORM 3.x dependent — see `references/doctrine-modernization-edges.md`).
- Never run Rector without `--dry-run` first.
- Never raise PHPStan level without regenerating + committing the baseline in the same change. Shrink, never delete.
- Never apply blanket `final` to mock targets or extension points without confirmation.
- Never edit `@generated` files or files under `var/cache/`, `vendor/`, `node_modules/`, `.Build/`.

## Tooling baseline

PHPStan ≥9 (10 recommended). PHP-CS-Fixer `@PER-CS`. Rector with version-set matching project PHP. PHPat where layer boundaries exist. `composer audit` on every run. Infection in PR-diff mode.

## Migration checklist

- [ ] `declare(strict_types=1)` everywhere
- [ ] `@PER-CS`, no deprecated aliases
- [ ] PHPStan ≥9 (`treatPhpDocTypesAsCertain: false`); 10 for new projects
- [ ] PHPat for layer boundaries
- [ ] Return + parameter types on all methods
- [ ] DTOs over arrays; backed enums over constants
- [ ] PSR interfaces in type-hints
- [ ] `#[Override]` (8.3+), `#[SensitiveParameter]` (8.2+), typed constants (8.3+)
- [ ] readonly on DTOs/VOs/events only — see `references/immutability-boundaries.md`
- [ ] Property hooks (8.4) for validated mutable state
- [ ] `array_find` / `array_any` / `array_all` over manual loops (8.4)
- [ ] Pipe `|>` for transform pipelines (8.5)

---

> Source: https://github.com/netresearch/php-modernization-skill
