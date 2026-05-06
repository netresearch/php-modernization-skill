# API Platform × PHP Modernization: Edges Only

This document covers only the edges where modern PHP features and API Platform interact. For API Platform usage, see https://api-platform.com/docs/.

API Platform is API-first, attribute-driven, and built on Symfony. The modernization patterns most likely to interact with it are: `final readonly` classes, constructor promotion, attribute-based configuration, PSR-3 logging, PHP 8 attributes for validation, and the strict separation between mutable Doctrine entities and immutable API resources.

## API Resources as Immutable DTOs

An API resource declared with `#[ApiResource]` is, in the recommended pattern, a DTO — not a Doctrine entity. DTOs have no internal state evolution, no Doctrine reflection-based hydration, and no proxy generation. That makes them ideal candidates for `final readonly class` (PHP 8.2+).

```php
use ApiPlatform\Metadata\ApiResource;
use ApiPlatform\Metadata\Get;
use ApiPlatform\Metadata\GetCollection;

#[ApiResource(
    operations: [
        new Get(uriTemplate: '/books/{id}'),
        new GetCollection(uriTemplate: '/books'),
    ],
    provider: BookOutputProvider::class,
)]
final readonly class BookOutput
{
    public function __construct(
        public string $id,
        public string $title,
        public string $author,
        public \DateTimeImmutable $publishedAt,
    ) {}
}
```

Distinction: a Doctrine entity (`#[ORM\Entity]`) must NOT be `readonly` — Doctrine bypasses the constructor and writes via reflection, which `readonly` blocks. See `references/immutability-boundaries.md` for the full explanation. The pattern below ("Doctrine entity vs API Resource separation") shows how to keep both correct.

## Input/Output DTOs and the Symfony Serializer Interaction

When an `#[ApiResource]` declares separate `input:` / `output:` classes, those classes should be DTOs — not arrays.

Before (array-based input, no type guarantees):

```php
#[ApiResource(
    operations: [new Post(uriTemplate: '/books')],
    // no input class — body deserializes to array, then a processor extracts keys
)]
class Book
{
    // ...
}
```

After (DTO-based input, full type safety, validated):

```php
final readonly class CreateBookInput
{
    public function __construct(
        public string $title,
        public string $author,
        public \DateTimeImmutable $publishedAt,
    ) {}
}

#[ApiResource(
    operations: [
        new Post(
            uriTemplate: '/books',
            input: CreateBookInput::class,
            output: BookOutput::class,
            processor: CreateBookProcessor::class,
        ),
    ],
)]
final readonly class BookOutput { /* ... */ }
```

The Symfony Serializer hydrates `CreateBookInput` from the request body. Because all properties are constructor-promoted and `readonly`, the deserializer must use a constructor-based denormalizer — which is the default in modern Symfony Serializer versions (`ObjectNormalizer` calls the constructor when properties are typed and promoted). Validate that the denormalizer used in your project supports constructor-based hydration; if you target Symfony 6.4+ / 7.x this is the default.

## State Providers and Processors as PHP 8 Services

`ProviderInterface` (read) and `ProcessorInterface` (write) implementations are plain Symfony services. They should use constructor injection only — never `new` or service-locator patterns for dependencies — and benefit from `final readonly` themselves.

```php
use ApiPlatform\Metadata\Operation;
use ApiPlatform\State\ProcessorInterface;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;

/**
 * @implements ProcessorInterface<CreateBookInput, BookOutput>
 */
final readonly class CreateBookProcessor implements ProcessorInterface
{
    public function __construct(
        private EntityManagerInterface $em,
        private LoggerInterface $logger,
    ) {}

    public function process(
        mixed $data,
        Operation $operation,
        array $uriVariables = [],
        array $context = [],
    ): BookOutput {
        \assert($data instanceof CreateBookInput);

        $entity = Book::register($data->title, $data->author, $data->publishedAt);
        $this->em->persist($entity);
        $this->em->flush();

        $this->logger->info('Book created', ['id' => $entity->id()]);

        return new BookOutput(
            id: (string) $entity->id(),
            title: $entity->title(),
            author: $entity->author(),
            publishedAt: $entity->publishedAt(),
        );
    }
}
```

Type the PSR-3 `LoggerInterface` parameter, not Monolog's concrete `Logger`. The processor is `final readonly` — it has no mutable state and no inheritance contract. Symfony autowires it via constructor.

## Filters with Attribute-based Configuration

API Platform filters configured via `#[ApiFilter(...)]` go on the resource class or directly on individual properties.

```php
use ApiPlatform\Doctrine\Orm\Filter\SearchFilter;
use ApiPlatform\Doctrine\Orm\Filter\OrderFilter;
use ApiPlatform\Metadata\ApiFilter;
use ApiPlatform\Metadata\ApiResource;

#[ApiResource]
#[ApiFilter(OrderFilter::class, properties: ['title', 'publishedAt'])]
final readonly class BookOutput
{
    public function __construct(
        public string $id,

        #[ApiFilter(SearchFilter::class, strategy: 'ipartial')]
        public string $title,

        #[ApiFilter(SearchFilter::class, strategy: 'exact')]
        public string $author,

        public \DateTimeImmutable $publishedAt,
    ) {}
}
```

