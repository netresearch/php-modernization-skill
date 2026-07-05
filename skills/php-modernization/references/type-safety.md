# Type Safety Patterns in PHP

## Strict Types Declaration

```php
<?php

declare(strict_types=1);

// This MUST be the first statement in every file
// Enables strict type checking for function arguments and returns
```

## Generic Collections with PHPDoc

### ArrayTypeHelper Implementation

```php
<?php

declare(strict_types=1);

namespace App\Util;

/**
 * Provides type-safe array operations with PHPStan generic support.
 *
 * @phpstan-type NonEmptyArrayOf<T> non-empty-array<int|string, T>
 */
final class ArrayTypeHelper
{
    /**
     * Ensures all array items are instances of the given type.
     *
     * @template T of object
     * @param array<mixed> $items
     * @param class-string<T> $type
     * @return array<T>
     * @throws \InvalidArgumentException
     */
    public static function ensureArrayOf(array $items, string $type): array
    {
        foreach ($items as $key => $item) {
            if (!$item instanceof $type) {
                throw new \InvalidArgumentException(sprintf(
                    'Expected instance of %s at key "%s", got %s',
                    $type,
                    $key,
                    get_debug_type($item)
                ));
            }
        }

        /** @var array<T> $items */
        return $items;
    }

    /**
     * Filters array to only items of given type.
     *
     * @template T of object
     * @param array<mixed> $items
     * @param class-string<T> $type
     * @return array<T>
     */
    public static function filterByType(array $items, string $type): array
    {
        $filtered = array_filter($items, static fn($item): bool => $item instanceof $type);

        /** @var array<T> $filtered */
        return $filtered;
    }

    /**
     * @param array<mixed> $items
     * @return array<string>
     */
    public static function ensureStringArray(array $items): array
    {
        return array_map(static function (mixed $item): string {
            if (!is_string($item)) {
                throw new \InvalidArgumentException(sprintf(
                    'Expected string, got %s',
                    get_debug_type($item)
                ));
            }
            return $item;
        }, $items);
    }

    /**
     * @param array<mixed> $items
     * @return array<int>
     */
    public static function ensureIntArray(array $items): array
    {
        return array_map(static function (mixed $item): int {
            if (!is_int($item)) {
                throw new \InvalidArgumentException(sprintf(
                    'Expected int, got %s',
                    get_debug_type($item)
                ));
            }
            return $item;
        }, $items);
    }

    /**
     * @template T
     * @param array<T> $items
     * @return T
     * @throws \InvalidArgumentException
     */
    public static function first(array $items): mixed
    {
        if (empty($items)) {
            throw new \InvalidArgumentException('Array is empty');
        }
        return reset($items);
    }

    /**
     * @template T
     * @param array<T> $items
     * @return T|null
     */
    public static function firstOrNull(array $items): mixed
    {
        return empty($items) ? null : reset($items);
    }
}
```

### Typed Collection Classes

```php
<?php

declare(strict_types=1);

namespace App\Collection;

/**
 * @template T
 * @implements \IteratorAggregate<int, T>
 */
abstract class TypedCollection implements \IteratorAggregate, \Countable
{
    /** @var array<int, T> */
    protected array $items = [];

    /**
     * @param array<T> $items
     */
    public function __construct(array $items = [])
    {
        foreach ($items as $item) {
            $this->add($item);
        }
    }

    /**
     * @param T $item
     */
    abstract public function add(mixed $item): void;

    /**
     * @return class-string<T>
     */
    abstract protected function getType(): string;

    /**
     * @return \ArrayIterator<int, T>
     */
    public function getIterator(): \ArrayIterator
    {
        return new \ArrayIterator($this->items);
    }

    public function count(): int
    {
        return count($this->items);
    }

    /**
     * @return array<int, T>
     */
    public function toArray(): array
    {
        return $this->items;
    }

    /**
     * @template U
     * @param callable(T): U $callback
     * @return array<int, U>
     */
    public function map(callable $callback): array
    {
        return array_map($callback, $this->items);
    }

    /**
     * @param callable(T): bool $callback
     * @return static
     */
    public function filter(callable $callback): static
    {
        $filtered = array_filter($this->items, $callback);
        return new static(array_values($filtered));
    }
}

// Concrete implementation
/**
 * @extends TypedCollection<User>
 */
final class UserCollection extends TypedCollection
{
    public function add(mixed $item): void
    {
        if (!$item instanceof User) {
            throw new \InvalidArgumentException('Expected User instance');
        }
        $this->items[] = $item;
    }

    protected function getType(): string
    {
        return User::class;
    }

    /**
     * @return array<string>
     */
    public function getEmails(): array
    {
        return $this->map(fn(User $user): string => $user->getEmail());
    }
}
```

