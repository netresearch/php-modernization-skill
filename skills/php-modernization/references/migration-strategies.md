<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# PHP Migration Strategies

## Version Upgrade Planning

### Pre-Migration Assessment

```bash
# Check PHP compatibility
composer require --dev phpcompatibility/php-compatibility

# Run compatibility check
vendor/bin/phpcs -p --standard=PHPCompatibility \
    --runtime-set testVersion 8.2 \
    src/

# Check deprecated features
php -d error_reporting=E_ALL \
    -d display_errors=1 \
    vendor/bin/phpunit
```

### Migration Phases

1. **Assessment** (1-2 days)
   - Run compatibility checks
   - Identify deprecated features
   - Document breaking changes
   - Estimate effort

2. **Preparation** (2-5 days)
   - Update composer.json constraints
   - Fix deprecation warnings
   - Update CI configuration
   - Prepare feature branches

3. **Execution** (3-10 days)
   - Apply automated fixes (Rector)
   - Manual code updates
   - Test extensively
   - Update dependencies

4. **Validation** (2-3 days)
   - Full test suite
   - Performance benchmarks
   - Security scan
   - Staging deployment

## Rector Automation

### Basic Configuration

```php
<?php
// rector.php

declare(strict_types=1);

use Rector\Config\RectorConfig;
use Rector\Set\ValueObject\LevelSetList;
use Rector\Set\ValueObject\SetList;
use Rector\Symfony\Set\SymfonySetList;

return RectorConfig::configure()
    ->withPaths([
        __DIR__ . '/src',
        __DIR__ . '/tests',
    ])
    ->withSkip([
        __DIR__ . '/src/Kernel.php',
    ])
    ->withSets([
        LevelSetList::UP_TO_PHP_83,
        SetList::CODE_QUALITY,
        SetList::DEAD_CODE,
        SetList::TYPE_DECLARATION,
        SymfonySetList::SYMFONY_64,
    ]);
```

### Targeted Upgrades

```php
<?php
// rector.php for specific PHP version upgrade

use Rector\Config\RectorConfig;
use Rector\Php80\Rector\Class_\AnnotationToAttributeRector;
use Rector\Php80\Rector\Class_\ClassPropertyAssignToConstructorPromotionRector;
use Rector\Php80\Rector\FunctionLike\MixedTypeRector;
use Rector\Php81\Rector\FuncCall\NullToStrictStringFuncCallArgRector;
use Rector\Php81\Rector\Property\ReadOnlyPropertyRector;

return RectorConfig::configure()
    ->withPaths([__DIR__ . '/src'])
    ->withRules([
        // PHP 8.0
        ClassPropertyAssignToConstructorPromotionRector::class,
        AnnotationToAttributeRector::class,

        // PHP 8.1
        ReadOnlyPropertyRector::class,

        // Type declarations
        MixedTypeRector::class,
    ]);
```

### Running Rector

```bash
# Dry run (preview changes); exit 0 = no change, 2 = changes proposed
vendor/bin/rector process --dry-run

# One rule on one area; --only needs the rule to be registered in the
# config or in a set the config loads
vendor/bin/rector process src/Payment \
  --only='Rector\Php80\Rector\Switch_\ChangeSwitchToMatchRector' --dry-run

# Apply the same scope after the diff was reviewed
vendor/bin/rector process src/Payment \
  --only='Rector\Php80\Rector\Switch_\ChangeSwitchToMatchRector'

# Drop the cache after a vendor or config change
vendor/bin/rector process --dry-run --clear-cache
```

### One bounded change at a time

A modernization step is one concern in one area: one value set to an enum,
one rule over one module, one class family to `readonly`. For each step:

1. Run the relevant existing tests first and note failures that already exist.
2. Preview the change (`--dry-run`) and read the diff against the questions in
   `SKILL.md` — Rector's diff is a proposal. In a probe with Rector 2.8.4,
   `ChangeSwitchToMatchRector` turned a loose `switch` on an untyped value into
   a strict `match`, and `ReadOnlyClassRector` made a class holding a mutable
   `\DateTime` a `readonly class`.
