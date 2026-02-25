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

## Scoring Criteria

| Criterion | Requirement |
|-----------|-------------|
| PHPStan | Level 9 minimum |
| PHP-CS-Fixer | `@PER-CS` zero violations |
| DTOs/VOs | No array params/returns for structured data |
| Enums | Backed enums for fixed value sets |
