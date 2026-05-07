# Architecture — php-modernization-skill

## Purpose

Provides expert patterns for modernizing PHP applications to PHP 8.x with type safety, PSR / PER-CS compliance, static-analysis tooling, and Symfony-grade architecture. The skill is portable: it works with any agent that supports the Agent Skills specification.

Since the agent-harness refocus, the skill is also an **executable contract**. A small set of Python tools emit machine-readable verification reports, archetype profiles, and fix-loop transcripts that downstream agents can drive without re-reading the prose references.

## Skill Structure

```
skills/php-modernization/
├── SKILL.md              # Agent contract: discover → drill → apply → references
├── checkpoints.yaml      # Mechanical + LLM-review checkpoints (PM-XX IDs)
├── references/           # Lazy-loaded detail docs (loaded on demand only)
├── scripts/              # Verifier, orchestrator, introspector, shared helpers
└── templates/            # composer-scripts.json + GitHub Actions workflow
```

## Key Components

### SKILL.md (agent router)

YAML frontmatter (name, description, license, compatibility, allowed-tools) followed by a short contract: a four-step decision flow, a reference-routing table, five hard guardrails, the tooling baseline, and a migration checklist. Agents read this first; nothing else is loaded eagerly.

### References (lazy-loaded)

Detail consulted on demand. Grouped by domain:

- **PHP language**: `php8-features.md`, `php-8.4.md`, `php-8.5.md`
- **Static analysis**: `static-analysis-tools.md`, `phpstan-compliance.md`, `php-cs-fixer-deprecations.md`
- **Standards**: `psr-per-compliance.md`, `psr15-middleware-architecture.md`
- **Type-system**: `type-safety.md`, `request-dtos.md`, `immutability-boundaries.md`
- **Architecture**: `adapter-registry-pattern.md`, `multi-version-adapters.md`, `symfony-patterns.md`
- **Framework edges**: `doctrine-modernization-edges.md`, `api-platform-edges.md`
- **Quality**: `mutation-testing.md`, `migration-strategies.md`, `core-rules.md`

The full routing table lives in [SKILL.md](../skills/php-modernization/SKILL.md#reference-routing).

### Verification & Orchestration

Three Python tools form the executable layer. All three are PEP 723 self-describing scripts runnable via `uv run`. Stdlib-only — no third-party Python dependencies.

| Tool | Role | Side effects | Exit code |
| --- | --- | --- | --- |
| `scripts/introspect.py` | Cheap first-touch profiler. Emits a project-profile JSON: archetype, PHP version, tooling fingerprints, PSR-4 mapping, baseline presence. | `php --version` only. | Always 0. |
| `scripts/verify_php_project.py` | Primary mechanical verifier. Runs the curated `PM-XX` checks and (optionally) shells out to PHPStan, Rector, PHP-CS-Fixer for live tool runs. Emits JSON, SARIF, or JUnit. Includes `agent_actions[]` recommendations. | Subprocesses if tools are present and `--no-tools` is not set; cache file under `.build/php-modernization/`. | 0 on pass/warn, 1 on fail. |
| `scripts/modernize_loop.py` | Fix orchestrator. Chains PHP-CS-Fixer, Rector, PHPStan, and Infection (diff-mode) into a transcript the agent reasons about. `--mode dry-run` is default; `apply` requires `--confirm`. | None in `dry-run`; mutates in `apply`. | 0 if every required tool passes, 1 otherwise. |

`scripts/_common.py` holds shared archetype detection, composer parsing, and version helpers used by the verifier and the introspector.

`scripts/verify-php-project.sh` is a thin Bash wrapper kept for backward compatibility. It dispatches to either `verify_php_project.py` (default) or `introspect.py` (when the first arg is `introspect`), and falls back to `python3` when `uv` is missing.

### JSON Schemas

The verifier and introspector outputs are public contracts. Both schemas use JSON Schema 2020-12.

- `schemas/verification-result.schema.json` — output of `verify_php_project.py --format json`. Required fields: `schema_version`, `skill`, `skill_version`, `generated_at`, `project_root`, `archetype`, `summary`. Checkpoint IDs (`PM-XX`) are stable forever — never renumbered.
- `schemas/project-profile.schema.json` — output of `introspect.py`. Captures archetype, PHP runtime, composer summary, and tooling booleans.

Downstream consumers should pin to a `schema_version`; new fields are additive within `1.x`.

### Regression Suite

Synthetic project fixtures and golden-output snapshots guard the verifier from accidental contract drift. See [fixtures/README.md](../fixtures/README.md) for the per-fixture description and snapshot-update workflow.

- `fixtures/generic-composer-minimal/`, `fixtures/symfony-app-minimal/`, `fixtures/typo3-extension-minimal/`, `fixtures/monorepo-minimal/` — one per detected archetype.
- `fixtures/fully-modern/` — positive control where every check passes.
- `scripts/test_fixtures.py` — runs the verifier against each fixture with `--no-tools --no-cache`, applies a normalization pass (scrubs `generated_at`, `project_root`, `environment.php_runtime`, `tool_runs[]`), and diffs against `expected/verifier.json`. Use `--update` to regenerate snapshots when output legitimately changes.

## Plugin Integration

`.claude-plugin/plugin.json` registers the skill with Claude Code. `composer.json` enables installation via Composer for PHP projects using `netresearch/composer-agent-skill-plugin` — the plugin discovers `extra.ai-agent-skill` and surfaces the skill to the local agent.

## Project Archetypes

The verifier and orchestrator branch on archetype. Detection is pure (no subprocesses) and lives in `scripts/_common.py::detect_archetype`. Priority order:

1. `typo3-extension` — `ext_emconf.php` or `Configuration/Services.yaml`
2. `symfony-app` — `bin/console` plus `config/bundles.php`
3. `monorepo-package` — `packages/<name>/composer.json` for two or more children
4. `generic-composer` — `composer.json` plus `src/` plus `tests/`
5. `unknown` — fallback

## Data Flow

The agent contract codifies the loop:

1. **Discover** — read `SKILL.md`, then run `introspect.py` (cheap) or `verify_php_project.py --summary` for a full picture.
2. **Drill** — for any failing checkpoint, narrow with `verify_php_project.py --check PM-XX`. Only fan out to the full report when triaging more than three findings.
3. **Apply** — preview with `modernize_loop.py --mode dry-run`. Review the transcript before applying.
4. **References** — load `references/<topic>.md` only when a fix needs the long-form rationale.

CI mirrors the same flow via [skills/php-modernization/templates/github-actions/php-modernization.yml](../skills/php-modernization/templates/github-actions/php-modernization.yml): verifier → SARIF upload → orchestrator dry-run → PR summary comment on failure.
