# Templates

Ready-to-paste configuration for projects adopting the **php-modernization** skill.

## `composer-scripts.json`

Drop-in `scripts` entries for `composer.json`. Two ways to consume:

1. **Manual paste**: open the JSON, copy the keys you want into your project's
   `composer.json::scripts` object.
2. **`composer config` per entry** (one-liners), e.g.:

   ```bash
   composer config scripts.cs:fix 'vendor/bin/php-cs-fixer fix'
   composer config scripts.skill:verify 'uv run skills/php-modernization/scripts/verify_php_project.py --root . --format json'
   ```

The script names (`cs:fix`, `phpstan`, `rector`) are the ones the verifier
checks for via PM-13, PM-14 and PM-15 — adopting them lets the skill light
those checkpoints green automatically. The `skill:*` aliases give you a
one-command path to the introspector and verifier from inside the project.

### Why no inline `_comment` in the JSON?

Composer treats every key under `scripts` as a runnable script — a `_comment`
key would surface in `composer run-script --list` and in IDE autocomplete,
confusing users and offering a script that does nothing. Composer has no
native syntax for inline script comments, so all explanatory text lives in
this README instead.

### Script reference

| Script           | Purpose                                                                  |
| ---------------- | ------------------------------------------------------------------------ |
| `cs:fix`         | Apply PHP-CS-Fixer fixes in place.                                       |
| `cs:check`       | Dry-run PHP-CS-Fixer; prints diff and exits non-zero on findings.        |
| `phpstan`        | Run PHPStan analysis (no progress bar — CI friendly).                    |
| `rector`         | Apply Rector refactorings in place.                                      |
| `rector:check`   | Dry-run Rector; exits non-zero if rewrites would happen.                 |
| `phpat`          | Architecture-test PHPStan run (uses the same binary, separate config).   |
| `audit`          | `composer audit --locked` — fails on advisories.                         |
| `skill:inspect`  | Run the project introspector via `uv` (writes JSON profile).             |
| `skill:verify`   | Run the mechanical verifier via `uv` (writes JSON report).               |
| `skill:fix`      | Convenience alias: `cs:fix` then `rector`.                               |
| `skill:qa`       | Full QA chain: `skill:inspect` → `cs:check` → `phpstan` → `skill:verify` (cheap → expensive). |

## `github-actions/php-modernization.yml`

A reusable GitHub Actions workflow that runs the verifier and uploads the
SARIF result to the **Security → Code scanning** tab. Copy it to
`.github/workflows/php-modernization.yml` in your repo and adjust the PHP
version matrix as needed.

## Together

- Local feedback: `composer skill:qa` — runs four steps in order:
  1. `skill:inspect` (project profile)
  2. `cs:check` (lint dry-run)
  3. `phpstan` (static analysis)
  4. `skill:verify` (skill checkpoints)
- CI: workflow runs `verify_php_project.py --format sarif` and uploads
- Release-gate: workflow run failure ⇒ skill checkpoint regression
