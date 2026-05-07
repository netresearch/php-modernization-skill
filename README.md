# PHP Modernization Skill

Expert patterns for modernizing PHP applications to PHP 8.x with type safety, PSR / PER-CS compliance, static-analysis tooling, and Symfony-grade architecture. The skill ships an **agent contract** — a small set of executable tools that emit machine-readable verification reports, archetype profiles, and fix-loop transcripts.

## Compatibility

This is an **Agent Skill** following the [open standard](https://agentskills.io) originally developed by Anthropic and released for cross-platform use.

Supported platforms:

- Claude Code (Anthropic)
- Cursor
- GitHub Copilot
- Other skills-compatible AI agents

Skills are portable packages of procedural knowledge that work across any AI agent supporting the Agent Skills specification.

## Features

- **Agent contract**: a Python verifier (`verify_php_project.py`), orchestrator (`modernize_loop.py`), and cheap profiler (`introspect.py`). stable structured output (JSON with `schema_version 1.0.0`, SARIF 2.1.0, or JUnit XML), archetype detection, and machine-readable `agent_actions[]` recommendations downstream agents can act on without re-reading the prose references.
- **Hard guardrails**: five binding refusal cases enforced in `SKILL.md` (no `readonly` on Doctrine entities, no Rector without `--dry-run`, baseline shrink-not-delete, no blanket `final` on mock targets, no editing generated files).
- **PHP 8.x feature coverage**: 8.0–8.3 baseline, dedicated 8.4 reference (released 2024-11: property hooks, asymmetric visibility, lazy objects, `array_find` / `array_any` / `array_all`), and dedicated 8.5 reference (released 2025-11: pipe `|>`, `array_first` / `array_last`, `#[\NoDiscard]`).
- **Static-analysis stack**: PHPStan (level 9+, level 10 recommended), PHPat (architecture testing), Rector (automated refactoring), PHP-CS-Fixer (`@PER-CS`), Infection (mutation testing in PR-diff mode), `composer audit`.
- **Type-safety patterns**: DTOs and Value Objects over arrays, generic collection typing via PHPDoc, strict typing everywhere, immutability boundaries (`readonly` vs. property hooks vs. classic mutation).
- **Framework edges**: dedicated references for Doctrine 2.x/3.x edges, API Platform resource separation, and PSR-15 middleware architecture.
- **PSR / PER-CS compliance**: PSR-1, 3, 4, 6, 7, 11, 13, 14, 15, 16, 17, 18, 20 plus PER Coding Style. PSR-12 superseded by PER-CS.
- **Project-archetype detection**: `generic-composer`, `typo3-extension`, `symfony-app`, `monorepo-package`. The verifier and orchestrator branch on archetype.
- **Regression suite**: synthetic fixtures plus golden-output snapshots guard the verifier from contract drift.

## Agent Contract

The skill follows a four-step loop. Cheap commands first; expensive analysis only when needed.

1. **Discover** — read [`SKILL.md`](skills/php-modernization/SKILL.md), then profile the project.
2. **Drill** — narrow to one finding at a time when more than three things fail.
3. **Apply** — preview every fix in `--mode dry-run` before mutating files.
4. **References** — load `references/<topic>.md` only when the long-form rationale is needed.

### One-line invocations

```bash
# Cheap first-touch profile (no subprocesses except `php --version`)
uv run skills/php-modernization/scripts/introspect.py --root .

# Full mechanical verification with agent_actions[]
uv run skills/php-modernization/scripts/verify_php_project.py --root . --format json --summary

# One checkpoint at a time
uv run skills/php-modernization/scripts/verify_php_project.py --root . --check PM-02

# Orchestrated fix preview (no mutations; use --confirm to apply)
uv run skills/php-modernization/scripts/modernize_loop.py --mode dry-run
```

`uv` is the recommended runner for the Python tools (it resolves the PEP 723 inline dependencies automatically). The Bash wrapper transparently falls back to `python3` if `uv` is not installed.

### Output formats

`verify_php_project.py` accepts `--format json | sarif | junit`. JSON is the canonical contract (see [`schemas/verification-result.schema.json`](schemas/verification-result.schema.json)). SARIF 2.1.0 plugs into the GitHub **Security → Code scanning** tab. JUnit XML is convenient for CI dashboards. Checkpoint IDs (`PM-XX`) are stable forever — never renumbered.

### Hard Guardrails

The five guardrails below are binding. The agent must refuse rather than violate them.

- Never apply `readonly` to Doctrine entities or mapped-superclasses (embeddables are a nuanced case, ORM 3.x dependent — see [`references/doctrine-modernization-edges.md`](skills/php-modernization/references/doctrine-modernization-edges.md)).
- Never run Rector without `--dry-run` first.
- Never raise the PHPStan level without regenerating + committing the baseline in the same change. Shrink, never delete.
- Never apply blanket `final` to mock targets or extension points without confirmation.
- Never edit `@generated` files or files under `var/cache/`, `vendor/`, `node_modules/`, `.Build/`.

The full table of references is in [`SKILL.md`](skills/php-modernization/SKILL.md#reference-routing).

## Installation

### Marketplace (recommended)

Add the [Netresearch marketplace](https://github.com/netresearch/claude-code-marketplace) once, then browse and install skills.

```bash
# Claude Code
/plugin marketplace add netresearch/claude-code-marketplace
```

### npx ([skills.sh](https://skills.sh))

Install with any [Agent Skills](https://agentskills.io)-compatible agent:

```bash
npx skills add https://github.com/netresearch/php-modernization-skill --skill php-modernization
```

### Composer (PHP projects)

```bash
composer require netresearch/php-modernization-skill
```

Requires [netresearch/composer-agent-skill-plugin](https://github.com/netresearch/composer-agent-skill-plugin).

### Download release

Download the [latest release](https://github.com/netresearch/php-modernization-skill/releases/latest) and extract to your agent's skills directory.

### Git clone

```bash
git clone https://github.com/netresearch/php-modernization-skill.git
```

## Usage

The skill auto-triggers on PHP modernization work: type-safety enforcement, PHPStan / Rector / PHP-CS-Fixer / PHPat setup, PSR / PER-CS compliance, Symfony patterns, version upgrades from 7.x or 8.0–8.3 baselines, and PHP 8.4 / 8.5 feature adoption.

Example queries:

- "Modernize this PHP class to PHP 8.4 with property hooks."
- "Add strict type safety with PHPStan level 10."
- "Set up PHPat architecture tests."
- "Configure Rector for a PHP 8.3 upgrade — dry-run only."
- "Make this HTTP client PSR-18 compliant."
- "Audit this Doctrine entity for incorrect `readonly` usage."

## Verification & CI

### Local

[`templates/composer-scripts.json`](skills/php-modernization/templates/composer-scripts.json) is a drop-in `scripts` block for `composer.json`. Highlights:

- `cs:fix`, `cs:check` — PHP-CS-Fixer apply / dry-run
- `phpstan` — analysis without progress bar (CI-friendly)
- `rector`, `rector:check` — apply / dry-run
- `phpat`, `audit` — architecture tests + composer advisories
- `skill:inspect`, `skill:verify` — introspector / verifier shortcuts
- `skill:fix`, `skill:qa` — convenience pipelines

The script-name conventions (`cs:fix`, `phpstan`, `rector`) map onto checkpoints `PM-13`, `PM-14`, `PM-15` — adopting them lights those checks green automatically. See [`templates/README.md`](skills/php-modernization/templates/README.md) for full guidance.

### CI

[`templates/github-actions/php-modernization.yml`](skills/php-modernization/templates/github-actions/php-modernization.yml) is a copy-and-modify GitHub Actions workflow. It runs the verifier, optionally uploads SARIF to the **Security → Code scanning** tab, runs the orchestrator in `--mode dry-run` (with Infection diff-mode against the PR base), uploads artifacts, and posts a PR summary comment on failure. Adjust the `php-version` matrix to match your project's PHP requirement.

## Project Archetypes

The verifier and orchestrator branch on archetype. Detection is pure (no subprocesses) and lives in `scripts/_common.py::detect_archetype`. Priority order:

| Archetype | Detection signal |
| --- | --- |
| `typo3-extension` | `ext_emconf.php` or `Configuration/Services.yaml` |
| `symfony-app` | `bin/console` plus `config/bundles.php` |
| `monorepo-package` | `packages/<name>/composer.json` for two or more children |
| `generic-composer` | `composer.json` plus `src/` plus `tests/` |

A regression suite under [`fixtures/`](fixtures/) covers each archetype plus a `fully-modern/` positive control where every check passes. See [`fixtures/README.md`](fixtures/README.md) for the snapshot workflow.

## Repository Layout

```
php-modernization-skill/
├── skills/php-modernization/
│   ├── SKILL.md                       # Agent contract (router + guardrails)
│   ├── checkpoints.yaml               # PM-XX checkpoints
│   ├── references/                    # 19 lazy-loaded reference docs
│   ├── scripts/                       # verify_php_project.py + orchestrator + introspector
│   └── templates/                     # composer-scripts.json + GitHub Actions workflow
├── schemas/                           # JSON Schema 2020-12 (output contracts)
├── fixtures/                          # Synthetic-project regression suite
├── scripts/                           # test_fixtures.py + verify-harness.sh
├── docs/ARCHITECTURE.md               # Architecture overview
├── evals/                             # Skill evaluation suite
├── composer.json                      # Composer manifest
├── .claude-plugin/plugin.json         # Claude Code plugin manifest
└── sonar-project.properties           # SonarCloud config (excludes fixtures)
```

## Required Static Analysis Tools

| Tool | Purpose | Requirement |
| --- | --- | --- |
| [PHPStan](https://phpstan.org/) | Type checking, bug detection | Level 9 minimum, level 10 recommended |
| [PHPat](https://www.phpat.dev/) | Architecture testing | Required for projects with defined layer boundaries |
| [Rector](https://getrector.com/) | Automated refactoring | Required for modernization (always dry-run first) |
| [PHP-CS-Fixer](https://cs.symfony.com/) | Coding style | Required with `@PER-CS` |
| [Infection](https://infection.github.io/) | Mutation testing | Required in PR-diff mode |

## PSR / PER-CS Compliance

| Standard | Purpose | Notes |
| --- | --- | --- |
| PSR-1 | Basic Coding | Required |
| PSR-4 | Autoloading | Required |
| PER Coding Style | Coding style | Required (supersedes PSR-12) |
| PSR-12 | Extended coding style | Superseded by PER-CS — do not use |
| PSR-3 | Logger | When logging |
| PSR-6 / PSR-16 | Cache | When caching |
| PSR-7 / PSR-17 / PSR-18 | HTTP messages, factories, client | For HTTP clients |
| PSR-11 | Container | For DI containers |
| PSR-13 | Hypermedia links | For HATEOAS responses |
| PSR-14 | Events | For event dispatching |
| PSR-15 | HTTP middleware | See [`references/psr15-middleware-architecture.md`](skills/php-modernization/references/psr15-middleware-architecture.md) |
| PSR-20 | Clock | For time-dependent code |

Source of truth: [php-fig.org/psr](https://www.php-fig.org/psr/) and [php-fig.org/per](https://www.php-fig.org/per/).

## Type Safety: DTOs and Value Objects

Never pass or return raw arrays for structured data. Use typed objects.

| Instead of | Use |
| --- | --- |
| `array $userData` | `UserDTO $user` |
| `array{email: string, name: string}` | `readonly class UserDTO` |
| `array $config` | `readonly class Config` or Value Object |
| `array $request` | `RequestDTO::fromRequest($request)` |
| `return ['success' => true, 'data' => $x]` | `return new ResultDTO($x)` |

Why: arrays lack runtime type safety, IDE autocompletion, and refactor-friendliness; PHPStan cannot verify array shapes across boundaries. Full patterns including Request DTOs, Command/Query DTOs, and Value Objects live in [`references/request-dtos.md`](skills/php-modernization/references/request-dtos.md). Immutability rules — when `readonly` applies, when property hooks fit better, when classic mutation is correct — are in [`references/immutability-boundaries.md`](skills/php-modernization/references/immutability-boundaries.md).

## Type Safety: Backed Enums

Never use string or integer constants, or arrays of literals, for fixed value sets. Use PHP 8.1+ backed enums.

| Instead of | Use |
| --- | --- |
| `const STATUS_DRAFT = 'draft'` | `enum Status: string { case Draft = 'draft'; }` |
| `['draft', 'published', 'archived']` | `Status::cases()` |
| `string $status` parameter | `Status $status` parameter |
| `switch ($status)` | `match ($status)` with enum |

Why: compile-time type checks, IDE autocompletion, exhaustive `match()` enforcement, and methods that encapsulate label / colour / validation logic. Full patterns are in [`references/php8-features.md`](skills/php-modernization/references/php8-features.md).

## Migration Checklist

- `declare(strict_types=1)` everywhere
- `@PER-CS` ruleset, no deprecated PHP-CS-Fixer aliases
- PHPStan ≥ 9 with `treatPhpDocTypesAsCertain: false` (level 10 for new projects)
- PHPat for layer boundaries
- Return + parameter types on every method
- DTOs over arrays; backed enums over constants
- PSR interfaces in type-hints (not implementations)
- `#[Override]` (8.3+), `#[SensitiveParameter]` (8.2+), typed constants (8.3+)
- `readonly` on DTOs / VOs / events only — see immutability boundaries
- Property hooks (8.4) for validated mutable state
- `array_find` / `array_any` / `array_all` over manual loops (8.4)
- Pipe `|>` for transform pipelines (8.5)

## Related Skills

- **security-audit-skill** — security patterns for PHP applications.
- **typo3-conformance** and **typo3-extension-upgrade** — TYPO3-specific checkpoints (the IDs `PM-26/27/28/33/35/36` were relocated there).
- **typo3-testing-skill** — PHPUnit patterns applicable to any PHP project.

## License

This project uses split licensing:

- **Code** (scripts, workflows, configs): [MIT](LICENSE-MIT)
- **Content** (skill definitions, documentation, references): [CC-BY-SA-4.0](LICENSE-CC-BY-SA-4.0)

See the individual license files for full terms.

## Credits

Developed and maintained by [Netresearch DTT GmbH](https://www.netresearch.de/).
