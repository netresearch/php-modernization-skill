# Architecture — php-modernization-skill

## Purpose

Provides expert patterns for modernizing PHP applications to PHP 8.x with type safety, PSR/PER compliance, static analysis tooling, and Symfony best practices. Designed as a portable agent skill.

## Skill Structure

```
skills/php-modernization/
├── SKILL.md              # Entry point — frontmatter, expertise areas, reference index
├── checkpoints.yaml      # Evaluation criteria
├── references/           # Detailed reference documents (loaded on demand)
└── scripts/
    └── verify-php-project.sh  # Project verification script
```

## Key Components

### SKILL.md (Entry Point)
Contains YAML frontmatter (name, description, version, compatibility, allowed-tools) and an index of expertise areas with pointers to reference documents. Agents read this first to understand scope and find relevant references.

### References (Lazy-Loaded)
Detailed specifications consulted on demand:

- **php8-features.md** — PHP 8.0 through 8.5 feature adoption patterns (constructor promotion, readonly, enums, match, attributes, fibers, property hooks)
- **static-analysis-tools.md** — PHPStan, PHPat, Rector, PHP-CS-Fixer configuration and integration
- **psr-per-compliance.md** — All active PHP-FIG standards with implementation guidance
- **phpstan-compliance.md** — PHPStan level details, baseline management, extension configuration
- **type-safety.md** — Type system maximization (generics via PHPDoc, union/intersection types, strict mode)
- **request-dtos.md** — DTO patterns for HTTP requests, command/query DTOs, value objects
- **adapter-registry-pattern.md** — Dynamic adapter instantiation from database configuration
- **symfony-patterns.md** — DI, service configuration, events, forms, security
- **migration-strategies.md** — Version upgrade assessment, compatibility checks, migration workflows
- **core-rules.md** — Core modernization rules and principles

### Verification Script
`scripts/verify-php-project.sh` checks a PHP project's modernization status (strict_types usage, PHPStan config, composer.json PHP version, etc.).

## Plugin Integration

The `.claude-plugin/plugin.json` manifest registers the skill with Claude Code. The `composer.json` enables installation via Composer for PHP projects using `netresearch/composer-agent-skill-plugin`.

## Data Flow

1. Agent detects PHP modernization task (auto-trigger or manual invocation)
2. Agent reads SKILL.md for expertise areas and reference index
3. Agent consults specific `references/*.md` based on the task domain
4. Agent applies patterns (DTOs, enums, strict types, PSR compliance)
5. Agent optionally runs `verify-php-project.sh` to validate results