3. Apply, run the project's formatter, then lint, static analysis and the
   tests that cover the area.
4. Run the same Rector dry-run again: for a finished step it proposes no
   further change in that scope.
5. Commit, then start the next step.

## Dependency Upgrades

### Composer Constraint Updates

```json
{
    "require": {
        "php": ">=8.2",
        "symfony/framework-bundle": "^7.0",
        "doctrine/orm": "^3.0"
    },
    "config": {
        "platform": {
            "php": "8.2.0"
        }
    }
}
```

### Upgrade Process

```bash
# Update constraints in composer.json first

# Show outdated packages
composer outdated --direct

# Update with dry run
composer update --dry-run

# Update specific package
composer update symfony/framework-bundle --with-dependencies

# Update all
composer update

# Validate after update
composer validate --strict
```

### Refreshing a committed lock across a CI matrix

Composer resolves against the **running** PHP, not against the root `require`
constraint. A lock refreshed on a developer machine running PHP 8.5 can
therefore pin packages that the lowest cell of a `8.2 / 8.3 / 8.4` CI matrix
cannot install — the update succeeds locally and CI fails on `Your lock file
does not contain a compatible set of packages`.

Two ways to pin resolution to the minimum supported version:

1. **Declare `config.platform.php`** (see "Composer Constraint Updates" above).
   Deterministic on every machine, and the right fix when you own
   `composer.json`. It changes resolution for everyone, so it is a decision,
   not a hotfix.
2. **Run the update in a container** pinned to the minimum version. No
   `composer.json` change — use this when a repo has no platform declaration
   and the task at hand is a dependency fix, not a policy change.

```bash
# resolve at the minimum supported version, in a throwaway container.
# php:X-cli ships no composer — mount the host phar (it is plain PHP, so it
# runs under the container's interpreter).
docker run --rm -v "$PWD":/app -w /app -e COMPOSER_ALLOW_SUPERUSER=1 \
  -v "$(command -v composer)":/usr/local/bin/composer:ro \
  php:8.2-cli composer update --no-install --ignore-platform-req="ext-*"
```

- `--no-install` writes only the lock, so the container needs no extensions
  and no vendor download.
- `--ignore-platform-req="ext-*"` skips the missing extensions while leaving
  the **php version** requirement enforced — which is the constraint being
  pinned. Do not use bare `--ignore-platform-reqs`; it drops the php check too
  and defeats the purpose.

Verify the result against every PHP version in the matrix before pushing:

```bash
for V in 8.2 8.3 8.4; do
  docker run --rm -v "$PWD":/app -w /app -e COMPOSER_ALLOW_SUPERUSER=1 \
    -v "$(command -v composer)":/usr/local/bin/composer:ro \
    php:${V}-cli composer install --dry-run --ignore-platform-req="ext-*"
done
```

### A lock refresh is a code change

An unconstrained `composer update` moves every package its constraint allows,
including across majors — `"psr/log": "^1.0 || ^2.0 || ^3.0"` will jump 1.x to
3.x. Observed: that jump gave `LoggerInterface::log()` native parameter types,
which made PHPStan fail on an untyped test double — in a job unrelated to the
one being fixed.

Run the project's whole gate (static analysis, code style, tests) against the
refreshed lock, not just the check that was red. Pin the blast radius with
`composer update <vendor>/<package> --with-dependencies` when only one package
needs to move.

### Full or targeted update

Pick the update scope from what changed in `composer.json`:

- **Raised PHP floor** (`require.php` and `config.platform.php`): run a full
  `composer update`. The lock was resolved against the old platform; only a
  full update re-resolves every locked package against the new one. A targeted
  update leaves everything outside its argument list at versions chosen for the
  old floor.
- **One library moved**: `composer update <vendor>/<package>
  --with-all-dependencies`. `-W` also lets the package's dependencies move when
  they are root requirements; `-w` (`--with-dependencies`) keeps those fixed.
  Neither unlocks packages that require it; list a blocking one as well.
  Every other package stays at its locked version, so unrelated upgrades do not
  enter the change.
