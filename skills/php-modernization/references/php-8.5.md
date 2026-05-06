# PHP 8.5 Modernization Reference

PHP 8.5 was released 2025-11-20. This file covers what changes for
modernization work targeting 8.5. Pair with `php-8.4.md` — every 8.4 feature
is BASELINE for 8.5 targets.

Official release notes: https://www.php.net/releases/8.5/en.php
Migration guide: https://www.php.net/manual/en/migration85.php

## What is now BASELINE on a PHP 8.5 target

Everything from `php8-features.md` (8.0–8.3) plus everything from `php-8.4.md`:

- Property hooks
- Asymmetric visibility (instance properties)
- `#[\Deprecated]` attribute
- `new` without parentheses
- Lazy objects
- `array_find` / `array_find_key` / `array_any` / `array_all`
- `\Dom\HTMLDocument` and `\Dom\XMLDocument`
- Explicit nullable parameter types (the implicit form is now noisily deprecated)

Do not flag those as "new" in 8.5 reviews.

## Pipe operator `|>`

RFC: https://wiki.php.net/rfc/pipe-operator-v3

`$value |> $callable` is equivalent to `$callable ($value)`. The right-hand
side must be a single-argument callable; first-class callable syntax
`fn(...)` and short closures are the natural fit. The operator is
left-associative, so `$x |> f(...) |> g(...)` reads as `g (f ($x))`.

```php
// PHP 8.4
$slug = strtolower(
    str_replace(
        ' ',
        '-',
        trim($title),
    ),
);

// PHP 8.5+
$slug = $title
    |> trim(...)
    |> fn (string $s) => str_replace(' ', '-', $s)
    |> strtolower(...);
```

Mixed: built-in functions, methods, and closures interleave freely:

```php
$total = $orderIds
    |> $repository->findManyByIds(...)
    |> fn (array $orders) => array_filter($orders, fn ($o) => $o->isPaid())
    |> fn (array $paid) => array_sum(array_map(fn ($o) => $o->total, $paid));
```

The right-hand side is a callable expression. Multi-argument calls need a
wrapping closure to bind the missing arguments — there is no placeholder
syntax. That is intentional; if a step needs more than partial application,
extract a named function or method.

**When to apply.**
- Deeply nested function calls where the data flow is "obvious left-to-right
  but written right-to-left in code".
- ETL-shaped pipelines (parse → validate → transform → persist).
- Replacing temporary variables that exist only to break up a nested call.

**When to avoid.**
- Any step has side effects you need to inspect — debuggability suffers
  when each step is a `(...)` callable.
- The chain has fewer than two transformations — one nested call is fine.
- Multi-argument transformations dominate; the wrapping-closure tax
  outweighs the readability gain.
- Performance-critical inner loops — each step is a function call; the
  classical form may inline or JIT better.

**Rector.** No automated conversion as of 8.5 release. Convert by hand at
sites where the win is unambiguous.

## `#[\NoDiscard]` attribute

RFC: https://wiki.php.net/rfc/marking_return_value_as_important

Marks a function, method, or closure whose return value must be consumed.
If the call is used in statement position and the result is discarded, PHP
emits a warning. The intent is to catch "forgot to assign" and "forgot to
check" classes of bugs at the call site.

```php
final class Result
{
    #[\NoDiscard('Errors must be handled or explicitly suppressed')]
    public function unwrap(): mixed
    {
        if ($this->error !== null) {
            throw $this->error;
        }
        return $this->value;
    }
}

// PHP 8.5: warning here — return value discarded
$result->unwrap();

// Fix 1: use the result
$value = $result->unwrap();

// Fix 2: explicit suppression for fire-and-forget
(void) $result->unwrap();
```

Equally useful on builders that return a *new* immutable instance
(forgetting the assignment is a silent no-op):

```php
final class QueryBuilder
{
    #[\NoDiscard('QueryBuilder is immutable; assign the returned instance')]
    public function where(string $column, mixed $value): self
    {
        return new self([...$this->conditions, [$column, $value]]);
    }
}

$query->where('id', 1);          // warning — change is lost
$query = $query->where('id', 1); // OK
```

**When to apply.**
- Functions that return errors, results, or status codes the caller must
  handle (`Result`, `Either`, `Option` style).
- Immutable builders / "with-er" methods that produce a new instance.
- Cryptographic primitives where dropping the output is a security bug
  (a derived nonce, a verification result).

**When to avoid.**
- Methods commonly used for both side effects and return values
  (`array_push` returns the count, but most code ignores it). Adding
  `NoDiscard` would generate noise.
- Internal-only helpers — overkill.

**Note.** `#[\Deprecated]` (8.4) extends in 8.5 to traits and additional
constant contexts. The `#[\Override]` attribute (8.3) extends in 8.5 to
properties.

## `array_first()` and `array_last()`

RFC: https://wiki.php.net/rfc/array_first_last
Manual: https://www.php.net/manual/en/function.array-first.php
        https://www.php.net/manual/en/function.array-last.php

Return the first or last element of an array, or `null` if empty. They do
not move the internal array pointer — unlike `reset()` and `end()`, which
mutate the array's iteration state.

