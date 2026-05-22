# Contracts & Invariants

Encode preconditions, postconditions, and invariants as runtime checks in the code path. Treat them as the bridge between a spec sentence and the tests that verify it: the same predicate becomes the inline assertion, the PHPUnit assertion, and (where it makes sense) the property-based test oracle.

## When to Use

- Value objects whose validity is structural ("amount never negative", "ISBN matches the checksum")
- DTOs that cross a domain boundary (HTTP edge → application core; queue payload → handler)
- Service methods that move a system between named states (orders, subscriptions, workflows)
- Money, quantities, identifiers with shape constraints
- Aggregate roots whose internal consistency outlives a single method

## When NOT to Use

- Plain CRUD glue, controller plumbing, framework callbacks
- Anything driven by user input → use validation and typed errors (`Symfony\Component\Validator`, `Webmozart\Assert` with caller-facing exceptions, form constraints)
- Doctrine entity hydration paths where reflection re-creates state (see `references/immutability-boundaries.md`)

Test: would a violation indicate the program is in an *impossible* state, given correct inputs? Yes → contract. No → validation.

## Tooling

### Native `assert()`

PHP compiles `assert()` calls under `zend.assertions`:

- `zend.assertions=1` (dev / CI): assertions run, failures throw `AssertionError`
- `zend.assertions=-1` (production): the compiler strips the calls entirely — zero cost

```ini
; php.ini (development / CI)
zend.assertions = 1
```

```ini
; php.ini (production)
zend.assertions = -1
```

