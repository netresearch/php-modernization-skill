# PHP 8.4 Modernization Reference

PHP 8.4 was released 2024-11-21. This file covers the features that change how
modernized PHP code is written. Each section: short description, before/after,
when to apply, when to avoid, Rector reference where one exists.

Official release notes: https://www.php.net/releases/8.4/en.php
Migration guide: https://www.php.net/manual/en/migration84.php

## What is now BASELINE (do not treat as new)

Anything from PHP 8.0 through 8.3 is assumed available in any modernization
target that requires PHP 8.4. Do not flag these as "new" in 8.4 work:

- 8.0: named arguments, constructor property promotion, union types,
  `match`, nullsafe `?->`, attributes (`#[...]`), `mixed`, `static` return type,
  `Stringable`, `WeakMap`, throw expressions
- 8.1: `enum`/backed enums, `readonly` properties, first-class callable
  syntax `fn(...)`, intersection types, `new` in initializers,
  `never` return type, `array_is_list()`, `#[ReturnTypeWillChange]`
- 8.2: `readonly` classes, DNF types `(A&B)|C`, constants in traits,
  `#[\SensitiveParameter]`, `null`/`false`/`true` as standalone types,
  deprecation of dynamic properties (`#[\AllowDynamicProperties]`)
- 8.3: typed class constants, dynamic class constant fetch
  `Foo::{$name}`, `#[\Override]`, `json_validate()`, `Randomizer::getBytesFromString()`

If a codebase still uses pre-8.0 idioms (manual getters/setters everywhere,
constants instead of enums, `array_walk` over a fluent pipeline), normalize
those first — see `php8-features.md` for the canonical 8.0–8.3 patterns.

## Property hooks

RFC: https://wiki.php.net/rfc/property-hooks
Manual: https://www.php.net/manual/en/language.oop5.property-hooks.php

`get` and `set` accessors attach to a property. The property is still accessed
as `$obj->name`, but reads or writes can compute, validate, or transform.
Replaces the "property + getter + setter" boilerplate triangle.

```php
// PHP 8.3
final class User
{
    private string $firstName;
    private string $lastName;

    public function __construct(string $firstName, string $lastName)
    {
        $this->firstName = $firstName;
        $this->lastName = $lastName;
    }

    public function getFullName(): string
    {
        return $this->firstName . ' ' . $this->lastName;
    }

    public function setFullName(string $value): void
    {
        [$this->firstName, $this->lastName] = explode(' ', $value, 2);
    }
}

// PHP 8.4+
final class User
{
    public string $fullName {
        get => $this->firstName . ' ' . $this->lastName;
        set (string $value) {
            [$this->firstName, $this->lastName] = explode(' ', $value, 2);
        }
    }

    public function __construct(
        private string $firstName,
        private string $lastName,
    ) {}
}
```

A get-only "virtual" property (no backing field needed):

```php
final class Order
{
    public function __construct(
        /** @var list<LineItem> */
        public readonly array $items,
    ) {}

    public int $total {
        get => array_sum(array_map(fn ($i) => $i->price, $this->items));
    }
}
```

A validated set hook with a real backing field:

```php
final class Email
{
    public string $value {
        set (string $value) {
            if (filter_var($value, FILTER_VALIDATE_EMAIL) === false) {
                throw new \InvalidArgumentException("Invalid email: $value");
            }
            $this->value = $value;
        }
    }

    public function __construct(string $value)
    {
        $this->value = $value;
    }
}
```

**When to apply.** Mutable state with validation, computed read-only views,
or wrapping a stored field with normalization. Hooks are visible to static
analysis (PHPStan, Psalm) and to IDEs.

**When to avoid.**
- The class is a pure DTO with `readonly` immutable fields — keep them plain.
- The "computation" is expensive and should be cached — a method makes the
  cost obvious; a hook hides it.
- The setter has side effects beyond this object (DB write, event dispatch)
  — keep that behind an explicit method, hooks should be local.
- Doctrine-style entities where ORM proxies need direct field access — verify
  ORM compatibility before converting fields to hooks.

**Rector.** No stable rule yet for "method pair → property hook" as of 8.4
release. Convert by hand and lean on PHPStan to confirm callers.

## Asymmetric visibility

RFC: https://wiki.php.net/rfc/asymmetric-visibility-v2
Manual: https://www.php.net/manual/en/language.oop5.visibility.php#language.oop5.visibility-members-aviz

Read scope and write scope can differ. `public private(set)` means anyone
reads, only the declaring class writes. Eliminates getters that exist solely
to expose a private field.

