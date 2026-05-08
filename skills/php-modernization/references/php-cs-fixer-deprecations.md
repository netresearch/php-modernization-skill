# PHP-CS-Fixer Deprecated Rule Set Aliases

## Rule Sets (as of PHP-CS-Fixer 3.50.0+)

| Deprecated | Replacement |
|-----------|-------------|
| `@PHP80Migration` | `@PHP8x0Migration` |
| `@PHP80Migration:risky` | `@PHP8x0Migration:risky` |
| `@PHP81Migration` | `@PHP8x1Migration` |
| `@PHP82Migration` | `@PHP8x2Migration` |
| `@PHPUnit100Migration:risky` | `@PHPUnit10x0Migration:risky` |
| `@PER-CS1.0` | `@PER-CS1x0` |
| `@PER-CS2.0` | `@PER-CS2x0` |

## Rules

| Deprecated | Replacement |
|-----------|-------------|
| `function_typehint_space` | `type_declaration_spaces` |

## Detection

Run PHP-CS-Fixer in dry-run mode and check for "Detected deprecations" in output:

```bash
vendor/bin/php-cs-fixer fix --dry-run 2>&1 | grep -A 20 "Detected deprecations"
```

## PER-CS Versions

`@PER-CS` (without version) is a dynamic alias that resolves to the latest non-deprecated PER-CS version. As of PHP-CS-Fixer 3.54.0, this resolves to PER-CS 2.0 (`@PER-CS2x0`).

Use `@PER-CS` for always-latest behavior, or pin to `@PER-CS2x0` for stability.

## PHP migration sets — current availability

PHP-CS-Fixer ships migration sets ahead of, but staggered behind, the
PHP version itself. The non-`:risky` set follows release closely; the
`:risky` variant lags. As of PHP-CS-Fixer **3.95.1**:

| Set | Available | Latest stable |
|---|---|---|
| `@PHP80Migration` … `@PHP85Migration` | ✓ | use the one matching your `composer.json`'s PHP constraint |
| `@PHP80Migration:risky`, `@PHP82Migration:risky` | ✓ | `@PHP82Migration:risky` is the **latest extant `:risky` set** — there is no `@PHP83/84/85Migration:risky` yet |

**Bumping the migration set should track `composer.json`'s PHP
constraint.** A project on `"php": "^8.5"` should use
`@PHP85Migration`. If your project is otherwise PHP-8.5-clean,
bumping the set produces zero diff but sets the right gate.

```bash
# Inventory what migration sets are installed locally
vendor/bin/php-cs-fixer list-sets | grep -E "PHP[0-9]+Migration"
```

## Verifier checks

The verify scripts should detect:

- Deprecated `@PHP8xMigration` aliases (mapping above)
- A `@PHPxxMigration` set lower than the project's PHP constraint
  (e.g. `composer.json` has `"php": "^8.5"` but `.php-cs-fixer.dist.php`
  uses `@PHP83Migration`)
- `@PSR12` / `@PSR12:risky` (deprecated by `@PER-CS`)