## PHPDoc Type Annotations

### Array Shapes

```php
/**
 * @param array{
 *     name: string,
 *     email: string,
 *     age?: int,
 *     roles: array<string>
 * } $data
 */
public function createUser(array $data): User
{
    return new User(
        name: $data['name'],
        email: $data['email'],
        age: $data['age'] ?? null,
        roles: $data['roles'],
    );
}

/**
 * @return array{
 *     total: int,
 *     items: array<int, Product>,
 *     pagination: array{page: int, perPage: int, pages: int}
 * }
 */
public function getPaginatedProducts(int $page, int $perPage): array
{
    // ...
}
```

### Callable Types

```php
/**
 * @param callable(User): bool $filter
 * @return array<User>
 */
public function filterUsers(callable $filter): array
{
    return array_filter($this->users, $filter);
}

/**
 * @param callable(int, int): int $comparator
 */
public function sortBy(callable $comparator): void
{
    usort($this->items, $comparator);
}

/**
 * @param \Closure(Request): Response $handler
 */
public function handle(\Closure $handler): Response
{
    return $handler($this->request);
}
```

### Generic Templates

```php
/**
 * @template T
 */
interface RepositoryInterface
{
    /**
     * @param int $id
     * @return T|null
     */
    public function find(int $id): ?object;

    /**
     * @return array<T>
     */
    public function findAll(): array;

    /**
     * @param T $entity
     */
    public function save(object $entity): void;
}

/**
 * @implements RepositoryInterface<User>
 */
class UserRepository implements RepositoryInterface
{
    public function find(int $id): ?User
    {
        // ...
    }

    /** @return array<User> */
    public function findAll(): array
    {
        // ...
    }

    public function save(object $entity): void
    {
        assert($entity instanceof User);
        // ...
    }
}
```

## Assertions and Guards

### Type Guards

```php
final class TypeGuard
{
    /**
     * @template T of object
     * @param mixed $value
     * @param class-string<T> $type
     * @return T
     * @throws \InvalidArgumentException
     */
    public static function instanceOf(mixed $value, string $type): object
    {
        if (!$value instanceof $type) {
            throw new \InvalidArgumentException(sprintf(
                'Expected %s, got %s',
                $type,
                get_debug_type($value)
            ));
        }
        return $value;
    }

    /**
     * @param mixed $value
     * @return non-empty-string
     */
    public static function nonEmptyString(mixed $value): string
    {
        if (!is_string($value) || $value === '') {
            throw new \InvalidArgumentException('Expected non-empty string');
        }
        return $value;
    }

    /**
     * @param mixed $value
     * @return positive-int
     */
    public static function positiveInt(mixed $value): int
    {
        if (!is_int($value) || $value <= 0) {
            throw new \InvalidArgumentException('Expected positive integer');
        }
        return $value;
    }

    /**
     * @template T
     * @param T|null $value
     * @return T
     */
    public static function notNull(mixed $value): mixed
    {
        if ($value === null) {
            throw new \InvalidArgumentException('Value cannot be null');
        }
        return $value;
    }
}
```

### Runtime Assertions

```php
// Using assert() for development checks
public function process(array $items): void
{
    assert(count($items) > 0, 'Items array cannot be empty');
    assert(array_is_list($items), 'Items must be a list');

    foreach ($items as $item) {
        assert($item instanceof ProcessableInterface);
        $item->process();
    }
}

// Using assertions in production (recommended approach)
public function processStrict(array $items): void
{
    if (count($items) === 0) {
        throw new \InvalidArgumentException('Items array cannot be empty');
    }

    foreach ($items as $item) {
        if (!$item instanceof ProcessableInterface) {
            throw new \TypeError('All items must implement ProcessableInterface');
        }
        $item->process();
    }
}
```

## Value Objects with Type Safety

