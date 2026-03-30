# Multi-Version Library Adapter Pattern

**Source:** t3x-nr-image-optimize Extension -- intervention/image v2/v4 compatibility
**Purpose:** Support multiple major versions of a library with incompatible APIs

## When to Use

- A dependency has multiple major versions with breaking API changes
- Your extension must support both versions (e.g., via `composer.json` `"lib/pkg": "^2.0 || ^4.0"`)
- Direct usage of the library class causes PHPStan errors on one version or the other
- `method_exists()` checks get narrowed by PHPStan when the variable is typed

## Pattern Overview

```
┌──────────────────────────────────────────────────────┐
│ YourInterface                                        │
│ ──────────────                                       │
│ Unified method signatures your code needs            │
│ encode(), resize(), getWidth(), etc.                 │
└──────────────────────────┬───────────────────────────┘
                           │ implements
                           ▼
┌──────────────────────────────────────────────────────┐
│ LibraryAdapter                                       │
│ ──────────────                                       │
│ - Accepts object (not typed library class)           │
│ - Detects version at construction via method_exists  │
│ - Uses dynamic dispatch: $obj->{$method}(...)        │
│ - Single @phpstan-ignore method.dynamicName          │
└──────────────────────────────────────────────────────┘
                           │ used by
                           ▼
┌──────────────────────────────────────────────────────┐
│ Consumer classes                                     │
│ ──────────────                                       │
│ Depend on YourInterface, never the library directly  │
│ Wired via Services.yaml                              │
└──────────────────────────────────────────────────────┘
```

## Implementation Steps

### 1. Define the Interface

Define only the methods your code actually needs, using your own
types (not the library's):

```php
<?php

declare(strict_types=1);

namespace Vendor\Extension\Adapter;

interface ImageManagerInterface
{
    /**
     * Create an image instance from a file path or binary string.
     */
    public function make(string $source): object;

    /**
     * Encode an image to the given format.
     *
     * @return string Binary image data
     */
    public function encode(object $image, string $format, int $quality = 90): string;
}
```

### 2. Create the Adapter

Use `object` type for the library instance to prevent PHPStan from
narrowing `method_exists()` checks:

```php
<?php

declare(strict_types=1);

namespace Vendor\Extension\Adapter;

final class InterventionImageAdapter implements ImageManagerInterface
{
    private readonly bool $isV4;

    /**
     * @param object $manager Intervention\Image\ImageManager (v2 or v4)
     */
    public function __construct(
        private readonly object $manager,
    ) {
        // Detect version by checking for v4-specific method
        $this->isV4 = method_exists($manager, 'read');
    }

    public function make(string $source): object
    {
        $method = $this->isV4 ? 'read' : 'make';

        // @phpstan-ignore method.dynamicName
        return $this->manager->{$method}($source);
    }

    public function encode(object $image, string $format, int $quality = 90): string
    {
        if ($this->isV4) {
            // v4: $image->encodeByExtension('webp', quality: 80)
            $method = 'encodeByExtension';
            // @phpstan-ignore method.dynamicName
            $encoded = $image->{$method}($format, quality: $quality);

            return (string) $encoded;
        }

        // v2: $image->encode('webp', 80)->getEncoded()
        $method = 'encode';
        // @phpstan-ignore method.dynamicName
        $encoded = $image->{$method}($format, $quality);

        return (string) $encoded;
    }
}
```

### 3. Wire in Services.yaml

```yaml
services:
  # Create the library's native manager
  Intervention\Image\ImageManager:
    factory: ['Vendor\Extension\Factory\ImageManagerFactory', 'create']

  # Adapter wraps the native manager
  Vendor\Extension\Adapter\InterventionImageAdapter:
    arguments:
      $manager: '@Intervention\Image\ImageManager'

  # Interface points to the adapter
  Vendor\Extension\Adapter\ImageManagerInterface:
    alias: 'Vendor\Extension\Adapter\InterventionImageAdapter'
```

### 4. Depend on the Interface

```php
<?php

declare(strict_types=1);

namespace Vendor\Extension\Service;

use Vendor\Extension\Adapter\ImageManagerInterface;

final class ImageProcessor
{
    public function __construct(
        private readonly ImageManagerInterface $imageManager,
    ) {}

    public function convertToWebp(string $sourcePath, int $quality = 80): string
    {
        $image = $this->imageManager->make($sourcePath);

        return $this->imageManager->encode($image, 'webp', $quality);
    }
}
```

## Key Techniques

### Use `object` Type, Not the Library Class

```php
// BAD: PHPStan narrows the type and method_exists() becomes always-true/false
public function __construct(
    private readonly ImageManager $manager,  // typed to specific version
) {
    // PHPStan knows ImageManager::read() exists (or doesn't), ignores method_exists()
    if (method_exists($this->manager, 'read')) { ... }
}

// GOOD: object prevents PHPStan from knowing the exact class
public function __construct(
    private readonly object $manager,  // no type narrowing
) {
    // PHPStan cannot narrow — method_exists() check is respected
    if (method_exists($this->manager, 'read')) { ... }
}
```

### Dynamic Method Dispatch

```php
// BAD: version-specific @phpstan-ignore tags
// Works on v2, errors on v4:
/** @phpstan-ignore-next-line */
$image->encode('webp', 80);

// Works on v4, errors on v2:
/** @phpstan-ignore-next-line */
$image->encodeByExtension('webp', quality: 80);

// GOOD: dynamic dispatch with version-independent ignore
$method = $this->isV4 ? 'encodeByExtension' : 'encode';
// @phpstan-ignore method.dynamicName
$result = $image->{$method}(...$args);
```

### Prefer Universal API Methods

Before writing version-branching code, check whether a method exists
in ALL supported versions:

```php
// Both v2 and v4 support save() with format inference from extension
$image->save('/path/to/output.webp');

// Only v4 has toWebp() — avoid unless you version-branch
$image->toWebp(quality: 80);
```

**Always check the common API surface first.** Document which methods
are version-specific vs. universal in your adapter's PHPDoc.

## PHPStan Considerations

| Problem | Solution |
|---------|----------|
| `method_exists()` narrowed on typed param | Use `object` parameter type |
| `@phpstan-ignore` for v2 method errors on v4 | Isolate in adapter with dynamic dispatch |
| `@phpstan-ignore-next-line` is version-specific | Use `method.dynamicName` identifier (fires on all versions) |
| Library class not found in one version | Never import library classes in consumer code |

### Version-Specific vs. Version-Independent Ignores

```php
// VERSION-SPECIFIC (breaks on the other version):
/** @phpstan-ignore method.notFound */    // only needed when method missing
/** @phpstan-ignore argument.type */      // only needed when signature differs

// VERSION-INDEPENDENT (safe on all versions):
// @phpstan-ignore method.dynamicName     // always fires for $obj->{$var}()
```

## Testing

Test the adapter against both library versions in CI:

```yaml
# .github/workflows/ci.yml
strategy:
  matrix:
    include:
      - php: '8.2'
        deps: 'intervention/image:^2.0'
      - php: '8.3'
        deps: 'intervention/image:^4.0'

steps:
  - run: composer require ${{ matrix.deps }} --no-update
  - run: composer update --prefer-dist
  - run: vendor/bin/phpunit
  - run: vendor/bin/phpstan analyse
```

## Related References

- `adapter-registry-pattern.md` -- Runtime adapter selection from database config
- `phpstan-compliance.md` -- PHPStan error fixing and baseline strategies
- `type-safety.md` -- Interface and type declaration patterns
- `symfony-patterns.md` -- Dependency injection and Services.yaml wiring
