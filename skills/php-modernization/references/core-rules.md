# Core Rules & Examples

## DTOs Required

When passing structured data, always use DTOs instead of arrays:

```php
// Bad: public function createUser(array $data): array
// Good: public function createUser(CreateUserDTO $dto): UserDTO
```

## Enums Required

When defining fixed value sets, always use backed enums instead of constants:

```php
// Bad: const STATUS_DRAFT = 'draft'; function setStatus(string $s)
// Good: enum Status: string { case Draft = 'draft'; }
```

## PSR Interface Compliance

When type-hinting dependencies, use PSR interfaces (PSR-3, PSR-6, PSR-7, PSR-11, PSR-14, PSR-18).

## Array Functions Over Regex for Token Lists

When adding/removing specific tokens in a delimited string (CSS classes, scopes), prefer `explode`/`array_filter`/`implode` over `preg_replace`:

```php
// Bad: trim(preg_replace('/\bfloat-(start|end)\b/', '', $classes)) ?: null
// Good:
$kept = array_filter(
    explode(' ', $classes),
    static fn (string $c): bool => $c !== '' && !in_array($c, ['float-start', 'float-end'], true),
);
$result = $kept !== [] ? implode(' ', $kept) : null;
```

The `$c !== ''` guard drops empty tokens from leading, trailing, or repeated spaces, so the result has no stray spaces and collapses to `null` when nothing is left. The array form states the intent (keep tokens not in this set) and avoids regex word-boundary and partial-match traps.

## Scoring Criteria

| Criterion | Requirement |
|-----------|-------------|
| PHPStan | Level 9 minimum |
| PHP-CS-Fixer | `@PER-CS` zero violations |
| DTOs/VOs | No array params/returns for structured data |
| Enums | Backed enums for fixed value sets |