- **`composer update --lock`** is not an update. It keeps every package at its
  locked version and rewrites only the lock's `content-hash` (plus mirror and
  URL metadata), which silences the "lock file is not up to date" warning after
  a hand edit to `composer.json`. It does not resolve the edited requirements,
  so it cannot stand in for either update above.

### Resolving a `composer.lock` conflict

Never merge `composer.lock` by hand: its `content-hash` and package set must
come out of one resolver run. Resolve `composer.json` first, because the
regeneration reads it. Then take one side of the lock whole and regenerate:

```bash
# during `git rebase`: --ours is the branch being rebased onto plus the
# commits already replayed; --theirs is the commit being replayed
# (the reverse of `git merge`)
git checkout --ours composer.lock     # the lock the replay is landing on
# re-apply the replayed commit's intent against the resolved composer.json,
# and stage and continue only if that succeeds:
composer update <vendor>/<package> --with-all-dependencies \
  && git add composer.lock && git rebase --continue   # the packages it moved
# instead of that update: `composer update` when it raised the PHP floor or
# refreshed the whole lock, `composer update --lock` when its composer.json
# edit changes no requirement
```

During `git merge` the sides are the usual ones: `--ours` is the branch you
are on, `--theirs` is the branch being merged in.

Run `composer install` after the rebase has finished: a later replayed commit
can change the lock again after the update installed it.

## Framework-Specific Migrations

### Symfony Upgrade

```bash
# Install Symfony Flex
composer require symfony/flex

# Update recipes
composer recipes:update

# Run deprecation detector
php bin/console debug:container --deprecations

# Use Symfony upgrade guide
# https://symfony.com/doc/current/setup/upgrade_major.html
```

### Doctrine Upgrade (2.x to 3.x)

```php
// Before: Annotations
/**
 * @ORM\Entity
 * @ORM\Table(name="users")
 */
class User
{
    /**
     * @ORM\Id
     * @ORM\Column(type="integer")
     */
    private $id;
}

// After: Attributes (Doctrine 3.x)
#[ORM\Entity]
#[ORM\Table(name: 'users')]
class User
{
    #[ORM\Id]
    #[ORM\Column(type: 'integer')]
    private ?int $id = null;
}
```

## Testing During Migration

### Parallel Testing

```yaml
# .github/workflows/test.yml
jobs:
  test:
    strategy:
      matrix:
        php: ['8.1', '8.2', '8.3']
        symfony: ['6.4', '7.0']

    steps:
      - name: Install dependencies
        run: |
          composer require symfony/framework-bundle:^${{ matrix.symfony }} --no-update
          composer update --prefer-dist

      - name: Run tests
        run: vendor/bin/phpunit
```

### Deprecation Tracking

```php
<?php
// tests/bootstrap.php

use Symfony\Bridge\PhpUnit\DeprecationErrorHandler;

// Fail on deprecations
DeprecationErrorHandler::register(E_USER_DEPRECATED);

// Or track with threshold
putenv('SYMFONY_DEPRECATIONS_HELPER=max[direct]=0');
```

## Common Migration Patterns

### Annotation to Attribute

```php
// Rector handles this automatically, but manual pattern:

// Before
/**
 * @Route("/api/users", name="api_users")
 * @Method({"GET", "POST"})
 */

// After
#[Route('/api/users', name: 'api_users', methods: ['GET', 'POST'])]
```

### Array to Named Arguments

```php
// Before
$response = new Response(
    '',
    200,
    ['Content-Type' => 'application/json']
);

// After
$response = new Response(
    content: '',
    status: Response::HTTP_OK,
    headers: ['Content-Type' => 'application/json']
);
```

### Switch to Match

```php
// Before
switch ($status) {
    case 'active':
        $color = 'green';
        break;
    case 'pending':
        $color = 'yellow';
        break;
    default:
        $color = 'gray';
}

// After
$color = match($status) {
    'active' => 'green',
    'pending' => 'yellow',
    default => 'gray',
};
```