```php
readonly class Email
{
    private function __construct(
        public string $value,
    ) {}

    public static function fromString(string $email): self
    {
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new \InvalidArgumentException("Invalid email: $email");
        }
        return new self(strtolower($email));
    }

    public function equals(self $other): bool
    {
        return $this->value === $other->value;
    }

    public function getDomain(): string
    {
        return substr($this->value, strpos($this->value, '@') + 1);
    }
}

readonly class Money
{
    private function __construct(
        public int $cents,
        public string $currency,
    ) {}

    public static function fromCents(int $cents, string $currency = 'EUR'): self
    {
        if ($cents < 0) {
            throw new \InvalidArgumentException('Amount cannot be negative');
        }
        return new self($cents, strtoupper($currency));
    }

    public static function fromDecimal(float $amount, string $currency = 'EUR'): self
    {
        return self::fromCents((int) round($amount * 100), $currency);
    }

    public function add(self $other): self
    {
        if ($this->currency !== $other->currency) {
            throw new \InvalidArgumentException('Cannot add different currencies');
        }
        return new self($this->cents + $other->cents, $this->currency);
    }

    public function toDecimal(): float
    {
        return $this->cents / 100;
    }
}
```

## Embedding/Vector Type Annotations

When processing JSON arrays (e.g., LLM embedding vectors), use `list<float>` not `array<string, float>`:

```php
// If $rawData has string keys, this creates an associative array.
$embedding = array_map(fn($v): float => (float) $v, $rawData);

// array_values() ensures a list by re-indexing to sequential integer keys.
// Use assertions for type narrowing instead of @var annotations.
$embedding = array_values(array_map(fn($v): float => (float) $v, $rawData));
assert(array_is_list($embedding));
```

PHPStan at level 10 distinguishes between `array<string, float>` and `list<float>`. JSON arrays always have integer keys.

## Return Type Narrowing

```php
interface EntityInterface
{
    public function getId(): int;
}

abstract class AbstractRepository
{
    /**
     * @return EntityInterface|null
     */
    abstract public function find(int $id): ?EntityInterface;
}

/**
 * Concrete implementation narrows return type
 */
class UserRepository extends AbstractRepository
{
    public function find(int $id): ?User  // Narrowed from EntityInterface
    {
        return $this->entityManager->find(User::class, $id);
    }

    /**
     * @return array<User>  // Specific type, not EntityInterface[]
     */
    public function findByRole(string $role): array
    {
        return $this->entityManager
            ->getRepository(User::class)
            ->findBy(['role' => $role]);
    }
}
```

## JSON: Empty Object vs. Empty Array

PHP conflates `[]` (empty array) and `{}` (empty object) in ways that break
strict JSON consumers — LLM tool-calling APIs (OpenAI, Ollama), JSON Schema
validators, and any peer that distinguishes the two types.

**Two traps, one root cause — `[]` and `{}` are the same empty PHP array:**

```php
// Trap 1 — encoding: an empty PHP array becomes a JSON array, never an object.
json_encode([]);                       // "[]"   ← NOT "{}"
json_encode(['properties' => []]);     // {"properties":[]}  ← invalid where an object is required

// Trap 2 — decoding with associative=true collapses an empty object to [].
json_decode('{}', true);               // []     (array)  ← type is now wrong
json_decode('{}', true) === [];        // true
json_decode('{}');                     // stdClass {}  (object)  ← preserved
```

A JSON Schema `properties` block, or a tool call's `arguments`, MUST serialize
as `{}` when empty. Sending `[]` gets the whole request rejected — Ollama, for
example, returns HTTP 400 `Value looks like object, but can't find closing '}'
symbol`.

**Rules:**

- For a field that must be a JSON **object**, represent "empty" as
  `new \stdClass()` (or `(object) []`), not `[]`. Normalize at the value's
  construction site so every serialization path is correct:

  ```php
  if (($schema['properties'] ?? null) === []) {
      $schema['properties'] = new \stdClass();   // serializes as {}
  }
  ```

- When a decoded value must **round-trip** as an object, decode with
  `json_decode($json)` (objects) — not `json_decode($json, true)` (which turns
  an empty `{}` into `[]` and re-encodes it wrong on the next hop).

- Prefer normalizing in a **shared value object's constructor** over each
  provider/serializer: adapters that read the raw property directly (not via a
  `toArray()`) then get the correct type too, and `fromArray(toArray())` stays
  idempotent:

  ```php
  public function __construct(array|object $properties)
  {
      // Empty array would serialize as []; force an empty object to {}.
      $this->properties = $properties === [] ? new \stdClass() : (object) $properties;
  }
  ```

**Symptom to recognize:** an intermittent-looking 4xx from a JSON API that
actually correlates with *which optional/empty field is present* (e.g. only
fails when a parameterless tool is offered) — not with timing or connections.
