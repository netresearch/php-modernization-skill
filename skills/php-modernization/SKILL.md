---
name: php-modernization
description: "Use when working with ANY PHP modernization task: upgrading PHP 8.1+, adding strict types, configuring PHPStan/Rector/PHP-CS-Fixer, refactoring to enums/DTOs/readonly, improving type safety, or reviewing PHP code quality. Triggers on: PHP upgrade, modernize, type safety, PHPStan, Rector, PHP-CS-Fixer, enum, DTO, readonly, strict_types."
license: "(MIT AND CC-BY-SA-4.0)"
compatibility: "Requires php 8.1+, composer."
metadata:
  version: "1.9.0"
  repository: "https://github.com/netresearch/php-modernization-skill"
  author: "Netresearch DTT GmbH"
allowed-tools:
  - "Bash(php:*)"
  - "Bash(composer:*)"
  - "Read"
  - "Write"
  - "Glob"
  - "Grep"
---

# PHP Modernization Skill

Modernize PHP applications to PHP 8.x with type safety, PSR compliance, and static analysis.

## Expertise Areas

- **PHP 8.x**: Constructor promotion, readonly, enums, match, attributes, union types
- **PSR/PER Compliance**: Active PHP-FIG standards
- **Static Analysis**: PHPStan (level 9+), PHPat, Rector, PHP-CS-Fixer
- **Type Safety**: DTOs/VOs over arrays, generics via PHPDoc

## Reference Documentation

| Topic | Reference File |
|-------|---------------|
| PHP 8.0-8.5 features | `references/php8-features.md` |
| PSR/PER compliance | `references/psr-per-compliance.md` |
| PHPStan levels | `references/phpstan-compliance.md` |
| Static analysis tools | `references/static-analysis-tools.md` |
| PHP-CS-Fixer deprecations | `references/php-cs-fixer-deprecations.md` |
| Type safety, DTOs | `references/type-safety.md` |
| Request DTOs | `references/request-dtos.md` |
| Adapter registry | `references/adapter-registry-pattern.md` |
| Symfony patterns | `references/symfony-patterns.md` |
| TYPO3 PSR patterns | `references/typo3-psr-patterns.md` |
| Migration planning | `references/migration-strategies.md` |

Always run `vendor/bin/php-cs-fixer fix --dry-run 2>&1 | grep -A 20 "Detected deprecations"` to check for deprecated rules.

## Running Scripts

Verify a project: `scripts/verify-php-project.sh /path/to/project`

## Required Tools

| Tool | Requirement |
|------|-------------|
| PHPStan | **Level 9 minimum**, level 10 recommended |
| PHPat | Required for defined architectures |
| Rector | Required for automated modernization |
| PHP-CS-Fixer | Required with `@PER-CS` ruleset |

## Core Rules

- **DTOs required** over arrays for structured data
- **Backed enums required** for fixed value sets (not constants)
- **PSR interfaces** for type-hinting dependencies (PSR-3, PSR-6, PSR-7, PSR-11, PSR-14, PSR-18)

See `references/core-rules.md` for code examples and scoring criteria.

## Migration Checklist

- [ ] `declare(strict_types=1)` in all files
- [ ] PER Coding Style via PHP-CS-Fixer (`@PER-CS`) with no deprecated aliases
- [ ] PHPStan level 9+ (level 10 for new projects)
- [ ] PHPat architecture tests
- [ ] Return types and parameter types on all methods
- [ ] DTOs for data transfer, no array params/returns
- [ ] Backed enums for all status/type values
- [ ] Type-hint against PSR interfaces

---

> **Contributing:** https://github.com/netresearch/php-modernization-skill