The two are equal only when `$status` is always a string: `switch` compares
with `==`, `match` with `===`. Check the comparison, fall-through and
`default` before converting — see "Match Expression" in `php8-features.md`.

### Property Initialization

```php
// Before (PHP 7.4)
class Service
{
    private LoggerInterface $logger;
    private array $config;

    public function __construct(LoggerInterface $logger, array $config)
    {
        $this->logger = $logger;
        $this->config = $config;
    }
}

// After (PHP 8.0+)
class Service
{
    public function __construct(
        private readonly LoggerInterface $logger,
        private readonly array $config,
    ) {}
}
```

## Rollback Strategy

### Version Control

```bash
# Create migration branch
git checkout -b php82-upgrade

# Tag pre-migration state
git tag pre-php82-upgrade

# If rollback needed
git checkout main
git branch -D php82-upgrade
```

### Feature Flags

```php
// Enable gradual rollout
class FeatureFlags
{
    public static function useNewParser(): bool
    {
        return getenv('USE_NEW_PARSER') === 'true'
            || PHP_VERSION_ID >= 80200;
    }
}

// Usage
if (FeatureFlags::useNewParser()) {
    return $this->newParser->parse($input);
}
return $this->legacyParser->parse($input);
```

## Anti-Patterns to Avoid

### Replace-All Literal Extraction That Rewrites Its Own Declaration

Bulk-extracting a repeated literal into a constant (the usual fix for SonarQube
`php:S1192`) is a natural scripted transform: find every `'…'`, replace with
`self::NAME`. Run naively, the replacement also hits the line that *defines* the
constant:

```php
// ❌ what a blind replace-all produces
private const SMALL_PAYLOAD = self::SMALL_PAYLOAD;   // Fatal: self-referencing constant

// ✅ intended
private const SMALL_PAYLOAD = '{"a":1}';
```

**Static analysis does not catch this.** PHPStan at level 10 reports nothing —
the error is raised by the engine at class-load time, so only *executing* a file
that loads the class surfaces it. A change set that passes every analyzer can
still be fatally broken.

Two rules when scripting this class of refactor:

1. **Exclude the declaration line.** Insert the `const` declaration *after*
   rewriting the usages, or skip any line already matching
   `const\s+NAME\s*=`.
2. **Verify by executing, not by analyzing.** Run the test suite (or at minimum
   `php -l` plus a load of each touched class); a green PHPStan run is not
   evidence here.

Checkpoint `PM-44` detects the resulting pattern. It generalizes beyond PHP —
any "extract repeated value to a named constant" transform in any language has
the same declaration-site hazard.

### Premature Backwards Compatibility

Don't add backwards compatibility code for features or versions that haven't been released yet:

```php
// ❌ BAD: BC code for unreleased extension
// Adding complexity for versions that don't exist in the wild
if ($options['auth_type'] !== null) {
    // Convert legacy string to enum for BC
    $placement = SecretPlacement::tryFrom($options['auth_type']);
}

// ✅ GOOD: Clean implementation without BC for unreleased code
public function request(array $options): Response
{
    $placement = $options['placement'];  // Just use the enum directly
    // ...
}
```

**When BC is appropriate:**
- After a public release with real installations
- When deprecating a feature (provide migration path)
- When API contracts exist with external consumers

**When BC is NOT needed:**
- Pre-release/unreleased extensions
- Internal refactoring during development
- Private/internal APIs

**Rule:** Only add BC code when there are actual installations to support. Premature BC creates unnecessary complexity and maintenance burden.

## Post-Migration Checklist

- [ ] All tests pass on target PHP version
- [ ] No deprecation warnings in logs
- [ ] PHPStan passes at configured level
- [ ] Performance benchmarks acceptable
- [ ] Dependencies updated and compatible
- [ ] CI/CD pipelines updated
- [ ] Documentation updated
- [ ] Team trained on new features
- [ ] Rollback plan tested
- [ ] Staging environment validated
