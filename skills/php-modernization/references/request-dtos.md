# Request DTOs and Safe Type Handling

## The Problem with Inline Type Guards

PSR-7 request methods like `getParsedBody()` return `array|object|null`. Inline type guards become scattered and repetitive:

```php
// Anti-pattern: Inline guards everywhere
public function listAction(ServerRequestInterface $request): ResponseInterface
{
    $body = $request->getParsedBody();
    $bodyArray = \is_array($body) ? $body : [];
    $queryParams = $request->getQueryParams();
    $params = array_merge($queryParams, $bodyArray);

    $action = isset($params['action']) && \is_string($params['action'])
        ? $params['action']
        : '';
    $limit = isset($params['limit']) && \is_numeric($params['limit'])
        ? max(1, min(1000, (int) $params['limit']))
        : 100;
    // ... more scattered validation
}
```

**Problems:**
- Validation logic scattered across controller
- Not reusable across endpoints
- Hard to test in isolation
- Type information lost after extraction
- Easy to forget validation

## Solution: Request DTOs

Encapsulate request data extraction and validation in dedicated immutable objects.

### Basic Request DTO

```php
<?php

declare(strict_types=1);

namespace Vendor\Extension\Http;

use DateTimeImmutable;
use Psr\Http\Message\ServerRequestInterface;

/**
 * Immutable DTO for audit filter parameters.
 *
 * Extracts and validates request data in one place.
 */
final readonly class AuditFilterRequest
{
    public function __construct(
        public string $action = '',
        public string $identifier = '',
        public ?DateTimeImmutable $from = null,
        public ?DateTimeImmutable $to = null,
        public int $limit = 100,
        public int $offset = 0,
    ) {}

    /**
     * Factory method - single point of request parsing.
     */
    public static function fromRequest(ServerRequestInterface $request): self
    {
        $params = self::extractParams($request);

        return new self(
            action: self::getString($params, 'action'),
            identifier: self::getString($params, 'identifier'),
            from: self::getDate($params, 'from'),
            to: self::getDate($params, 'to'),
            limit: self::getInt($params, 'limit', 100, 1, 1000),
            offset: self::getInt($params, 'offset', 0, 0, PHP_INT_MAX),
        );
    }

    /**
     * @return array<string, mixed>
     */
    private static function extractParams(ServerRequestInterface $request): array
    {
        $body = $request->getParsedBody();

        return array_merge(
            $request->getQueryParams(),
            match (true) {
                \is_array($body) => $body,
                default => [],
            }
        );
    }

    /**
     * @param array<string, mixed> $params
     */
    private static function getString(array $params, string $key, string $default = ''): string
    {
        $value = $params[$key] ?? $default;

        return \is_string($value) ? trim($value) : $default;
    }

    /**
     * @param array<string, mixed> $params
     */
    private static function getInt(
        array $params,
        string $key,
        int $default,
        int $min,
        int $max,
    ): int {
        $value = $params[$key] ?? null;

        if ($value === null || $value === '') {
            return $default;
        }

        if (!\is_numeric($value)) {
            return $default;
        }

        return max($min, min($max, (int) $value));
    }

    /**
     * @param array<string, mixed> $params
     */
    private static function getDate(array $params, string $key): ?DateTimeImmutable
    {
        $value = $params[$key] ?? null;

        if (!\is_string($value) || $value === '') {
            return null;
        }

        try {
            $date = new DateTimeImmutable($value);
        } catch (\Exception) {
            return null;
        }

        // 2026-02-30 does not throw: it rolls over to 2026-03-02 and only
        // records a warning. See "Safe Date Handling" below.
        $errors = DateTimeImmutable::getLastErrors();
        if ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0)) {
            return null;
        }

        return $date;
    }
}
```

### Using the DTO in Controllers

```php
public function listAction(ServerRequestInterface $request): ResponseInterface
{
    // Single line - all validation done
    $filter = AuditFilterRequest::fromRequest($request);

    // Use typed properties directly
    $entries = $this->auditService->findEntries(
        action: $filter->action,
        identifier: $filter->identifier,
        from: $filter->from,
        to: $filter->to,
        limit: $filter->limit,
        offset: $filter->offset,
    );

    return $this->jsonResponse(['entries' => $entries]);
}
```

### Testing DTOs

DTOs are trivially testable in isolation:

