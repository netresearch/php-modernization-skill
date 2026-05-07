# Agent Guide — php-modernization-skill

## Repo Structure

```
.
├── skills/php-modernization/
│   ├── SKILL.md                              # Agent contract (router + guardrails)
│   ├── checkpoints.yaml                      # Mechanical + LLM-review checkpoints
│   ├── references/                           # Lazy-loaded detail docs
│   │   ├── php8-features.md                  # PHP 8.0–8.3 baseline
│   │   ├── php-8.4.md                        # PHP 8.4 (hooks, asymmetric vis., lazy)
│   │   ├── php-8.5.md                        # PHP 8.5 (pipe, array_first/last, NoDiscard)
│   │   ├── static-analysis-tools.md          # PHPStan / PHPat / Rector / PHP-CS-Fixer
│   │   ├── phpstan-compliance.md             # Levels, baseline, extensions
│   │   ├── php-cs-fixer-deprecations.md      # Renamed / removed rules
│   │   ├── psr-per-compliance.md             # Active PSR + PER-CS
│   │   ├── psr15-middleware-architecture.md  # Middleware stacking
│   │   ├── type-safety.md                    # Generics, unions, intersections
│   │   ├── request-dtos.md                   # DTO / VO patterns
│   │   ├── adapter-registry-pattern.md       # Registries from DB config
│   │   ├── multi-version-adapters.md         # Cross-version compatibility
│   │   ├── symfony-patterns.md               # PSR exemplar patterns
│   │   ├── doctrine-modernization-edges.md   # Doctrine 2.x/3.x edges
│   │   ├── api-platform-edges.md             # API Platform resource separation
│   │   ├── immutability-boundaries.md        # readonly vs. hooks vs. mutable
│   │   ├── mutation-testing.md               # Infection diff-mode
│   │   ├── migration-strategies.md           # Upgrade planning
│   │   └── core-rules.md                     # Core modernization rules
│   ├── scripts/
│   │   ├── verify_php_project.py             # Primary verifier (PEP 723)
│   │   ├── modernize_loop.py                 # Fix orchestrator
│   │   ├── introspect.py                     # Cheap profiler
│   │   ├── _common.py                        # Shared helpers
│   │   └── verify-php-project.sh             # Backward-compatible Bash wrapper
│   └── templates/
│       ├── composer-scripts.json             # Drop-in scripts block
│       ├── README.md                         # Template consumption guide
│       └── github-actions/php-modernization.yml  # Copy-and-modify CI workflow
├── schemas/
│   ├── verification-result.schema.json       # Verifier output contract
│   └── project-profile.schema.json           # Introspector output contract
├── fixtures/                                 # Synthetic-project regression suite
│   ├── generic-composer-minimal/
│   ├── symfony-app-minimal/
│   ├── typo3-extension-minimal/
│   ├── monorepo-minimal/
│   ├── fully-modern/                         # Positive control (all checks pass)
│   └── README.md
├── scripts/
│   ├── test_fixtures.py                      # Golden-snapshot diff runner
│   └── verify-harness.sh                     # AGENTS.md/docs harness check
├── docs/ARCHITECTURE.md                      # Architecture overview
├── evals/evals.json                          # Skill evaluation suite
├── .claude-plugin/plugin.json                # Plugin manifest
├── composer.json                             # Composer package manifest
├── sonar-project.properties                  # SonarCloud config (excludes fixtures)
└── .github/workflows/                        # CI workflows
```

## Commands

`uv` is required for the Python tools; the Bash wrapper falls back to `python3` when `uv` is missing.

- `composer install` — install Composer dependencies (requires [composer-agent-skill-plugin](https://github.com/netresearch/composer-agent-skill-plugin)).
- `bash skills/php-modernization/scripts/verify-php-project.sh [path]` — backward-compatible wrapper for the verifier.
- `bash skills/php-modernization/scripts/verify-php-project.sh introspect [path]` — wrapper for the introspector.
- `uv run skills/php-modernization/scripts/introspect.py --root .` — emit the project profile (cheap, no subprocesses).
- `uv run skills/php-modernization/scripts/verify_php_project.py --root . --format json --summary` — full mechanical verification with `agent_actions[]`.
- `uv run skills/php-modernization/scripts/verify_php_project.py --root . --format sarif` — SARIF output for GitHub code scanning.
- `uv run skills/php-modernization/scripts/modernize_loop.py --mode dry-run` — orchestrated fix preview (no mutations).
- `uv run scripts/test_fixtures.py` — regression suite for the verifier itself.
- `bash scripts/verify-harness.sh` — agent-harness consistency check (this file, docs, refs).

## Hard Guardrails

The agent contract in [SKILL.md](skills/php-modernization/SKILL.md#hard-guardrails) is binding. Five refusal cases:

1. No `readonly` on Doctrine entities or mapped-superclasses (embeddables are nuanced — see references).
2. Never run Rector without `--dry-run` first.
3. Raising the PHPStan level requires regenerating + committing the baseline in the same change. Shrink, never delete.
4. No blanket `final` on mock targets or extension points without confirmation.
5. Do not edit `@generated` files or files under `var/cache/`, `vendor/`, `node_modules/`, `.Build/`.

## Rules

1. **PHP 8.1+ required** — promotion, readonly, enums, match, attributes, union types.
2. **Strict types** — `declare(strict_types=1)` in every file.
3. **DTOs over arrays** — typed objects for structured data, never raw arrays.
4. **Backed enums** — replace string/int constants for fixed value sets.
5. **PHPStan ≥ 9** — level 9 minimum, level 10 for new projects, `treatPhpDocTypesAsCertain: false`.
6. **Static analysis stack** — PHPStan + PHPat + Rector + PHP-CS-Fixer (`@PER-CS`).
7. **PSR / PER-CS compliance** — see `references/psr-per-compliance.md`.
8. **Type-hint against PSR interfaces**, not implementations.

## References

- [SKILL.md](skills/php-modernization/SKILL.md) — agent contract and reference-routing table
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — architecture overview
- [CHANGELOG.md](CHANGELOG.md) — release history
- [fixtures/README.md](fixtures/README.md) — regression-suite layout and snapshot rules
- [skills/php-modernization/templates/README.md](skills/php-modernization/templates/README.md) — template consumption guide
- [schemas/verification-result.schema.json](schemas/verification-result.schema.json) — verifier output contract
- [schemas/project-profile.schema.json](schemas/project-profile.schema.json) — introspector output contract
