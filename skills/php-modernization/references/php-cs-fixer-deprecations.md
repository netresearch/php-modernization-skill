# PHP-CS-Fixer Deprecated Rule Set Aliases

## Rule Sets (as of PHP-CS-Fixer 3.90+)

| Deprecated | Replacement |
|-----------|-------------|
| `@PHP80Migration` | `@PHP8x0Migration` |
| `@PHP80Migration:risky` | `@PHP8x0Migration:risky` |
| `@PHP81Migration` | `@PHP8x1Migration` |
| `@PHP82Migration` | `@PHP8x2Migration` |
| `@PHPUnit100Migration:risky` | `@PHPUnit10x0Migration:risky` |
| `@PER-CS1.0` | `@PER-CS1x0` |
| `@PER-CS2.0` | `@PER-CS2x0` |
| `@PER-CS3.0` | `@PER-CS3x0` |

## Rules

| Deprecated | Replacement |
|-----------|-------------|
| `function_typehint_space` | `type_declaration_spaces` |

## Detection

Run PHP-CS-Fixer in dry-run mode and check for "Detected deprecations" in output:

```bash
php-cs-fixer fix --dry-run 2>&1 | grep -A 20 "Detected deprecations"
```

## PER-CS Versions

`@PER-CS` (without version) is a dynamic alias that resolves to the latest non-deprecated PER-CS version. As of PHP-CS-Fixer 3.94, this resolves to PER-CS 3.0 (`@PER-CS3x0`).

Use `@PER-CS` for always-latest behavior, or pin to `@PER-CS3x0` for stability.