```php
<?php

declare(strict_types=1);

namespace Vendor\Extension\Tests\Unit\Http;

use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Test;
use PHPUnit\Framework\TestCase;
use Psr\Http\Message\ServerRequestInterface;
use Vendor\Extension\Http\AuditFilterRequest;

final class AuditFilterRequestTest extends TestCase
{
    #[Test]
    public function createsWithDefaults(): void
    {
        $request = $this->createRequestWithParams([]);

        $dto = AuditFilterRequest::fromRequest($request);

        self::assertSame('', $dto->action);
        self::assertSame('', $dto->identifier);
        self::assertNull($dto->from);
        self::assertNull($dto->to);
        self::assertSame(100, $dto->limit);
        self::assertSame(0, $dto->offset);
    }

    #[Test]
    public function parsesValidParameters(): void
    {
        $request = $this->createRequestWithParams([
            'action' => 'secret.accessed',
            'identifier' => 'api_key',
            'limit' => '50',
            'from' => '2025-01-01',
        ]);

        $dto = AuditFilterRequest::fromRequest($request);

        self::assertSame('secret.accessed', $dto->action);
        self::assertSame('api_key', $dto->identifier);
        self::assertSame(50, $dto->limit);
        self::assertNotNull($dto->from);
        self::assertSame('2025-01-01', $dto->from->format('Y-m-d'));
    }

    #[Test]
    public function clampsLimitToRange(): void
    {
        $request = $this->createRequestWithParams(['limit' => '9999']);

        $dto = AuditFilterRequest::fromRequest($request);

        self::assertSame(1000, $dto->limit); // Clamped to max
    }

    #[Test]
    public function handlesInvalidDateGracefully(): void
    {
        $request = $this->createRequestWithParams(['from' => 'not-a-date']);

        $dto = AuditFilterRequest::fromRequest($request);

        self::assertNull($dto->from);
    }

    #[Test]
    public function rejectsNonexistentDate(): void
    {
        // Parses without throwing and would silently become 2026-03-02
        $request = $this->createRequestWithParams(['from' => '2026-02-30']);

        $dto = AuditFilterRequest::fromRequest($request);

        self::assertNull($dto->from);
    }

    #[Test]
    public function mergesQueryAndBodyParams(): void
    {
        $request = $this->createMock(ServerRequestInterface::class);
        $request->method('getQueryParams')->willReturn(['action' => 'from-query']);
        $request->method('getParsedBody')->willReturn(['action' => 'from-body']);

        $dto = AuditFilterRequest::fromRequest($request);

        // Body params override query params
        self::assertSame('from-body', $dto->action);
    }

    /**
     * @param array<string, mixed> $params
     */
    private function createRequestWithParams(array $params): ServerRequestInterface
    {
        $request = $this->createMock(ServerRequestInterface::class);
        $request->method('getQueryParams')->willReturn($params);
        $request->method('getParsedBody')->willReturn([]);

        return $request;
    }
}
```

## Safe Integer Handling

### The Overflow Problem

Casting large numeric strings to integers can cause overflow:

```php
// DANGEROUS: Overflow without warning
$uid = (int) '99999999999999999999';  // Results in PHP_INT_MAX or negative!
```

### Solution: String-Based Validation (No bcmath Required)

When bcmath is not available, use string comparison:

```php
/**
 * Safely parse a numeric string to integer, returning null on overflow.
 */
function safeParseInt(string $value): ?int
{
    // Must be non-empty numeric string
    if ($value === '' || !\ctype_digit($value)) {
        return null;
    }

    $maxIntString = (string) PHP_INT_MAX;
    $maxLen = \strlen($maxIntString);
    $valueLen = \strlen($value);

    // Longer than max int = definitely overflow
    if ($valueLen > $maxLen) {
        return null;
    }

    // Same length - string comparison works for same-length numeric strings
    if ($valueLen === $maxLen && \strcmp($value, $maxIntString) > 0) {
        return null;
    }

    return (int) $value;
}
```

### Practical Example: UID Validation