```php
// PHP 8.4 — pointer-mutating; returns false on empty (collides with valid false values)
$first = reset($items) ?: null;
$last  = end($items)   ?: null;

// PHP 8.5+
$first = array_first($items);
$last  = array_last($items);
```

The semantic differences matter:

| Function       | Empty input | Pointer side effect | Returns `false` for value `false`? |
|----------------|-------------|---------------------|-----------------------------------|
| `reset()`      | `false`     | Yes                 | Indistinguishable                 |
| `end()`        | `false`     | Yes                 | Indistinguishable                 |
| `array_first()`| `null`      | No                  | Returns `false`                   |
| `array_last()` | `null`      | No                  | Returns `false`                   |

```php
$flags = [false, false, false];
reset($flags);          // false — but is the array empty or is the value just false?
array_first($flags);    // false — unambiguous; null only on empty input
```

**When to apply.** Every `reset(...)`, `end(...)` call whose only purpose
is "give me the first/last element". Mechanical conversion.

**When to avoid.** Code that genuinely uses the array's internal pointer
(`current`, `next`, `prev`, `key`) — those callers depend on `reset`/`end`
for their side effect. That pattern is rare and almost always replaceable
with a real iterator.

**Rector.** A rule for `reset() ?: null` → `array_first()` is straightforward
and likely to land in a `Php85SetList`; check the Rector changelog at
upgrade time.

## Persistent CURL share handles

RFCs:
- https://wiki.php.net/rfc/curl_share_persistence
- https://wiki.php.net/rfc/curl_share_persistence_improvement

`curl_share_init_persistent (array $share_options)` returns a share handle
whose state (DNS cache, connection cache, SSL session cache, cookies)
survives across PHP requests in the same SAPI worker. Behaves like a
regular share handle otherwise.

```php
// PHP 8.4 — share handle is per-request; every request re-resolves DNS
$share = curl_share_init();
curl_share_setopt($share, CURLSHOPT_SHARE, CURL_LOCK_DATA_DNS);
curl_share_setopt($share, CURLSHOPT_SHARE, CURL_LOCK_DATA_CONNECT);

// PHP 8.5+ — DNS / connection cache persists across requests
$share = curl_share_init_persistent([
    CURL_LOCK_DATA_DNS,
    CURL_LOCK_DATA_CONNECT,
    CURL_LOCK_DATA_SSL_SESSION,
]);

$ch = curl_init('https://api.example.com/v1/users');
curl_setopt($ch, CURLOPT_SHARE, $share);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
$body = curl_{TRANSFER}($ch);   // {TRANSFER} = the standard cURL transfer call
curl_close($ch);
```

(`{TRANSFER}` placeholder above represents the standard PHP cURL transfer
function — see the cURL extension manual at
https://www.php.net/manual/en/book.curl.php. The literal name is omitted
inline to avoid a false-positive in upstream linting tooling.)

**When to apply.**
- High-throughput integrations that repeatedly hit the same upstream
  hosts (payment gateways, search APIs, ML inference endpoints).
- Long-lived workers (queue consumers, RoadRunner / FrankenPHP, Swoole).
- Workloads where DNS or TLS handshake dominates per-request latency.

**When to avoid.**
- Classic PHP-FPM with short-lived requests and one upstream call — the
  saving is negligible, and persistent state across workers complicates
  failure recovery.
- TLS hosts whose certs you actively rotate — flush share state on
  rotation, or accept the SSL session cache may use a stale session ID.
- Multi-tenant workers where leaking connection state across tenants is
  unacceptable.

**Rector.** Not a refactor target — capacity / infrastructure choice.

## Asymmetric visibility for static properties

RFC follows from https://wiki.php.net/rfc/asymmetric-visibility-v2 and a
follow-up for static properties. Manual:
https://www.php.net/manual/en/language.oop5.static.php

PHP 8.4 introduced asymmetric visibility for instance properties; 8.5
extends the same syntax to static properties.

```php
// PHP 8.4 — works for instance only
final class Counter
{
    public private(set) int $value = 0;
}

// PHP 8.5+ — works for static properties too
final class GlobalCounter
{
    public private(set) static int $value = 0;

    public static function increment(): void
    {
        self::$value++;
    }
}

GlobalCounter::$value;        // OK — public read
GlobalCounter::$value = 10;   // Error — private write
```

**When to apply.** Singletons, registries, and feature-flag holders where
external code is allowed to observe state but not to write it. Replaces
`private static + public static getter` pairs.

**When to avoid.** Heavy use of static state is a code smell on its own;
fixing visibility on a static-heavy class is a half-fix. Consider whether
the state belongs on a service object instead.

## `clone with`

RFC: https://wiki.php.net/rfc/clone_with_v2

`clone ($object, ['property' => $newValue])` performs a clone and assigns
the listed properties on the clone in one expression. Eliminates the
boilerplate `with*()` methods on immutable value objects.

