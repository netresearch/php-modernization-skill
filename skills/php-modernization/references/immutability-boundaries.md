# Immutability Boundaries: When `readonly` Is Wrong

The `php-modernization` skill recommends `final readonly class` for data-shaped classes. That recommendation is correct for DTOs, value objects, and events. It is wrong for entities, form-bound models, and most deserialization targets. This document draws the line.

## What `readonly` Actually Does

PHP supports two forms:

- **Property-level `readonly`** (PHP 8.1+): the property may be initialized exactly once, only from inside the declaring class scope.
- **Class-level `readonly`** (PHP 8.2+): every declared property is implicitly `readonly`. The class additionally cannot declare static or untyped properties, and cannot use dynamic properties.

Both forms enforce single-assignment at runtime. The constraints cannot be lifted by:

- Reflection (`ReflectionProperty::setValue` throws on a readonly property after initialization).
- Cloning (clones inherit the initialized state; you must implement `__clone` with a wither pattern to "change" values).
- `unserialize()` (PHP 8.3 added `__unserialize` support that respects readonly via reflection on uninitialized clones, but the constraint is still single-assignment).
- Inheritance (a child class cannot redeclare a readonly property to drop the modifier).

References:
- RFC: https://wiki.php.net/rfc/readonly_properties_v2
- RFC: https://wiki.php.net/rfc/readonly_classes

## Where `readonly` Is Correct

### DTO (request/response shape)

```php
final readonly class CreateUserRequest
{
    public function __construct(
        public string $email,
        public string $name,
        /** @var list<string> */
        public array $roles,
    ) {}
}
```

### Value object

```php
final readonly class Money
{
    public function __construct(
        public int $cents,
        public string $currency,
    ) {}

    public function add(self $other): self
    {
        if ($this->currency !== $other->currency) {
            throw new \DomainException('currency mismatch');
        }
        return new self($this->cents + $other->cents, $this->currency);
    }
}
```

### Domain event

```php
final readonly class OrderShipped
{
    public function __construct(
        public string $orderId,
        public \DateTimeImmutable $occurredAt,
        public string $carrier,
    ) {}
}
```

These all share a property: the object is constructed once, fully populated by the constructor, and never modified.

## Where `readonly` Is Incorrect — and Why

### Doctrine entities

Doctrine ORM hydrates entities by:

1. Creating the instance **without calling the constructor** (via `ReflectionClass::newInstanceWithoutConstructor()` or, in newer versions, instantiator libraries).
2. Assigning each mapped property via reflection.

Step 2 fails on a `readonly` property after the proxy has been initialized — and even on first hydration, Doctrine relies on being able to write properties at any point during the unit-of-work lifecycle (re-loading, refresh, lazy proxy initialization).

```php
#[ORM\Entity]
final readonly class User // BROKEN
{
    public function __construct(
        #[ORM\Id, ORM\Column]
        public int $id,
        #[ORM\Column]
        public string $email,
    ) {}
}

// On EntityManager::find(User::class, 1):
// Error: Cannot modify readonly property User::$id
```

The correct shape: a non-readonly entity, with private or protected setters that enforce invariants.

```php
#[ORM\Entity]
class User
{
    #[ORM\Id, ORM\GeneratedValue, ORM\Column]
    private ?int $id = null;

    public function __construct(
        #[ORM\Column(unique: true)]
        private string $email,
    ) {}

    public function id(): ?int { return $this->id; }
    public function email(): string { return $this->email; }
}
```

### Form-bound models (Symfony Form)

Symfony Form's default data mapper writes into the bound object using property accessors (`PropertyAccess`). It needs either public writable properties or matching `setX()` methods. A `readonly` property has neither.

You can work around this with `'mapped' => false` plus manual hydration into a DTO, but at that point the form binds to a DTO and the entity is updated by a separate command/use case. That is the pattern to prefer — but the entity itself must remain mutable.

### Deserialization targets

- **Symfony Serializer**: by default uses constructor + property writes. Readonly works *only* if every property is set via the constructor and the serializer is configured to use constructor arguments (`AbstractNormalizer::OBJECT_CREATION_FROM_CONSTRUCTOR` / explicit constructor argument resolution). For partial payloads, this becomes brittle.
- **JMS Serializer**: bypasses the constructor by default, then assigns via reflection. Incompatible with `readonly` unless reconfigured per class.
- **Generic ObjectMapper / hand-rolled hydrators**: same pattern; check whether they use constructor-only mode.