```php
// PHP 8.3
final class BankAccount
{
    private float $balance = 0.0;

    public function getBalance(): float
    {
        return $this->balance;
    }

    public function deposit(float $amount): void
    {
        $this->balance += $amount;
    }
}

// PHP 8.4+
final class BankAccount
{
    public private(set) float $balance = 0.0;

    public function deposit(float $amount): void
    {
        $this->balance += $amount;
    }
}
```

Allowed combinations: the `set` visibility must be equal to or stricter than
the read visibility.

| Read       | Set allowed                            |
|------------|----------------------------------------|
| `public`   | `public`, `protected(set)`, `private(set)` |
| `protected`| `protected`, `private(set)`            |
| `private`  | `private` (asymmetric is meaningless)  |

Combined with `readonly` and constructor promotion:

```php
final class Cursor
{
    public function __construct(
        public protected(set) int $position = 0,
    ) {}

    protected function advance(int $by): void
    {
        $this->position += $by;
    }
}
```

**When to apply.**
- Exposing identity-like state (id, version, status) read-only to consumers
  while internal mutators evolve it.
- Replacing the "private + public getter" pair when there is no validation
  to do on read.
- Modeling state machines: external code observes, internal transition
  methods write.

**When to avoid.**
- Full immutability fits — use `readonly` (or a `readonly` class). Asymmetric
  is for *write-restricted-but-mutable*, not for "set once".
- The setter validates — combine with property hooks instead, or keep an
  explicit method.
- Ecosystems that reflect on properties for hydration (some serializers,
  some ORMs) may need configuration for `private(set)` properties.

**Rector.** No stable conversion rule. Manual migration; PHPStan catches
external write attempts.

## `#[\Deprecated]` attribute

RFC: https://wiki.php.net/rfc/deprecated_attribute
Manual: https://www.php.net/manual/en/class.deprecated.php

Marks a userland function, method, or class constant as deprecated. Calling
it triggers `E_USER_DEPRECATED` through PHP's standard deprecation channel —
the same channel core deprecations use, so the same handlers, log filters,
and CI gates apply.

```php
// PHP 8.3 — PHPDoc + manual trigger_error
final class LegacyApi
{
    /**
     * @deprecated since 2.0, use newFetch() instead
     */
    public function oldFetch(string $id): array
    {
        trigger_error(
            'LegacyApi::oldFetch() is deprecated, use newFetch()',
            E_USER_DEPRECATED,
        );
        return $this->newFetch($id);
    }
}

// PHP 8.4+
final class LegacyApi
{
    #[\Deprecated(
        message: 'Use newFetch() instead',
        since: '2.0',
    )]
    public function oldFetch(string $id): array
    {
        return $this->newFetch($id);
    }
}
```

Constants and free functions work the same way:

```php
final class Config
{
    #[\Deprecated(message: 'Use Config::TIMEOUT_MS', since: '3.1')]
    public const int TIMEOUT = 30;
}

#[\Deprecated(message: 'Use ::format() with explicit timezone', since: '4.0')]
function format_date(\DateTimeInterface $dt): string { /* ... */ }
```

**When to apply.** Library code with public-API deprecations. Replace every
`@deprecated` PHPDoc plus `trigger_error` pair with the attribute.

**When to avoid.** The function is fully internal (`@internal`) — just delete
or rename instead. Hot loops where a deprecation notice on every call is
prohibitively chatty — gate via the deprecation handler, not by skipping the
attribute.

**PHP 8.5 extends this** to traits and class constants in additional contexts.

## `new` without parentheses

RFC: https://wiki.php.net/rfc/new_without_parentheses

`new Foo()->bar()` is now legal. The expression-grammar quirk that forced
`(new Foo())->bar()` is removed.

```php
// PHP 8.3
$today = (new \DateTimeImmutable('today'))->format('Y-m-d');
$client = (new HttpClientFactory($config))->create();

// PHP 8.4+
$today = new \DateTimeImmutable('today')->format('Y-m-d');
$client = new HttpClientFactory($config)->create();
```

Works for property access, method chains, and array dereference:

```php
$first = new ItemRepository($pdo)->findAll()[0];
$name  = new User('alice')->name;
```

**When to apply.** Mechanical cleanup. Rector or PHP-CS-Fixer can do it.

**When to avoid.** Don't aggressively rewrite if the wrapping parens add
readability — for short factory + call patterns the new form is cleaner; for
long expressions either form remains acceptable, optimize for the next reader.

**Rector.** `Rector\Php84\Rector\New_\NewWithoutParenthesesRector` (in the
`Php84SetList`).

## Lazy objects

Manual: https://www.php.net/manual/en/language.oop5.lazy-objects.php
RFC: https://wiki.php.net/rfc/lazy-objects

