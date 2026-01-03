---
name: php-modernization
description: "Agent Skill: PHP 8.x modernization patterns. Use when upgrading to PHP 8.1/8.2/8.3/8.4/8.5, implementing type safety, or achieving PHPStan level 10. By Netresearch."
---

# PHP Modernization Skill

Modernize PHP applications to PHP 8.x with type safety, PSR compliance, Symfony patterns, and static analysis.

## Expertise Areas

- **PHP 8.x**: Constructor promotion, readonly, enums, match, attributes, union types
- **PSR/PER Compliance**: Active PHP-FIG standards (PSR-1,3,4,6,7,11,12,13,14,15,16,17,18,20, PER Coding Style)
- **Type Safety**: Generics via PHPDoc, ArrayTypeHelper, PHPStan level 10 (max)
- **Symfony**: DI patterns, PHP config, PSR-14 events

## Reference Files

- `references/php8-features.md` - PHP 8.0-8.5 features
- `references/psr-per-compliance.md` - **Active PSR and PER standards (required)**
- `references/type-safety.md` - Type system strategies
- `references/request-dtos.md` - Request DTOs, safe integer handling
- `references/symfony-patterns.md` - Modern Symfony architecture
- `references/phpstan-compliance.md` - Static analysis configuration
- `references/migration-strategies.md` - Version upgrade planning
- `references/adapter-registry-pattern.md` - Dynamic adapter instantiation

## PSR/PER Compliance (Required)

All modern PHP code must follow active PHP-FIG standards:

| Standard | Purpose | Requirement |
|----------|---------|-------------|
| PSR-1 | Basic Coding | **Required** |
| PSR-4 | Autoloading | **Required** |
| PER Coding Style | Coding Style | **Required** (supersedes PSR-12) |
| PSR-3 | Logger | Use when logging |
| PSR-6/16 | Cache | Use when caching |
| PSR-7/17/18 | HTTP | Use for HTTP clients |
| PSR-11 | Container | Use for DI containers |
| PSR-14 | Events | Use for event dispatching |
| PSR-15 | Middleware | Use for HTTP middleware |
| PSR-20 | Clock | Use for time-dependent code |

**Source of truth:** https://www.php-fig.org/psr/ and https://www.php-fig.org/per/

## Quick Patterns

**Constructor promotion (PHP 8.0+):**
```php
readonly class UserDTO {
    public function __construct(
        public string $name,
        public string $email,
    ) {}
}
```

**PSR-18 HTTP client (minimal interface):**
```php
use Psr\Http\Client\ClientInterface;
use Psr\Http\Message\RequestFactoryInterface;

final class ApiService
{
    public function __construct(
        private readonly ClientInterface $client,
        private readonly RequestFactoryInterface $requestFactory,
    ) {}

    public function fetch(string $uri): array
    {
        $request = $this->requestFactory->createRequest('GET', $uri);
        $response = $this->client->sendRequest($request);
        return json_decode($response->getBody()->getContents(), true);
    }
}
```

**Typed arrays (PHPDoc generics):**
```php
/** @return array<int, User> */
public function getUsers(): array
```

## Migration Checklist

- [ ] `declare(strict_types=1)` in all files
- [ ] PSR-4 autoloading configured in composer.json
- [ ] PER Coding Style 2.0 enforced via PHP-CS-Fixer
- [ ] Return types and parameter types on all methods
- [ ] Replace annotations with attributes
- [ ] Use readonly, enums, match expressions
- [ ] PHPStan level 10 (max) - required for full conformance
- [ ] Type-hint against PSR interfaces (not implementations)

## Scoring

| Criterion | Requirement |
|-----------|-------------|
| PHPStan | Level 10 (max) required for full points |
| PHP-CS-Fixer | `@PER-CS` ruleset required |
| PSR Compliance | Type-hint against PSR interfaces |
| Rector | No remaining suggestions |

> **Note:** PHPStan level 9 is insufficient for security-critical code. Level 10 enforces strict `mixed` type handling.

## PHP-CS-Fixer Configuration

```php
// .php-cs-fixer.dist.php
return (new PhpCsFixer\Config())
    ->setRules([
        '@PER-CS' => true,
        '@PER-CS:risky' => true,
        'declare_strict_types' => true,
    ])
    ->setRiskyAllowed(true);
```

## Verification

```bash
./scripts/verify-php-project.sh /path/to/project
```

---

> **Contributing:** https://github.com/netresearch/php-modernization-skill
