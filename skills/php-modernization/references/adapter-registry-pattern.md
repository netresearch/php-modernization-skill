# Adapter Registry Pattern

**Purpose:** Dynamic adapter instantiation from runtime configuration

## Overview

The Adapter Registry pattern separates PHP implementation classes (Adapters) from configuration records (Providers). This allows runtime selection of an implementation based on configuration loaded from any source (database, config file, environment).

## When to Use

- Integrating with multiple external services (APIs, SDKs)
- Supporting multiple implementations of the same interface
- Dynamic provider selection based on configuration
- Clean separation between protocol logic and connection credentials
- Multi-version library compatibility (see also `multi-version-adapters.md`)

## Terminology

| Term | Description | Example |
|------|-------------|---------|
| **Adapter** | PHP class implementing protocol | `GdAdapter`, `ImagickAdapter` |
| **Provider** | Configuration record with credentials/options | Row in DB, config struct, env-loaded DTO |
| **Registry** | Maps provider type string → adapter class | `ImagingAdapterRegistry` |

## Pattern Structure

```
┌─────────────────────────────────────────────────────────────┐
│ AdapterRegistry                                              │
│ ─────────────────────────                                   │
│ Maps adapter_type string → PHP Adapter class                │
│ Creates configured adapter instances from Provider records  │
└──────────────────────────┬──────────────────────────────────┘
                           │ creates
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ AdapterInterface                                             │
│ ─────────────────                                           │
│ Common contract for all adapters                            │
│ configure(), execute(), supports()                          │
└─────────────────────────────────────────────────────────────┘
           ▲                    ▲                    ▲
           │                    │                    │
┌──────────┴─────┐  ┌──────────┴─────┐  ┌──────────┴─────┐
│ GdAdapter      │  │ ImagickAdapter │  │ VipsAdapter    │
│                │  │                │  │                │
│ adapter_type:  │  │ adapter_type:  │  │ adapter_type:  │
│ "gd"           │  │ "imagick"      │  │ "vips"         │
└────────────────┘  └────────────────┘  └────────────────┘
```

## Implementation

### Adapter Interface

```php
<?php
declare(strict_types=1);

namespace App\Imaging;

interface AdapterInterface
{
    /**
     * Configure adapter with provider settings.
     *
     * @param array<string, mixed> $config
     */
    public function configure(array $config): void;

    /**
     * Check if adapter supports a capability.
     */
    public function supports(string $capability): bool;
}
```

### Concrete Adapter

```php
<?php
declare(strict_types=1);

namespace App\Imaging\Adapter;

use App\Imaging\AdapterInterface;
use Psr\Http\Client\ClientInterface;

final class GdAdapter implements AdapterInterface
{
    private int $quality = 85;
    private string $tmpDir = '/tmp';
    private int $timeout = 30;

    public function __construct(
        private readonly ClientInterface $httpClient,
    ) {}

    public function configure(array $config): void
    {
        $this->quality = (int) ($config['quality'] ?? 85);
        $this->tmpDir = (string) ($config['tmpDir'] ?? '/tmp');
        $this->timeout = (int) ($config['timeout'] ?? 30);
    }

    public function supports(string $capability): bool
    {
        return in_array($capability, ['resize', 'crop', 'jpeg', 'png'], true);
    }

    /**
     * @return array{path: string, width: int, height: int}
     */
    public function resize(string $sourcePath, int $width, int $height): array
    {
        // GD-based resize implementation
        $img = imagecreatefromstring(file_get_contents($sourcePath));
        $resized = imagescale($img, $width, $height);
        $outPath = $this->tmpDir . '/' . uniqid('img_', true) . '.jpg';
        imagejpeg($resized, $outPath, $this->quality);

        return ['path' => $outPath, 'width' => $width, 'height' => $height];
    }
}
```

### Provider Record (Configuration DTO)

```php
<?php
declare(strict_types=1);

namespace App\Imaging\Config;

final class ImagingProvider
{
    public const ADAPTER_GD = 'gd';
    public const ADAPTER_IMAGICK = 'imagick';
    public const ADAPTER_VIPS = 'vips';

    public function __construct(
        public readonly string $identifier,
        public readonly string $name,
        public readonly string $adapterType,
        public readonly int $quality = 85,
        public readonly string $tmpDir = '/tmp',
        public readonly int $timeout = 30,
        public readonly bool $isActive = true,
    ) {}
}
```