Two new factories on `ReflectionClass`:

- `newLazyGhost(callable $initializer)` — returns an instance of the class
  itself; on first real access the initializer is called to populate it.
- `newLazyProxy(callable $factory)` — returns an instance whose state is
  forwarded to a real instance produced by `$factory` on first access.

This is the same machinery ORMs and DI containers used to fake with
hand-written proxies. Built-in support means correct serialization,
`var_dump`, `clone`, and equality semantics.

```php
// Ghost: same class, deferred state
$reflection = new \ReflectionClass(Report::class);

$report = $reflection->newLazyGhost(function (Report $report): void {
    // populate $report from disk; called on first property access
    $report->__construct(...$this->fetchRow());
});

// Caller does not know it is lazy
echo $report->title;  // initializer fires here
```

```php
// Proxy: a different real object satisfies access
$reflection = new \ReflectionClass(User::class);

$user = $reflection->newLazyProxy(function (): User {
    return $this->repository->find($id);  // real fetch
});

echo $user->email;  // proxy resolves once, caches the real object
```

**When to apply.**
- Repositories returning aggregates whose loading is expensive and
  conditionally needed.
- DI containers that can return "stubs" until first method call.
- Serialization endpoints that hand back partially-loaded entities.

**When to avoid.**
- The object is small and cheap to construct — skip the indirection.
- The class has `final` constructors with side effects you don't want
  triggered later — laziness defers those side effects.
- Code that uses `instanceof` against the *concrete* class is fine; code
  that introspects via internal pointer comparison or `spl_object_id()`
  needs review.

**Rector.** Not a refactor target — this is a runtime/architecture choice.

## Array find functions

RFC: https://wiki.php.net/rfc/array_find

Four new functions retire common `foreach` patterns:

- `array_find(array, callable): mixed` — first matching value, or `null`
- `array_find_key(array, callable): int|string|null` — first matching key
- `array_any(array, callable): bool` — at least one matches
- `array_all(array, callable): bool` — every element matches

All four short-circuit; `array_filter` does not.

```php
// PHP 8.3 — manual loop
$active = null;
foreach ($users as $u) {
    if ($u->isActive()) {
        $active = $u;
        break;
    }
}

// PHP 8.4+
$active = array_find($users, fn (User $u) => $u->isActive());
```

```php
// "Has any expired" — replaces array_filter(...) !== []
$hasExpired = array_any($tokens, fn (Token $t) => $t->isExpired());

// "All paid" — replaces count(filter) === count(input)
$allPaid = array_all($invoices, fn (Invoice $i) => $i->isPaid());

// Find the key, not the value
$idx = array_find_key($lines, fn (string $l) => str_starts_with($l, 'ERROR'));
```

**When to apply.** Any `foreach` whose only job is to find one element, set
a flag, and `break`. Any `array_filter(...)[0] ?? null` antipattern. Any
`count(array_filter(...)) === count($x)` test.

**When to avoid.**
- The callback has side effects you actually want on every element — use a
  real `foreach`.
- Iterating a `Generator` or `Iterator` — these helpers take `array` only;
  use `iterator_to_array` first or keep the loop.

**Rector.** `Rector\Php84\Rector\FuncCall\` rule set covers some patterns.
Manual review preferred — the intent of the loop is what matters.

## HTML5 DOM (`Dom\HTMLDocument`)

RFC: https://wiki.php.net/rfc/domdocument_html5_parser
Manual: https://www.php.net/manual/en/class.dom-htmldocument.php

`\Dom\HTMLDocument` is a standards-compliant HTML5 parser that obsoletes
the `DOMDocument::loadHTML()` workarounds. Two factory methods:

- `Dom\HTMLDocument::createFromString(string $source, int $options = 0, ?string $overrideEncoding = null)`
- `Dom\HTMLDocument::createFromFile(string $path, int $options = 0, ?string $overrideEncoding = null)`

Adds `querySelector`, `querySelectorAll`, `classList`, and the rest of
the modern DOM API.

```php
// PHP 8.3 — UTF-8 hack required, no querySelector
$dom = new \DOMDocument();
$dom->loadHTML(
    '<?xml encoding="UTF-8"><div>' . $html . '</div>',
    LIBXML_NONET | LIBXML_HTML_NOIMPLIED | LIBXML_HTML_NODEFDTD,
);
$xpath = new \DOMXPath($dom);
$nodes = $xpath->query("//a[contains(@class, 'external')]");