Treat readonly DTOs as deserialization targets *only* when you control the deserializer and have proven it goes through the constructor.

### `__unserialize` and session-restored objects

`unserialize()` reconstructs objects by allocating without calling the constructor and then writing properties. PHP 8.3+ tolerates readonly inside `__unserialize`, but only because the engine treats the object as freshly allocated. If you rely on the default `serialize`/`unserialize` magic on a readonly class without `__unserialize`, behavior depends on PHP version — verify before assuming it works.

### Test doubles and mocks

PHPUnit's `getMockBuilder()` and Mockery generate subclasses. `final` blocks subclassing entirely. `readonly` constraints propagate to the subclass. Combined, `final readonly class` is hard to mock.

Mitigations:
- Mock against an interface, not the concrete class. The interface stays mockable; the implementation can stay `final readonly`.
- Use `bovigo/assert` or hand-rolled stubs for value objects (usually you don't need to mock a VO — just construct one).
- For PHPUnit 10+, `createStub()` on an interface is the standard path.

## Decision Matrix

| Class purpose                   | readonly?  | final?       | Notes                                                      |
| ------------------------------- | ---------- | ------------ | ---------------------------------------------------------- |
| DTO / Request DTO               | yes        | yes          | Pure data, immutable                                       |
| Value object (Money, Email)     | yes        | yes          | Identity = value                                           |
| Domain event                    | yes        | yes          | Fact, never mutates                                        |
| Command / Query (CQRS message)  | yes        | yes          | Bus payload                                                |
| Immutable configuration object  | yes        | yes          | Built once at boot                                         |
| Doctrine entity                 | no         | usually no   | Hydration writes properties post-construct                 |
| Form-bound model                | no         | depends      | Form binding requires settable properties                  |
| Service / use case              | no needed  | yes usually  | Stateless behavior; final unless extension is a use case   |
| Aggregate root (event-sourced)  | depends    | yes          | If reconstructed via `apply(Event)`, can be readonly with care |
| Test double target              | no         | no           | Or mock against an interface                               |

## Migration Patterns When You Want Both

### Embed an immutable VO in a mutable entity

```php
#[ORM\Entity]
class Order
{
    #[ORM\Embedded(class: Money::class)]
    private Money $total;

    public function __construct(Money $total)
    {
        $this->total = $total;
    }

    public function reprice(Money $newTotal): void
    {
        $this->total = $newTotal; // entity is mutable; Money stays readonly
    }

    public function total(): Money { return $this->total; }
}
```

### Bind form to DTO, then map onto entity

```php
final readonly class UpdateUserRequest
{
    public function __construct(
        public string $email,
        public string $name,
    ) {}
}

final class UpdateUserHandler
{
    public function __construct(private EntityManagerInterface $em) {}

    public function __invoke(int $userId, UpdateUserRequest $request): void
    {
        $user = $this->em->find(User::class, $userId)
            ?? throw new \RuntimeException('user not found');

        $user->changeEmail($request->email);
        $user->rename($request->name);

        $this->em->flush();
    }
}
```

The form binds to `UpdateUserRequest` (readonly). The handler mutates the entity through intent-revealing methods. The entity stays writable.

## Property Hooks (PHP 8.4) as Middle Ground

PHP 8.4 introduces property hooks (RFC: https://wiki.php.net/rfc/property-hooks). They let a single property expose controlled mutation without the whole class becoming a free-for-all of public setters.

```php
class User
{
    public string $email {
        set(string $value) {
            if (!filter_var($value, FILTER_VALIDATE_EMAIL)) {
                throw new \DomainException('invalid email');
            }
            $this->email = strtolower($value);
        }
    }
}
```

For entities and form-bound models, property hooks are a cleaner alternative to writing explicit setter methods. The class is still mutable (Doctrine and Symfony Form can still write to it), but invariants are enforced at the assignment site.

See `references/php-8.4.md` for the full property-hooks reference.

## Summary

`readonly` is a tool for shapes that are constructed once and observed many times. It is not a tool for shapes that are loaded from a database, populated by a form, or restored from a serialized payload. Apply it where the lifecycle matches; reach for property hooks, private setters, or intent-revealing methods where it does not.
