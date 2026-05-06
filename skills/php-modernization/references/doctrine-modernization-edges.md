# Doctrine ORM × PHP Modernization: Edges Only

This document covers only the edges where modern PHP features and Doctrine ORM interact. It is **not** a Doctrine guide. For Doctrine ORM usage — mapping, DQL, query builder, schema management, migrations — consult the official documentation at https://www.doctrine-project.org/projects/orm.html.

## Doctrine ORM 3.x Baseline Expectations

Doctrine ORM 3.x (released April 2024) closed off several legacy extension paths that modern PHP code commonly relied on. Before applying modernization patterns, confirm you are working against 3.x and not 2.x.

### `EntityRepository` is no longer extended by inheritance

In ORM 2.x, the typical pattern was to subclass `EntityRepository`:

```php
// 2.x style — works in 2.x, not the modern recommended path
class UserRepository extends EntityRepository
{
    public function findActive(): array
    {
        return $this->findBy(['active' => true]);
    }
}
```

In ORM 3.x, this still compiles, but the `EntityRepository` is increasingly closed and the recommended pattern is composition or — in Symfony — `ServiceEntityRepository`:

```php
use Doctrine\Persistence\ManagerRegistry;
use Doctrine\Bundle\DoctrineBundle\Repository\ServiceEntityRepository;

/**
 * @extends ServiceEntityRepository<User>
 */
final class UserRepository extends ServiceEntityRepository
{
    public function __construct(ManagerRegistry $registry)
    {
        parent::__construct($registry, User::class);
    }

    /** @return list<User> */
    public function findActive(): array
    {
        return $this->findBy(['active' => true]);
    }
}
```

For non-Symfony projects, prefer composition: inject `EntityManagerInterface`, call `getRepository(User::class)`, and wrap the result in a domain-specific class that exposes only intent-revealing methods.

## PHP 8 Attribute Mappings

Doctrine ORM 3.x is attribute-first. Annotations are removed; XML and YAML are still supported for legacy projects but attributes are the modernization target.

### Migration from annotations

```php
// Before (annotations, ORM 2.x)
/**
 * @ORM\Entity
 * @ORM\Table(name="users")
 */
class User
{
    /**
     * @ORM\Id
     * @ORM\GeneratedValue
     * @ORM\Column(type="integer")
     */
    private ?int $id = null;

    /**
     * @ORM\Column(type="string", length=255, unique=true)
     */
    private string $email;
}
```

```php
// After (attributes, ORM 3.x)
use Doctrine\ORM\Mapping as ORM;

#[ORM\Entity]
#[ORM\Table(name: 'users')]
class User
{
    #[ORM\Id]
    #[ORM\GeneratedValue]
    #[ORM\Column]
    private ?int $id = null;

    #[ORM\Column(length: 255, unique: true)]
    private string $email;
}
```

Note that `type` is often inferable from the property type declaration in 3.x, so explicit `type:` attributes are usually redundant.

Rector has a ready set: `Rector\Doctrine\Set\DoctrineSetList::ANNOTATIONS_TO_ATTRIBUTES`.

## Embeddables as PHP Value Objects

`#[ORM\Embeddable]` lets a value object live as a set of columns on the parent entity, without a separate table. This is the bridge between immutable VOs (which the modernization skill recommends) and mutable entities (which Doctrine requires).

```php
#[ORM\Embeddable]
final readonly class Money
{
    public function __construct(
        #[ORM\Column]
        public int $cents,
        #[ORM\Column(length: 3)]
        public string $currency,
    ) {}
}

#[ORM\Entity]
class Order
{
    #[ORM\Id, ORM\GeneratedValue, ORM\Column]
    private ?int $id = null;

    #[ORM\Embedded(class: Money::class)]
    private Money $total;

    public function __construct(Money $total)
    {
        $this->total = $total;
    }

    public function total(): Money { return $this->total; }

    public function reprice(Money $newTotal): void
    {
        $this->total = $newTotal;
    }
}
```

Doctrine instantiates the embeddable via reflection too, so it bypasses the constructor on hydration. `final readonly` works here because Doctrine's reflection-based property assignment treats the embeddable's properties as part of the parent entity's hydration lifecycle — and embeddables are never re-hydrated independently. Verify on your Doctrine version (this has historically been a moving target; on ORM 3.x with PHP 8.2+ it is supported).

## Lazy Proxies vs PHP 8.4 Native Lazy Objects

Doctrine has used generated proxy classes for lazy loading since ORM 2.x. The proxy is a subclass of the entity that intercepts property access and triggers loading. Two consequences:

- The entity must not be `final`, because the proxy needs to extend it.
- The proxy initializes the entity at the first property access.