```php
/**
 * Parse "table:field:uid" format safely.
 *
 * @return array{table: string, field: string, uid: int}|null
 */
public function parseFieldReference(string $reference): ?array
{
    $parts = explode(':', $reference);

    if (\count($parts) !== 3) {
        return null;
    }

    [$table, $field, $uidString] = $parts;

    // Validate UID won't overflow
    $uid = $this->safeParseUid($uidString);
    if ($uid === null) {
        return null;
    }

    return [
        'table' => $table,
        'field' => $field,
        'uid' => $uid,
    ];
}

private function safeParseUid(string $uidString): ?int
{
    if ($uidString === '' || !\ctype_digit($uidString)) {
        return null;
    }

    $maxIntString = (string) PHP_INT_MAX;
    $maxLen = \strlen($maxIntString);
    $uidLen = \strlen($uidString);

    if ($uidLen > $maxLen) {
        return null;
    }

    if ($uidLen === $maxLen && \strcmp($uidString, $maxIntString) > 0) {
        return null;
    }

    return (int) $uidString;
}
```

### Why Not bcmath?

`bccomp()` is cleaner but requires the bcmath extension:

```php
// Clean but requires ext-bcmath
if (\bccomp($uidString, (string) PHP_INT_MAX) > 0) {
    return null;
}
```

The string-based approach works without additional extensions, making it suitable for:
- Libraries that shouldn't require optional extensions
- Environments where bcmath isn't installed
- TYPO3 extensions aiming for minimal dependencies

## Safe Date Handling

### A nonexistent date rolls over instead of throwing

`new DateTimeImmutable($value)` throws only when it cannot parse the string. A
string it can parse that names no real date or time is normalised forward, and
the only trace is a warning in `DateTimeImmutable::getLastErrors()`:

| Input | Constructor result | Recorded warning |
|---|---|---|
| `2026-02-30` | `2026-03-02 00:00:00` | `The parsed date was invalid` |
| `2026-04-31` | `2026-05-01 00:00:00` | `The parsed date was invalid` |
| `2026-09-21T24:00:00` | `2026-09-22 00:00:00` | `The parsed time was invalid` |
| `2026-13-01` | throws | — |
| `2026-09-21T25:00:00` | throws | — |

Out-of-range months and hours throw `DateMalformedStringException` on PHP 8.3+
(it extends `DateException`, which extends `Exception`); PHP 8.1 and 8.2 throw
plain `Exception`, so `catch (\Exception)` covers every version. A `try`/`catch`
alone therefore refuses month 13 and hour 25, and accepts February 30th: a
filter asked for `2026-02-30` quietly starts on March 2nd.

### The check: `getLastErrors()` right after the constructor

```php
/**
 * @throws \InvalidArgumentException when $value is not a real calendar date/time
 */
function parseStrictDate(string $value): \DateTimeImmutable
{
    try {
        $date = new \DateTimeImmutable($value);
    } catch (\Exception $e) {
        throw new \InvalidArgumentException('Not a parseable date', 0, $e);
    }

    // First statement after the constructor: the next parse overwrites it.
    $errors = \DateTimeImmutable::getLastErrors();
    if ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0)) {
        if (preg_match('/[T ]24:00/', $value) === 1) {
            throw new \InvalidArgumentException(
                'Write 24:00 as 00:00 of the next day: ' . $date->format('Y-m-d\T00:00:00'),
            );
        }
        throw new \InvalidArgumentException('Not a calendar date');
    }

    return $date;
}
```

- **Refuse when either count is above zero.** From PHP 8.2,
  `getLastErrors()` returns `false` after a clean parse. PHP 8.1 returns an array
  with both counts at `0` instead, so a bare `getLastErrors() !== false` refuses
  every date on 8.1. Checking the counts works on both.
- **Read it immediately.** The state is process-global, shared by `DateTime` and
  `DateTimeImmutable`, and replaced by the next parse: a `new DateTimeImmutable()`
  for "now" between the constructor and the check resets it to clean.
- **Say how to write 24:00.** ISO 8601 allows `24:00` as end of day and users
  send it; a bare "invalid date" leaves them guessing. The rolled-over value
  already holds the next day, so the refusal can name the exact replacement
  (`2026-09-21T24:00:00` → `2026-09-22T00:00:00`).

### `createFromFormat()` fixes the shape, not the range

`DateTimeImmutable::createFromFormat('!Y-m-d', $value)` is the stricter parser:
it returns `false` for anything that does not match the format (the constructor
accepts relative strings such as `next monday`), and the `!` resets the fields
the format does not name to zero — without it the current time of day leaks into
the result. It still rolls over: `2026-02-30` becomes `2026-03-02` and
`2026-13-01` becomes `2027-01-01`, each with a warning and no `false`. Apply the
same `getLastErrors()` check after it.

