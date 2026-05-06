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

## `github-actions/php-modernization.yml`

A reusable GitHub Actions workflow that runs the verifier and uploads the
SARIF result to the **Security → Code scanning** tab. Copy it to
`.github/workflows/php-modernization.yml` in your repo and adjust the PHP
version matrix as needed.

## Together

- Local feedback: `composer skill:qa` (lints, statically analyses, verifies)
- CI: workflow runs `verify_php_project.py --format sarif` and uploads
- Release-gate: workflow run failure ⇒ skill checkpoint regression