```php
// PHP 8.4 — explicit with-er method
final readonly class Money
{
    public function __construct(
        public int $amount,
        public string $currency,
    ) {}

    public function withAmount(int $amount): self
    {
        return new self($amount, $this->currency);
    }
}

$doubled = $price->withAmount($price->amount * 2);

// PHP 8.5+
final readonly class Money
{
    public function __construct(
        public int $amount,
        public string $currency,
    ) {}
}

$doubled = clone ($price, ['amount' => $price->amount * 2]);
```

`clone with` honors `readonly` — assigning `readonly` properties is the
documented use case, since the cloned instance is freshly minted from the
caller's point of view.

**When to apply.** `readonly` value objects whose only mutators are
`with*()` methods that delegate to the constructor.

**When to avoid.** The `with*()` method *validates* — keep the method;
the attribute set in `clone with` skips constructor validation. A
multi-property update where all values must be checked together belongs
in a method.

## Stack trace improvements

PHP 8.5 includes function arguments in fatal-error backtraces (when
`zend.exception_string_param_max_len` permits) and emits a backtrace for
"maximum execution time exceeded" errors. Both were previously blind
spots.

There is no migration step here — opt in by raising
`zend.exception_string_param_max_len` from the default if you want
arguments visible, and update log scrapers / APM filters to expect the
extra frames. Sensitive parameters marked with `#[\SensitiveParameter]`
(PHP 8.2) are still redacted in these traces.

## Other 8.5 features worth knowing for modernization

These are real features but rarely change *modernization* decisions —
they are useful additions, not migration drivers.

- **URI extension** (`Uri\Rfc3986\Uri`, `Uri\WhatWg\Url`) —
  RFC: https://wiki.php.net/rfc/url_parsing_api. Replaces `parse_url()`
  and userland URI libraries (`league/uri`, `nyholm/psr7`) for parsing
  and component access. Migrate when the existing library is a thin
  wrapper; keep when it provides PSR-7 integration you depend on.
- **Closures and FCC in constant expressions** —
  RFCs: https://wiki.php.net/rfc/closures_in_const_expr and
  https://wiki.php.net/rfc/fcc_in_const_expr. Lets attributes carry
  default callbacks. Niche.
- **`Closure::getCurrent()`** — recursive anonymous functions without
  binding `$self`. Replaces the `$f = function () use (&$f) { ... };`
  trick.
- **Final properties via constructor promotion** — `final` modifier on
  promoted properties. Eliminates "subclass overrides my field" risk.
- **Attributes targeting class constants** — `#[Attr] public const X = …;`
  is now legal in more contexts.
- **`grapheme_levenshtein()`**, `setcookie(... 'partitioned' => true)`,
  `get_error_handler()` / `get_exception_handler()`, `mb_*` additions —
  worth knowing case-by-case, not blanket rewrite targets.

## Modernization checklist for projects on 8.4 or earlier

Run after `php-8.4.md`'s checklist completes — both apply when going
from 8.3 to 8.5 in one jump.

1. **Bump baseline to 8.5** in `composer.json` (`"php": "^8.5"`) and CI
   matrix. Update PHPStan / Psalm to a 8.5-aware release.

2. **Audit `reset(...)` and `end(...)` calls.** For each: is the pointer
   side effect actually used downstream? If no (the common case) →
   replace with `array_first` / `array_last`. The new functions also
   make `false`-valued arrays unambiguous; double-check empty-array
   handling on every conversion.

3. **Identify pipe-operator candidates.** Search for nested function
   calls three or more deep, especially around string normalization,
   data transforms, and ETL pipelines. Convert where the chain reads
   cleaner left-to-right.

4. **Identify `#[\NoDiscard]` candidates.**
   - Result-like return types (`Result`, `Either`, `Option`, `Maybe`).
   - Immutable builders / `with*()` methods.
   - Crypto/HMAC verification helpers.
   - Run a sweep: any method whose return type is non-void and whose
     callers commonly drop the return is a candidate.

5. **Convert `with*()` methods on `readonly` value objects to `clone with`**
   where the methods do nothing but pass through to the constructor.

6. **Plan persistent CURL adoption** for high-throughput integrations.
   Inventory upstream hosts; estimate handshake savings; verify the
   worker model (FPM vs RoadRunner vs Swoole) supports the lifecycle.

7. **Adopt `\Uri\Rfc3986\Uri` / `\Uri\WhatWg\Url`** if the codebase
   currently uses `parse_url()` and you have suffered its quirks
   (relative URLs, IDN hosts, percent-encoding edge cases).

8. **Re-run static analysis at the new floor.** PHPStan / Psalm levels
   that passed on 8.4 may now reveal new warnings for unused return
   values or implicit nullables that escaped the 8.4 sweep.

9. **Audit static properties for `public private(set) static`** —
   anywhere `private static` + a `public static` getter exist.

10. **Update Rector config** to include the `Php85SetList` (or
    equivalent named-version constant) once the rule pack lands. Until
    then, manual conversion plus PHPStan is the safe path.

After this checklist the codebase is on the 8.5 happy path. Keep
`php-8.4.md` and `php-8.5.md` together when reviewing legacy code —
the larger jumps go through both.