// PHP 8.4+
$doc = \Dom\HTMLDocument::createFromString(
    '<div>' . $html . '</div>',
    LIBXML_NOERROR,
    'UTF-8',
);
$nodes = $doc->querySelectorAll('a.external');
```

**When to apply.** Any code that parses HTML5 fragments — TYPO3 RTE
processors, content sanitizers, scrapers, link rewriters, Open Graph
extractors. The encoding pitfall (`<?xml encoding="UTF-8">` prefix) goes
away.

**When to avoid.**
- Strict XML / XHTML — use `\Dom\XMLDocument` (also new) or stick with
  `DOMDocument` for fully-formed XML.
- Code that must run on PHP 8.3 — keep the legacy parser behind an adapter
  (see `references/multi-version-adapters.md`).

**Rector.** No automated conversion; the legacy class stays available.
Migrate per-callsite, prefer write-once helpers in shared infrastructure.

## Implicit nullable parameter type — DEPRECATED

Manual: https://www.php.net/manual/en/migration84.deprecated.php

Until PHP 8.3 a `null` default value implicitly made a non-nullable
parameter type nullable. PHP 8.4 deprecates this; PHP 9.0 will remove it.

```php
// Deprecated in PHP 8.4 (was the recommended PHP 7.x style)
function fetch(string $id, Logger $logger = null): array { /* ... */ }

// Required in PHP 8.4+
function fetch(string $id, ?Logger $logger = null): array { /* ... */ }
```

This affects huge swathes of pre-8.0 code. The pattern was idiomatic for
years and survives in nearly every legacy codebase. Treat it as the
single largest mechanical migration item for 8.3 → 8.4.

**Detection.**
- PHPStan level 0+ with `phpstan-deprecation-rules` flags it.
- PHP itself emits `E_DEPRECATED` at runtime when a function is *declared*
  (not when called) on PHP 8.4+.
- Regex sweep is brittle but useful: search for `=\s*null\)` and inspect
  preceding parameter types.

**Rector.**
`Rector\Php84\Rector\ClassMethod\ExplicitNullableParamTypeRector` and the
equivalent for free functions and closures. Listed in `Php84SetList`.

```php
// Apply via rector.php
return RectorConfig::configure()
    ->withPhpSets(php84: true)
    ->withRules([
        \Rector\Php84\Rector\ClassMethod\ExplicitNullableParamTypeRector::class,
    ]);
```

**When to apply.** Always. Run Rector against the entire codebase, review
the diff, commit. The transformation is purely additive (`Type` → `?Type`)
and behavior-preserving.

**When to avoid.** Never — but be careful with library *consumers*. If your
public API has signature `Type $x = null`, fixing it to `?Type $x = null`
keeps callers compatible (they were already passing `null`); the LSP
implications only matter if subclasses override the parameter type.

## Modernization checklist for projects on 8.3 or earlier

Run in this order — each step builds on the previous:

1. **Bump baseline to 8.4** in `composer.json` (`"php": "^8.4"`) and CI
   matrix. Verify the autoloader and test bootstrap still work.

2. **Audit implicit-nullable parameters.** Run Rector with
   `ExplicitNullableParamTypeRector`. Review the diff, commit as a single
   "chore: explicit nullable parameter types (PHP 8.4)" change. This is
   the largest blast-radius change; isolate it.

3. **Run `Php84SetList`** for the rest of the automatable rewrites
   (notably `new` without parentheses).

4. **Audit `DOMDocument::loadHTML()` callsites.** For each, decide:
   migrate to `\Dom\HTMLDocument` (preferred), or wrap in an adapter that
   keeps the UTF-8 prefix hack until 8.5/9.0.

5. **Audit `array_filter`/`foreach + break` patterns.** Convert to
   `array_find`, `array_find_key`, `array_any`, `array_all` where the
   callback is pure.

6. **Identify property-hook candidates.** Look for:
   - `private $x; public function getX(): T { return $this->x; }
     public function setX(T $x): void { /* validate */ $this->x = $x; }`
   - Any `getX()` whose body is `return $this->a . $this->b` style
     concatenation/derivation.

7. **Identify asymmetric-visibility candidates.** Look for:
   - `private $x; public function getX(): T { return $this->x; }` with no
     setter at all → consider `public private(set)` plus internal mutators.
   - Value objects that should be observable but not externally writable.

8. **Replace `@deprecated` PHPDoc + `trigger_error` pairs** with
   `#[\Deprecated]` on functions, methods, and class constants you publish.

9. **Plan lazy-object adoption** in repositories and DI factories where
   you currently hand-write proxies. Not a refactor target — a design
   improvement to schedule.

10. **Update PHPStan** to a version with PHP 8.4 support; verify the
    deprecation-rules and strict-rules packages still pass.

After this checklist the codebase fully exploits 8.4. The follow-on
checklist for 8.5 lives in `php-8.5.md`.