Verified on PHP 8.1.34, 8.2.33, 8.3.33, 8.4.25 and 8.5.10.

## Command/Query DTOs

For complex operations, separate command and query objects:

### Command DTO (Write Operations)

```php
<?php

declare(strict_types=1);

namespace Vendor\Extension\Command;

/**
 * Command to create a new secret.
 */
final readonly class CreateSecretCommand
{
    public function __construct(
        public string $identifier,
        public string $value,
        public ?string $description = null,
        public ?\DateTimeImmutable $expiresAt = null,
        public bool $frontendAccessible = false,
    ) {
        // Validate on construction
        if ($identifier === '') {
            throw new \InvalidArgumentException('Identifier cannot be empty');
        }
        if ($value === '') {
            throw new \InvalidArgumentException('Value cannot be empty');
        }
    }

    public static function fromRequest(ServerRequestInterface $request): self
    {
        $body = $request->getParsedBody();
        $params = \is_array($body) ? $body : [];

        return new self(
            identifier: self::requireString($params, 'identifier'),
            value: self::requireString($params, 'value'),
            description: self::optionalString($params, 'description'),
            expiresAt: self::optionalDate($params, 'expiresAt'),
            frontendAccessible: self::getBool($params, 'frontendAccessible'),
        );
    }

    /**
     * @param array<string, mixed> $params
     */
    private static function requireString(array $params, string $key): string
    {
        $value = $params[$key] ?? null;

        if (!\is_string($value) || $value === '') {
            throw new \InvalidArgumentException("Missing required field: $key");
        }

        return $value;
    }

    /**
     * @param array<string, mixed> $params
     */
    private static function optionalString(array $params, string $key): ?string
    {
        $value = $params[$key] ?? null;

        return \is_string($value) && $value !== '' ? $value : null;
    }

    /**
     * @param array<string, mixed> $params
     */
    private static function optionalDate(array $params, string $key): ?\DateTimeImmutable
    {
        $value = $params[$key] ?? null;

        if (!\is_string($value) || $value === '') {
            return null;
        }

        try {
            $date = new \DateTimeImmutable($value);
        } catch (\Exception) {
            throw new \InvalidArgumentException("Invalid date format for: $key");
        }

        $errors = \DateTimeImmutable::getLastErrors();
        if ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0)) {
            throw new \InvalidArgumentException("Not a calendar date for: $key");
        }

        return $date;
    }

    /**
     * @param array<string, mixed> $params
     */
    private static function getBool(array $params, string $key): bool
    {
        $value = $params[$key] ?? false;

        return filter_var($value, FILTER_VALIDATE_BOOLEAN);
    }
}
```

### Query DTO (Read Operations)

```php
<?php

declare(strict_types=1);

namespace Vendor\Extension\Query;

/**
 * Query parameters for listing secrets.
 */
final readonly class ListSecretsQuery
{
    public function __construct(
        public ?string $search = null,
        public string $sortBy = 'identifier',
        public string $sortOrder = 'asc',
        public int $limit = 50,
        public int $offset = 0,
    ) {}

    public static function fromRequest(ServerRequestInterface $request): self
    {
        $params = $request->getQueryParams();

        return new self(
            search: self::optionalString($params, 'search'),
            sortBy: self::getEnum($params, 'sortBy', ['identifier', 'created', 'updated'], 'identifier'),
            sortOrder: self::getEnum($params, 'sortOrder', ['asc', 'desc'], 'asc'),
            limit: self::getInt($params, 'limit', 50, 1, 200),
            offset: self::getInt($params, 'offset', 0, 0, PHP_INT_MAX),
        );
    }

    // ... helper methods similar to above
}
```

## Summary

| Pattern | Use Case |
|---------|----------|
| Request DTO | Extract and validate HTTP request data |
| Command DTO | Write operations with required fields |
| Query DTO | Read operations with optional filters |
| Safe Integer Parsing | Prevent overflow without bcmath |
| Safe Date Parsing | Refuse dates PHP rolls over (`2026-02-30`, `24:00`) |

**Benefits:**
- Type safety preserved through entire flow
- Validation in one place
- Easily testable in isolation
- Reusable across controllers
- Self-documenting API
- Immutable by design (`readonly`)