### Registry Implementation

```php
<?php
declare(strict_types=1);

namespace App\Imaging;

use App\Imaging\Adapter\GdAdapter;
use App\Imaging\Adapter\ImagickAdapter;
use App\Imaging\Adapter\VipsAdapter;
use App\Imaging\Config\ImagingProvider;
use Psr\Container\ContainerInterface;

final class ImagingAdapterRegistry
{
    /**
     * Maps adapter_type string to adapter class
     *
     * @var array<string, class-string<AdapterInterface>>
     */
    private const array ADAPTER_MAP = [
        ImagingProvider::ADAPTER_GD      => GdAdapter::class,
        ImagingProvider::ADAPTER_IMAGICK => ImagickAdapter::class,
        ImagingProvider::ADAPTER_VIPS    => VipsAdapter::class,
    ];

    public function __construct(
        private readonly ContainerInterface $container,
    ) {}

    /**
     * @return list<string>
     */
    public function getAvailableAdapterTypes(): array
    {
        return array_keys(self::ADAPTER_MAP);
    }

    public function hasAdapterType(string $adapterType): bool
    {
        return isset(self::ADAPTER_MAP[$adapterType]);
    }

    /**
     * Create adapter instance from a provider record.
     *
     * @throws \InvalidArgumentException If adapter type unknown
     */
    public function createAdapterFromProvider(ImagingProvider $provider): AdapterInterface
    {
        $adapterClass = self::ADAPTER_MAP[$provider->adapterType]
            ?? throw new \InvalidArgumentException(
                sprintf('Unknown adapter type: %s', $provider->adapterType)
            );

        /** @var AdapterInterface $adapter */
        $adapter = $this->container->get($adapterClass);

        $adapter->configure([
            'quality' => $provider->quality,
            'tmpDir'  => $provider->tmpDir,
            'timeout' => $provider->timeout,
        ]);

        return $adapter;
    }
}
```

### DI container configuration

Wire the registry as a public service and each adapter under its FQCN. The exact format depends on the framework (Symfony YAML/PHP, Laminas, PHP-DI, Pimple, custom). The registry must receive a PSR-11 `ContainerInterface`. Each adapter must be retrievable by its class name.

```yaml
# Example: Symfony-style services file
services:
  _defaults:
    autowire: true
    autoconfigure: true
    public: false

  App\Imaging\ImagingAdapterRegistry:
    public: true

  App\Imaging\Adapter\GdAdapter: ~
  App\Imaging\Adapter\ImagickAdapter: ~
  App\Imaging\Adapter\VipsAdapter: ~
```

For other DI containers, perform the equivalent factory wiring: register the registry as a service that receives the container, and ensure each adapter class is resolvable by FQCN.

## Usage Examples

### In a Service Class

```php
<?php
declare(strict_types=1);

namespace App\Service;

use App\Imaging\Config\ImagingProviderRepository;
use App\Imaging\ImagingAdapterRegistry;

final class ThumbnailService
{
    public function __construct(
        private readonly ImagingProviderRepository $providerRepository,
        private readonly ImagingAdapterRegistry $adapterRegistry,
    ) {}

    /**
     * @return array{path: string, width: int, height: int}
     */
    public function makeThumbnail(string $providerId, string $sourcePath, int $w, int $h): array
    {
        $provider = $this->providerRepository->findByIdentifier($providerId)
            ?? throw new \InvalidArgumentException('Provider not found: ' . $providerId);

        $adapter = $this->adapterRegistry->createAdapterFromProvider($provider);

        if (!$adapter->supports('resize')) {
            throw new \RuntimeException('Adapter does not support resize');
        }

        return $adapter->resize($sourcePath, $w, $h);
    }
}
```

### In a Controller

