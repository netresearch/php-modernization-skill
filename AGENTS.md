# Agent Guide — php-modernization-skill

## Repo Structure

```
.
├── skills/php-modernization/
│   ├── SKILL.md                        # Main skill definition
│   ├── checkpoints.yaml                # Evaluation checkpoints
│   ├── references/                     # Detailed reference docs
│   │   ├── php8-features.md            # PHP 8.0-8.5 feature patterns
│   │   ├── static-analysis-tools.md    # PHPStan, PHPat, Rector, PHP-CS-Fixer
│   │   ├── psr-per-compliance.md       # Active PSR and PER standards
│   │   ├── phpstan-compliance.md       # PHPStan level configuration
│   │   ├── type-safety.md              # Type system strategies
│   │   ├── request-dtos.md             # DTO patterns and validation
│   │   ├── adapter-registry-pattern.md # Adapter registry for external services
│   │   ├── symfony-patterns.md         # Modern Symfony architecture
│   │   ├── migration-strategies.md     # Version upgrade planning
│   │   └── core-rules.md              # Core modernization rules
│   └── scripts/
│       └── verify-php-project.sh       # PHP project verification
├── evals/evals.json                    # Skill evaluation suite
├── Build/Scripts/                      # Build scripts
├── Build/hooks/                        # Git hooks
├── .claude-plugin/plugin.json          # Claude Code plugin manifest
├── composer.json                       # Composer package definition
├── docs/                               # Architecture and planning docs
│   └── ARCHITECTURE.md
└── .github/workflows/                  # CI workflows
```

## Commands

No Makefile or npm scripts. Available commands:

- `composer install` — install dependencies (requires [composer-agent-skill-plugin](https://github.com/netresearch/composer-agent-skill-plugin))
- `bash skills/php-modernization/scripts/verify-php-project.sh` — verify a PHP project's modernization status

## Rules

1. **PHP 8.1+ required**: Constructor promotion, readonly, enums, match, attributes, union types
2. **Strict types**: `declare(strict_types=1)` in every file
3. **DTOs over arrays**: Never pass/return raw arrays for structured data — use typed DTOs/Value Objects
4. **Enums over constants**: Replace string/int constants with backed enums for fixed value sets
5. **PHPStan level 9+**: Level 9 minimum, level 10 for new projects
6. **Static analysis stack**: PHPStan + PHPat + Rector + PHP-CS-Fixer (`@PER-CS`)
7. **PSR/PER compliance**: Follow all active PHP-FIG standards (PSR-1, 4, PER-CS, PSR-3/6/7/11/14/15/16/17/18/20)
8. **Type-hint against interfaces**: Use PSR interfaces, not implementations

## References

- [SKILL.md](skills/php-modernization/SKILL.md) — full skill definition with expertise areas
- [php8-features.md](skills/php-modernization/references/php8-features.md) — PHP 8.0-8.5 feature adoption
- [static-analysis-tools.md](skills/php-modernization/references/static-analysis-tools.md) — tool configuration
- [psr-per-compliance.md](skills/php-modernization/references/psr-per-compliance.md) — PHP-FIG standards
- [type-safety.md](skills/php-modernization/references/type-safety.md) — type system strategies
- [migration-strategies.md](skills/php-modernization/references/migration-strategies.md) — upgrade planning
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — architecture overview