PHP 8.4 property hooks would, in principle, allow computed/validated properties on the resource — but API Platform's filter introspection reads the declared property type, not the hook return type. For filtered properties, prefer plain promoted properties; reserve hooks for non-filtered derived state. Verify against your API Platform version (3.4+ has improved property metadata handling but hooks remain conservative).

## Validation with PHP 8 Attributes

Symfony Validator constraints are PHP 8 attributes. They compose cleanly with constructor promotion and `readonly` on input DTOs that double as the validated payload.

```php
use Symfony\Component\Validator\Constraints as Assert;

final readonly class CreateBookInput
{
    public function __construct(
        #[Assert\NotBlank]
        #[Assert\Length(min: 1, max: 255)]
        public string $title,

        #[Assert\NotBlank]
        public string $author,

        #[Assert\NotNull]
        public \DateTimeImmutable $publishedAt,

        #[Assert\Email]
        #[Assert\NotBlank]
        public string $contactEmail,
    ) {}
}
```

API Platform invokes the validator on the deserialized input before passing it to the processor. Constraint violations surface as a `422 Unprocessable Entity` response with a Hydra-formatted error payload — no manual validation in the processor required. See `references/request-dtos.md` for the broader request-DTO pattern; this is the API-Platform-specific application of it.

## Doctrine Entity vs API Resource Separation

The cleanest pattern: keep mutable Doctrine entities, expose immutable API resources, map between them in a state provider/processor. This isolates the persistence model from the API contract — schema can evolve without breaking clients, and the API resource can expose a different shape than the row.

```php
// Persistence: mutable, Doctrine-managed.
#[ORM\Entity]
class Book
{
    #[ORM\Id, ORM\GeneratedValue, ORM\Column]
    private ?int $id = null;

    public function __construct(
        #[ORM\Column] private string $title,
        #[ORM\Column] private string $author,
        #[ORM\Column] private \DateTimeImmutable $publishedAt,
    ) {}

    public function id(): ?int { return $this->id; }
    public function title(): string { return $this->title; }
    public function author(): string { return $this->author; }
    public function publishedAt(): \DateTimeImmutable { return $this->publishedAt; }
}

// API contract: immutable, no Doctrine annotations.
#[ApiResource(provider: BookOutputProvider::class)]
final readonly class BookOutput
{
    public function __construct(
        public string $id,
        public string $title,
        public string $author,
        public \DateTimeImmutable $publishedAt,
    ) {}
}

// Provider: maps entity → resource at the boundary.
final readonly class BookOutputProvider implements ProviderInterface
{
    public function __construct(private BookRepository $books) {}

    public function provide(Operation $operation, array $uriVariables = [], array $context = []): object|array|null
    {
        $entity = $this->books->find($uriVariables['id'] ?? null);
        return $entity === null ? null : new BookOutput(
            id: (string) $entity->id(),
            title: $entity->title(),
            author: $entity->author(),
            publishedAt: $entity->publishedAt(),
        );
    }
}
```

See `references/doctrine-modernization-edges.md` for why entities cannot be `readonly` and how to factor invariants into factory methods.

## `#[ApiResource]` and the readonly Trap

A common shortcut: put `#[ApiResource]` directly on the Doctrine entity and skip the DTO. It works — and for a thin CRUD service it can be a reasonable trade-off. But:

- The class **cannot** be `final readonly` — Doctrine bypasses the constructor on hydration. See `references/immutability-boundaries.md`.
- Schema evolution is now an API breaking change.
- Filters, normalization groups, and serialization context all live on a class that also has to satisfy ORM constraints.

If your API resource IS the Doctrine entity, accept that the class stays mutable and non-`readonly`. If your API resource is a DTO mapped from an entity (the recommended pattern above), it should be `final readonly`. Cross-link: `references/immutability-boundaries.md` lists this as one of the four scenarios where `readonly` is incorrect.

## Async / Mercure / Message Handlers

When a processor publishes a Mercure update or dispatches a Symfony Messenger message, the payload should be a `final readonly` event DTO — never an array, never the entity itself. PSR-14-style event objects are the right shape.

```php
final readonly class BookCreated
{
    public function __construct(
        public string $bookId,
        public string $title,
        public \DateTimeImmutable $occurredAt,
    ) {}
}

// Inside the processor, after persistence:
$this->messageBus->dispatch(new BookCreated(
    bookId: (string) $entity->id(),
    title: $entity->title(),
    occurredAt: new \DateTimeImmutable(),
));
```

Messenger serializes the message for transport (when using AMQP/Redis/SQS); a `readonly` constructor-promoted class round-trips cleanly through Symfony's default Messenger serializer. Avoid passing the Doctrine entity itself across the bus — proxy state, lazy collections, and identity-map assumptions do not survive serialization.

## Summary

The PHP modernization patterns most likely to collide with API Platform are: `final readonly` (correct on resources/DTOs/events, incorrect when the resource IS the entity), constructor injection (the only acceptable shape for providers/processors), and the input/output DTO split (typed classes, never arrays). Apply each pattern at the right boundary:

- API resource as DTO → `final readonly`
- Input / Output DTOs → `final readonly` with `#[Assert\*]` attributes
- State providers / processors → `final readonly` services, constructor-injected, PSR-3 logger
- Doctrine entity exposed as resource → mutable, non-`readonly`, accept the trade-off
- Event/message payloads → `final readonly`, never the entity