```php
<?php
declare(strict_types=1);

namespace App\Controller;

use App\Imaging\Config\ImagingProviderRepository;
use App\Imaging\ImagingAdapterRegistry;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\ServerRequestInterface;

final class ProviderController
{
    public function __construct(
        private readonly ImagingProviderRepository $providerRepository,
        private readonly ImagingAdapterRegistry $adapterRegistry,
        private readonly ResponseFactory $responseFactory,
    ) {}

    public function testConnectionAction(ServerRequestInterface $request): ResponseInterface
    {
        $providerId = (string) ($request->getParsedBody()['provider'] ?? '');
        $provider = $this->providerRepository->findByIdentifier($providerId);

        if ($provider === null) {
            return $this->responseFactory->jsonError('Provider not found', 404);
        }

        try {
            $adapter = $this->adapterRegistry->createAdapterFromProvider($provider);
            return $this->responseFactory->json([
                'success'      => true,
                'capabilities' => array_filter(
                    ['resize', 'crop', 'jpeg', 'png', 'webp', 'avif'],
                    static fn (string $cap): bool => $adapter->supports($cap),
                ),
            ]);
        } catch (\Throwable $e) {
            return $this->responseFactory->jsonError($e->getMessage(), 400);
        }
    }
}
```

## Extending with New Adapters

### 1. Create Adapter Class

```php
<?php
declare(strict_types=1);

namespace App\Imaging\Adapter;

use App\Imaging\AdapterInterface;

final class WebpAdapter implements AdapterInterface
{
    // Implement interface...
}
```

### 2. Add to Provider Constants

```php
// In ImagingProvider
public const ADAPTER_WEBP = 'webp';
```

### 3. Update Registry Map

```php
// In ImagingAdapterRegistry
private const array ADAPTER_MAP = [
    // ... existing adapters
    ImagingProvider::ADAPTER_WEBP => WebpAdapter::class,
];
```

### 4. Register in DI container

Add the new adapter to your container configuration (services file, factory wiring, etc.) so the registry can resolve it via the PSR-11 container.

## Benefits

| Benefit | Description |
|---------|-------------|
| **Separation of Concerns** | Protocol logic separate from configuration |
| **Runtime Flexibility** | Select implementation via configuration |
| **Testability** | Mock adapters easily in tests |
| **Extensibility** | Add new adapters without changing existing code |
| **Type Safety** | Interface ensures consistent API across adapters |

## Testing

```php
<?php
declare(strict_types=1);

namespace App\Tests\Imaging;

use App\Imaging\Adapter\GdAdapter;
use App\Imaging\Config\ImagingProvider;
use App\Imaging\ImagingAdapterRegistry;
use PHPUnit\Framework\TestCase;
use Psr\Container\ContainerInterface;

final class ImagingAdapterRegistryTest extends TestCase
{
    public function testCreatesCorrectAdapterForProviderType(): void
    {
        $mockAdapter = $this->createMock(GdAdapter::class);
        $mockAdapter->expects(self::once())
            ->method('configure')
            ->with(self::callback(static fn (array $cfg): bool
                => $cfg['quality'] === 90 && $cfg['timeout'] === 60));

        $container = $this->createMock(ContainerInterface::class);
        $container->method('get')
            ->with(GdAdapter::class)
            ->willReturn($mockAdapter);

        $registry = new ImagingAdapterRegistry($container);

        $provider = new ImagingProvider(
            identifier: 'gd-default',
            name: 'GD default',
            adapterType: 'gd',
            quality: 90,
            timeout: 60,
        );

        $adapter = $registry->createAdapterFromProvider($provider);

        self::assertInstanceOf(GdAdapter::class, $adapter);
    }

    public function testThrowsExceptionForUnknownAdapterType(): void
    {
        $container = $this->createMock(ContainerInterface::class);
        $registry = new ImagingAdapterRegistry($container);

        $provider = new ImagingProvider(
            identifier: 'unknown',
            name: 'Unknown',
            adapterType: 'unknown',
        );

        $this->expectException(\InvalidArgumentException::class);
        $this->expectExceptionMessage('Unknown adapter type: unknown');

        $registry->createAdapterFromProvider($provider);
    }
}
```

## Related Patterns

- **Strategy Pattern**: Adapters implement the Strategy pattern
- **Factory Pattern**: Registry acts as a factory for adapters
- **Dependency Injection**: Adapters created via PSR-11 container

## Related References

- `multi-version-adapters.md` — Adapter pattern for multi-version library compatibility
- `symfony-patterns.md` — Dependency injection patterns
- `type-safety.md` — Interface and type declarations
