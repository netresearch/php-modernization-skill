# Changelog

All notable changes to **php-modernization-skill** are documented in this file.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Section ordering within a release: **Added → Changed → Deprecated → Removed → Fixed → Security**.

## [Unreleased]

This entry collects the cumulative work landed on `main` after the v1.15.1 tag — the agent-harness refocus that turns the skill into an executable contract instead of a static reference bundle. Release notes will be assigned a version when the next tag is cut.

### Added

#### Agent-contract executable layer

- `skills/php-modernization/scripts/verify_php_project.py` — primary mechanical verifier. PEP 723, runnable via `uv run`. Emits JSON (`schema_version: 1.0.0`), SARIF 2.1.0, or JUnit XML. Supports `--summary`, `--check PM-XX`, `--no-tools`, `--no-cache`, `--root`. Includes machine-readable `agent_actions[]` recommendations so downstream agents can plan fixes without re-reading the rule descriptions.
- `skills/php-modernization/scripts/modernize_loop.py` — orchestrator that chains PHP-CS-Fixer, Rector, PHPStan, and Infection (PR-diff mode) into a single transcript. Defaults to `--mode dry-run`; `apply` mode requires `--confirm`.
- `skills/php-modernization/scripts/introspect.py` — cheap first-touch profiler. Detects archetype, PHP version constraint, tooling fingerprints, and PSR-4 layout without invoking subprocesses (other than `php --version`). Always exits 0.
- `skills/php-modernization/scripts/_common.py` — shared archetype detection, composer parsing, and version helpers used by the verifier and introspector.
- `skills/php-modernization/scripts/verify-php-project.sh` rewritten as a thin Bash wrapper that dispatches to either `verify_php_project.py` (default) or `introspect.py` (`introspect` subcommand), with a `python3` fallback when `uv` is missing.

#### JSON Schemas (public output contract)

- `schemas/verification-result.schema.json` — JSON Schema 2020-12 for verifier output.
- `schemas/project-profile.schema.json` — JSON Schema 2020-12 for introspector output.

#### Reference documents

- `skills/php-modernization/references/php-8.4.md` — property hooks, asymmetric visibility, lazy objects, `array_find` / `array_any` / `array_all`.
- `skills/php-modernization/references/php-8.5.md` — pipe operator `|>`, `array_first` / `array_last`, `#[\NoDiscard]`.
- `skills/php-modernization/references/immutability-boundaries.md` — when `readonly` applies vs. property hooks vs. classic mutation.
- `skills/php-modernization/references/doctrine-modernization-edges.md` — Doctrine ORM 2.x/3.x, mapped superclasses, embeddables; explicitly forbids `readonly` on entities.
- `skills/php-modernization/references/mutation-testing.md` — Infection diff-mode workflow, MSI thresholds, baseline strategy.
- `skills/php-modernization/references/api-platform-edges.md` — API Platform 3.x/4.x state-providers, processors, resource separation.
- `skills/php-modernization/references/psr15-middleware-architecture.md` — PSR-15 middleware stacking, request-handler patterns, framework integration.

#### Checkpoints

- `PM-39` (mechanical): `readonly` keyword presence on Doctrine entity classes — fails when `readonly class` collides with `#[Entity]`.
- `PM-40` (LLM review): broad `readonly` review covering inheritance, embeddables, and serialization edges.
- `PM-41` (LLM review): Infection diff-mode wiring — checks that PR-mode mutation testing is configured.
- `PM-42` (LLM review): API Platform resource separation — entity vs. API resource boundary.

#### Templates

- `skills/php-modernization/templates/composer-scripts.json` — drop-in `scripts` block (`cs:fix`, `cs:check`, `phpstan`, `rector`, `rector:check`, `phpat`, `audit`, `skill:inspect`, `skill:verify`, `skill:fix`, `skill:qa`).
- `skills/php-modernization/templates/README.md` — consumption guide and per-script reference.
- `skills/php-modernization/templates/github-actions/php-modernization.yml` — copy-and-modify reusable workflow that runs the verifier, uploads SARIF to the GitHub code-scanning tab, runs the orchestrator in dry-run mode, and posts a PR summary comment on failure.

#### Regression suite

- `fixtures/generic-composer-minimal/`, `fixtures/symfony-app-minimal/`, `fixtures/typo3-extension-minimal/`, `fixtures/monorepo-minimal/`, `fixtures/fully-modern/` — synthetic project shapes covering the four detected archetypes plus a positive control.
- `fixtures/<name>/expected/verifier.json` — golden snapshots for each fixture.
- `scripts/test_fixtures.py` — golden-snapshot diff runner with normalization for non-deterministic fields (`generated_at`, `project_root`, `environment.php_runtime`, `tool_runs[]`).

#### Project-archetype detection

- Four archetypes auto-detected by the verifier and orchestrator: `generic-composer`, `typo3-extension`, `symfony-app`, `monorepo-package` (plus `unknown`).

#### Other

- `sonar-project.properties` — excludes `fixtures/` from SonarCloud analysis.
- `.gitignore` entries for Python bytecode caches.

### Changed

- `SKILL.md` restructured as an **agent router** with hard guardrails: discover → drill → apply → references decision flow, reference-routing table, and explicit refusal cases. Long-form content was moved into the references; `SKILL.md` itself is now a short contract.
- Verifier output is now treated as a public schema. Checkpoint IDs are stable; renumbering is forbidden.
- `verify-php-project.sh` is now a wrapper, not the verifier — the implementation lives in Python.

### Deprecated

- Checkpoint IDs `PM-26`, `PM-27`, `PM-28`, `PM-33`, `PM-35`, `PM-36` are **permanently retired** in this skill. They MUST NOT be reused. Equivalent checks now live in `typo3-conformance` and `typo3-extension-upgrade`.

### Removed

- `skills/php-modernization/references/typo3-psr-patterns.md` — TYPO3-specific PSR guidance migrated to the TYPO3 skill set as part of the dedup.
- The TYPO3-specific checkpoints listed above (relocated, see Deprecated).

### Fixed

- (No standalone bug-fix entries since v1.15.1; behaviour changes are folded into Added/Changed.)

### Security

- (No security advisories since v1.15.1.)

## [1.15.1] - 2026-04-25

(historical — pre-CHANGELOG)

[Unreleased]: https://github.com/netresearch/php-modernization-skill/compare/v1.15.1...HEAD
[1.15.1]: https://github.com/netresearch/php-modernization-skill/releases/tag/v1.15.1