(Note: `assert.exception` was deprecated in PHP 8.3 — under `zend.assertions=1`, failures already throw `AssertionError`. Don't set it on PHP 8.3+.)

Because `assert()` is strippable, do not rely on it for input validation, security checks, or side-effecting checks. It is for *invariants the code itself is supposed to maintain*.

Reference: <https://www.php.net/manual/en/function.assert.php>

### `webmozart/assert`

Use for **always-on** runtime checks at boundaries (input validation, library-API guard rails). The exceptions thrown are `InvalidArgumentException`; most application frameworks need an explicit exception-listener / handler to map that to a 4xx response (Symfony's `kernel.exception` listener, Laravel's `Handler::register`, Slim's error middleware, etc.). Configure that mapping or the failure surfaces as a generic 500.

```php
use Webmozart\Assert\Assert;

public function withdraw(int $amountCents): void
{
    Assert::positiveInteger($amountCents);       // caller's responsibility
    Assert::lessThanEq($amountCents, $this->balanceCents);

    $this->balanceCents -= $amountCents;
    \assert($this->balanceCents >= 0, 'invariant: balance >= 0');   // self-check
}
```

The split is deliberate: `Webmozart\Assert` for "is this caller using the API correctly?", native `assert()` for "is this object still in a valid state?".

### `@phpstan-assert` (static analysis)

Teach PHPStan that an assertion narrows a type, so subsequent code can rely on it without redundant guards:

```php
/**
 * @phpstan-assert non-empty-string $value
 */
private static function requireNonEmpty(string $value, string $field): void
{
    if ($value === '') {
        throw new \InvalidArgumentException(sprintf('%s must not be empty', $field));
    }
}
```

After `requireNonEmpty($email, 'email')`, PHPStan treats `$email` as `non-empty-string` for the remainder of the scope.

Reference: <https://phpstan.org/writing-php-code/phpdocs-basics#assertions>

### Custom `InvariantViolation`

For checks that must survive `zend.assertions=-1` in production, throw a domain-specific error. Reserve for crystalline guarantees whose violation must crash the request even in production:

```php
final class InvariantViolation extends \LogicException
{
    public static function of(string $message): self
    {
        return new self('invariant: ' . $message);
    }
}

public function applyDiscount(Money $discount): self
{
    if ($discount->isNegative()) {
        throw InvariantViolation::of('discount must not be negative');
    }
    $next = $this->total->minus($discount);
    if ($next->isNegative()) {
        throw InvariantViolation::of('total would go negative after discount');
    }
    return new self($next);
}
```

`LogicException` semantically means "the program is wrong", which is exactly what an invariant violation signals.

## Patterns

### Constructor-time invariants on value objects

The single best place to encode structural validity:

```php
final readonly class EmailAddress
{
    public function __construct(public string $value)
    {
        if (!filter_var($value, FILTER_VALIDATE_EMAIL)) {
            throw new \InvalidArgumentException(sprintf('invalid email: %s', $value));
        }
    }
}
```

Every place in the codebase that takes `EmailAddress` can rely on its validity without re-checking. Cross-link: `references/immutability-boundaries.md`, `references/type-safety.md`.

### Pre/postconditions on service methods

Document the contract in the docblock; enforce it at runtime.

```php
final class TransferService
{
    /**
     * Transfer funds between accounts.
     *
     * Contract:
     *   pre:  $amount->isPositive()                                        // caller's responsibility → always-on guard
     *   pre:  $from->balance->isGreaterThanOrEqual($amount)                // caller's responsibility → always-on guard
     *   post: $from->balance + $to->balance == old($from->balance + $to->balance)
     *   inv:  account balances never go negative
     */
    public function transfer(Account $from, Account $to, Money $amount): void
    {
        // Caller-facing preconditions: always-on. Webmozart throws
        // InvalidArgumentException, which the framework maps to a 4xx.
        Assert::true($amount->isPositive(), 'amount must be positive');
        Assert::true($from->balance->isGreaterThanOrEqual($amount), 'insufficient balance');

        $sumBefore = $from->balance->plus($to->balance);

        $from->debit($amount);
        $to->credit($amount);

        // Self-checks: strippable in production. They guard *our own*
        // implementation, not the caller.
        \assert($from->balance->plus($to->balance)->equals($sumBefore), 'postcondition: conservation');
        \assert(!$from->balance->isNegative() && !$to->balance->isNegative(), 'invariant: non-negative');
    }
}
```

### Property hooks as invariant points (PHP 8.4)

Hooks let you guard the *one* mutation site for a property, so the invariant cannot be bypassed by future setters:

```php
final class Inventory
{
    public int $available {
        set (int $value) {
            if ($value < 0) {
                throw InvariantViolation::of('available stock must not go negative');
            }
            $this->available = $value;
        }
    }
}
```

Cross-link: `references/php-8.4.md` for the wider property-hooks pattern.

## Property-Based Tests from Contracts

A postcondition is automatically a property: "for all valid inputs, the postcondition holds". Two routes in PHP:

### Targeted data providers (pragmatic)

PHPUnit data providers cover representative inputs. Paired with mutation testing (`infection/infection`), they catch most contract drift in domain code:

```php
use PHPUnit\Framework\Attributes\DataProvider;

public static function withdrawalCases(): iterable
{
    yield 'zero balance, zero withdrawal' => [0, 0, 0];
    yield 'full balance withdrawal' => [100, 100, 0];
    yield 'partial withdrawal' => [100, 30, 70];
}

#[DataProvider('withdrawalCases')]
public function testWithdrawalPreservesBalanceInvariant(int $initial, int $amount, int $expected): void
{
    $account = new Account($initial);
    $account->withdraw($amount);
    self::assertSame($expected, $account->balance);
    self::assertGreaterThanOrEqual(0, $account->balance);     // invariant
}
```

Pair with Infection (`references/mutation-testing.md`) to verify the assertions are load-bearing — a mutant that violates the contract must kill the test.

### `giorgiosironi/eris` (property-based)

`eris` is the maintained property-based testing library for PHPUnit. Useful where the input space is large and the postcondition is more tractable than enumerating cases:

```php
use Eris\Generator;
use Eris\TestTrait;

final class AccountPropertyTest extends \PHPUnit\Framework\TestCase
{
    use TestTrait;

    public function testWithdrawNeverGoesNegative(): void
    {
        $this->forAll(
            Generator\nat(1_000_000),
            Generator\seq(Generator\nat(10_000)),
        )->then(function (int $initial, array $ops): void {
            $account = new Account($initial);
            foreach ($ops as $op) {
                try {
                    $account->withdraw($op);
                } catch (\InvalidArgumentException) {
                    // validation rejection is fine
                }
                self::assertGreaterThanOrEqual(0, $account->balance);
            }
        });
    }
}
```

Be honest about the cost: `eris` is well-suited to algorithmic / value-object code and overkill for typical CRUD services. Use it for the 10% where postconditions are non-trivial and the input space is genuinely large.

Reference: <https://github.com/giorgiosironi/eris>

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using `assert()` for input validation | Use `Webmozart\Assert` or throw an `InvalidArgumentException`. `assert()` is strippable. |
| Custom `InvariantViolation` everywhere "to be safe" | Reserve it for crystalline production-critical guarantees; let strippable `assert()` carry the rest |
| Asserting on Doctrine-hydrated state in `__construct` | Hydration bypasses the constructor; assert in a separate validity method called after persistence loads |
| Postcondition that re-implements the function | The postcondition states the *property* (conservation, monotonicity, bounded range), not the steps |
| Sprinkling `assert()` decoratively in controllers | Gate by domain — value objects, services, aggregates. Not framework glue. |
| Property tests on every method | Pick the few methods whose postcondition is a real algebraic property; let providers + Infection cover the rest |

## Cross-References

- `references/type-safety.md` — typed properties, DTOs, value objects
- `references/immutability-boundaries.md` — where `readonly` is correct and where it is wrong
- `references/request-dtos.md` — boundary validation of incoming payloads
- `references/php-8.4.md` — property hooks for one-site enforcement
- `references/mutation-testing.md` — Infection as the strength-test for your assertions
- `references/phpstan-compliance.md` — `@phpstan-assert` and the type-narrowing payoff
