# Verifier Regression Fixtures

Synthetic project fixtures and golden-output snapshots used by
`scripts/test_fixtures.py` to detect unintended changes in the
`verify_php_project.py` mechanical verifier.

## Layout

Each fixture is a directory under `fixtures/` shaped like a real PHP project,
with a `expected/verifier.json` snapshot capturing the verifier's output for
that shape:

| Fixture | Purpose | Detected archetype |
| --- | --- | --- |
| `generic-composer-minimal/` | Bare-bones library with `src/` + `tests/` and PSR-4 autoload. Most checks fail; PM-19 (PSR-4) passes. | `generic-composer` |
| `symfony-app-minimal/` | Minimal Symfony 7 app shape (`bin/console` + `config/bundles.php` + `src/Controller/`). | `symfony-app` |
| `typo3-extension-minimal/` | Minimal TYPO3 extension (`ext_emconf.php`, `Configuration/Services.yaml`, `Classes/`). | `typo3-extension` |
| `monorepo-minimal/` | Top-level project with `packages/foo` and `packages/bar` each carrying their own `composer.json`. | `monorepo-package` |
| `fully-modern/` | Positive control: phpstan.neon (level: max + treatPhpDocTypesAsCertain: false), `.php-cs-fixer.dist.php` (@PER-CS), `rector.php`, composer scripts, and dev-deps for phpstan / php-cs-fixer / rector / phpat. **All checks pass.** | `generic-composer` |

The fixture content is kept minimal but realistic so an agent can use any of
them as a starting-point reference.

## Snapshot determinism

`verify_php_project.py` emits a few fields that vary between runs or hosts. To
make snapshots stable, `scripts/test_fixtures.py` applies an idempotent
normalization pass to *both* the live verifier output and the loaded snapshot
before diffing:

| Field | Treatment |
| --- | --- |
| `generated_at` | Replaced with the literal string `"<NORMALIZED>"`. |
| `project_root` | Replaced with `"<NORMALIZED>"` (absolute path differs per checkout). |
| `environment.php_runtime` | Replaced with `"<NORMALIZED>"` (varies per runner; can also be `"unknown"` if `php` is not on PATH). |
| `tool_runs[]` | Replaced with `[]` — these are subprocess outcomes, not deterministic. The runner invokes the verifier with `--no-tools`, so this should already be empty, but the normalization makes the contract explicit. |
| `checks[]` | Sorted by `id`. |
| `agent_actions[]` | Sorted by `checkpoint`. |

The runner uses `--no-tools --no-cache` to keep evaluation fast and free of
side effects. With `--no-tools` no `.build/` artifact directory is created in
the fixture tree.

## Running the regression tests

From the repo root:

```sh
uv run scripts/test_fixtures.py                     # diff all fixtures
uv run scripts/test_fixtures.py --fixture <name>    # one fixture only
uv run scripts/test_fixtures.py --update            # regenerate snapshots
```

Exit code is `0` when all fixtures match their snapshots, `1` otherwise, `2`
on harness errors (verifier missing, unknown fixture name, etc.).

## When to update snapshots

Use `--update` only when the verifier output legitimately changed and you
intend the new shape to become the contract. Common triggers:

- A new mechanical check (PM-NN) was added.
- An existing check's `message`, `severity`, or `evidence` shape changed.
- `skill_version` was bumped (the version is hardcoded in the verifier source
  and appears in every snapshot — every release of the skill regenerates all
  snapshots; this is expected).
- An `agent_actions[]` entry's `target` / `operation` / `rationale` changed.

Before running `--update`, confirm the diff is intentional. Review the
resulting `git diff fixtures/*/expected/verifier.json` and commit alongside
the verifier change so reviewers see the contract evolve in lockstep.

## Adding a new fixture

1. Create a directory under `fixtures/<name>/` with the project files.
   - The fixture **must** include a `composer.json` (the runner discovers
     fixtures by this marker).
   - Make sure no archetype-detection markers from earlier-priority archetypes
     leak in (TYPO3 markers > Symfony markers > monorepo > generic). For
     example, a `symfony-app` fixture must not contain `ext_emconf.php`.
   - Every `.php` file should `declare(strict_types=1);`.
2. Run `uv run scripts/test_fixtures.py --update --fixture <name>` to write
   the initial `expected/verifier.json`.
3. Inspect the snapshot manually — confirm the archetype and pass/fail set
   match what you intended to capture.
4. Run `uv run scripts/test_fixtures.py` (without `--update`) to confirm the
   snapshot diffs cleanly.