PHP 8.4 introduces native lazy objects (RFC: https://wiki.php.net/rfc/lazy-objects). Two flavors:

```php
// Lazy ghost: same instance, initializer fills properties on first access.
$user = $reflClass->newLazyGhost(function (User $user): void {
    $data = $repo->loadRowById($id);
    $user->__construct($data['email']);
});

// Lazy proxy: a proxy object that delegates to a real instance on first access.
$user = $reflClass->newLazyProxy(fn(): User => $repo->find($id));
```

Doctrine ORM does not yet ship a hydrator backed by `newLazyGhost` as the default — but support has been added incrementally (track https://github.com/doctrine/orm/issues for specifics). Today, the practical implications:

- Continue assuming Doctrine's traditional proxy generation. Do not mark entities `final`.
- For your own lazy-loading needs *outside* Doctrine (caching, aggregating, deferred external calls), prefer `newLazyGhost` over hand-rolled proxies — they integrate with reflection, `var_dump`, and serialization correctly.
- When Doctrine releases a version that uses native lazy objects internally, the `final` restriction on entities can be revisited.

## Collections and Immutability

`Doctrine\Common\Collections\Collection` and `ArrayCollection` are mutable by design — entities expose them so Doctrine can track add/remove operations for relationship updates.

Do not expose the `Collection` directly on a public API. Wrap it:

```php
#[ORM\Entity]
class Order
{
    /** @var Collection<int, OrderLine> */
    #[ORM\OneToMany(targetEntity: OrderLine::class, mappedBy: 'order', cascade: ['persist'])]
    private Collection $lines;

    public function __construct()
    {
        $this->lines = new ArrayCollection();
    }

    public function addLine(OrderLine $line): void
    {
        $this->lines->add($line);
    }

    /** @return list<OrderLine> */
    public function lines(): array
    {
        return array_values($this->lines->toArray());
    }
}
```

`lines()` returns a snapshot list. Callers cannot mutate the underlying collection through it. Mutations go through `addLine()` / `removeLine()` so the entity controls invariants.

## The `readonly` Trap

`final readonly class` on a Doctrine entity will fail at hydration. See `references/immutability-boundaries.md` for the full explanation. The short version: Doctrine bypasses the constructor and writes properties via reflection, which `readonly` blocks after first assignment.

Embeddables (above) and DTOs/VOs *outside* the entity graph are the right places for `readonly`. Entities themselves stay mutable.

## Hydration and Constructor Decisions

Doctrine instantiates entities via `ReflectionClass::newInstanceWithoutConstructor()` (or an instantiator library). The constructor is **not called** when an entity is loaded from the database. Three implications:

### Validation in the constructor does not run on load

```php
#[ORM\Entity]
class User
{
    public function __construct(
        #[ORM\Column]
        private string $email,
    ) {
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new \DomainException('invalid email'); // only runs on `new User(...)`
        }
    }
}
```

If the database somehow contains an invalid email (legacy import, manual SQL), the entity loads without complaint. Validation must happen at write boundaries (form, command handler, named factory) or via Doctrine lifecycle callbacks (`#[ORM\PrePersist]`, `#[ORM\PreUpdate]`).

### Factory methods over public constructors

A common pattern: keep the constructor `protected` (so Doctrine can still hydrate via reflection) and expose intent-revealing factories:

```php
#[ORM\Entity]
class User
{
    #[ORM\Id, ORM\GeneratedValue, ORM\Column]
    private ?int $id = null;

    protected function __construct(
        #[ORM\Column(unique: true)]
        private string $email,
        #[ORM\Column]
        private \DateTimeImmutable $registeredAt,
    ) {}

    public static function register(string $email, \DateTimeImmutable $now): self
    {
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new \DomainException('invalid email');
        }
        return new self(strtolower($email), $now);
    }
}
```

`new User(...)` from outside is now blocked at compile time. Doctrine's reflection-based instantiation bypasses the visibility check. Application code goes through `User::register()`, which enforces invariants.

### Private constructors are not safe

`private function __construct()` works in some Doctrine versions but is fragile. Stick with `protected` for compatibility. If a future Doctrine version requires `public`, the change is mechanical.

## Summary

The PHP modernization patterns most likely to collide with Doctrine are: `final`, `readonly`, constructor-based validation, and immutable collections. Apply each modern pattern at the right boundary:

- DTOs, VOs, events, commands → `final readonly`
- Embeddables → `final readonly` (verify per version)
- Entities → mutable, with private/protected setters or property hooks; non-final until lazy-loading goes native
- Repositories → composition or `ServiceEntityRepository<EntityClass>`
- Validation → at the write boundary, not in the entity constructor
