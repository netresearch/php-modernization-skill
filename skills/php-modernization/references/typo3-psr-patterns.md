# TYPO3-Specific PSR Pattern Implementation

## PSR-3: LoggerAwareInterface Pattern

TYPO3 services should use `LoggerAwareInterface` with a NullLogger default, never a nullable logger property.

### Correct Pattern

```php
use Psr\Log\LoggerAwareInterface;
use Psr\Log\LoggerAwareTrait;
use Psr\Log\LoggerInterface;
use Psr\Log\NullLogger;

class ImageProcessor implements LoggerAwareInterface
{
    use LoggerAwareTrait;

    public function __construct(
        private readonly ImageManagerFactory $factory,
    ) {
        // NullLogger default — never nullable
        $this->logger = new NullLogger();
    }

    /**
     * Helper to narrow type for PHPStan (trait property is ?LoggerInterface)
     */
    private function getLogger(): LoggerInterface
    {
        return $this->logger ?? new NullLogger();
    }
}
```

### Why NullLogger Default?

- Eliminates null checks throughout the class
- Services work standalone (without DI container) for testing
- TYPO3's `LoggerAwareTrait` sets the property via `setLogger()` — the NullLogger is overwritten by DI
- The `getLogger()` helper satisfies PHPStan because the trait property `$logger` is typed as `?LoggerInterface`

### Anti-Patterns

```php
// WRONG: Nullable logger with checks everywhere
private ?LoggerInterface $logger = null;

public function process(): void
{
    if ($this->logger !== null) {  // Repeated null checks
        $this->logger->info('Processing');
    }
}

// WRONG: Logger as required constructor parameter
public function __construct(LoggerInterface $logger) // Forces callers to provide logger
```

## PSR-14: Event Dispatch with Error Guard

Event dispatch should be wrapped in try/catch to prevent listener exceptions from breaking the main flow.

### Correct Pattern

```php
use Psr\EventDispatcher\EventDispatcherInterface;

class ImageProcessor
{
    public function __construct(
        private readonly EventDispatcherInterface $eventDispatcher,
    ) {}

    public function process(string $filePath): ProcessingResult
    {
        $result = $this->doProcessing($filePath);

        // Guarded dispatch — listener failures must not break processing
        try {
            $this->eventDispatcher->dispatch(
                new ImageProcessedEvent($filePath, $result)
            );
        } catch (\Throwable $e) {
            $this->getLogger()->error('Event listener failed', [
                'event' => ImageProcessedEvent::class,
                'exception' => $e,
            ]);
        }

        return $result;
    }
}
```

### Event Class Pattern

```php
final class ImageProcessedEvent
{
    public function __construct(
        public readonly string $filePath,
        public readonly ProcessingResult $result,
    ) {}
}
```

### When to Guard vs Not Guard

| Context | Guard? | Reason |
|---------|--------|--------|
| Post-processing notifications | Yes | Main operation already complete |
| Validation events | No | Listeners may legitimately stop flow |
| Logging/audit events | Yes | Must not break business logic |
| Pre-processing hooks | Depends | Guard if optional enrichment, don't guard if validation |

## Factory Pattern with Capability Fallback

Use factory classes for runtime library selection with graceful degradation.

### Correct Pattern

```php
class ImageManagerFactory
{
    public function create(): ImageManager
    {
        if (extension_loaded('imagick')) {
            return new ImageManager(new ImagickDriver());
        }

        if (extension_loaded('gd')) {
            return new ImageManager(new GdDriver());
        }

        throw new \RuntimeException(
            'No image processing library available. Install ext-imagick or ext-gd.'
        );
    }
}
```

### Services.yaml Wiring

```yaml
services:
  Vendor\Extension\Service\ImageManagerFactory:
    public: true

  Intervention\Image\ImageManager:
    factory: ['@Vendor\Extension\Service\ImageManagerFactory', 'create']
```

### Generic Processor Interface

```php
interface ProcessorInterface
{
    public function process(ServerRequestInterface $request): ResponseInterface;
    public function canProcess(ServerRequestInterface $request): bool;
}
```

This enables middleware-style decoupling where processors can be swapped, chained, or decorated without modifying consumers.

## PHPStan Baseline Management

### Target: Empty Baseline

```neon
# phpstan-baseline.neon — IDEAL STATE
parameters:
    ignoreErrors: []
```

### Rules

1. **Never add new entries** — fix issues immediately
2. **Shrink on every PR** — remove entries as code improves
3. **Track count in CI** — alert if baseline grows
4. **Legitimate entries only** — complex generics, third-party type issues
5. **Review quarterly** — reassess if entries can now be fixed
