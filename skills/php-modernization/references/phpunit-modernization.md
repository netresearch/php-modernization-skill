# PHPUnit Modernization (12 → 13)

PHPUnit 12.5 deprecated and 13 removed several long-standing idioms. The
biggest blast-radius change for modernization passes is the **strict
mock-vs-stub distinction**, which routinely produces 100s of "PHPUnit
notices" and `InvocationStubber::with()` PHPStan errors when the
distinction isn't honoured.

## Mock vs Stub: the decision that matters

| Object | Created via | Has `->expects(...)` | Has `->with(...)` | Verifies args |
|---|---|---|---|---|
| **Stub** | `createStub(X)` | ✗ | ✗ | ✗ — only returns values |
| **Mock** | `createMock(X)` | ✓ | ✓ (after `expects`) | ✓ |
| **Mock-as-stub** | `createMock(X)` | ✗ (just `method`) | ✗ in 13 | — was deprecated path |

PHPUnit 12.5 deprecated and 13 removed the "mock-as-stub" pattern
(`$mock->method('x')->with($arg)->willReturn(...)` without `expects`).
The chain receiver is now `InvocationStubber`, which has no `with()`.

### Decision tree for migration

```
Does the test care what argument the call receives?
├─ NO  → it's a stub
│       $stub = self::createStub(X::class);
│       $stub->method('foo')->willReturn($value);
│
└─ YES → it's a mock; require expectation
        $mock = self::createMock(X::class);
        $mock->expects(self::once())     // see "matcher choice" below
            ->method('foo')
            ->with($expectedArg)         // ← THIS is the assertion
            ->willReturn($value);
```

`createMock`/`createStub` are static methods on `TestCase`; PHPStan
flags `$this->createStub(...)` as `staticMethod.dynamicCall`. Use
`self::` consistently (or migrate the whole file at once if your repo
convention is `$this->`).

## Common antipatterns

### ❌ Mechanical `createMock` → `createStub`

The single biggest mistake when chasing the "no expectations were
configured" notice (1698-occurrence-class). Substituting `createStub`
**deletes argument verification** if `->with(...)` was present. Always
inspect: if `->with(...)` is in the chain, it was a mock — promote it
to `expects()` form, don't strip it.

### ❌ `self::any()` in PHPUnit 13

`PHPUnit\Framework\TestCase::any()` is hard-deprecated
([phpunit#6461](https://github.com/sebastianbergmann/phpunit/issues/6461))
and PHPStan flags every call as `method.deprecated`. **Pick the matcher
that matches the test's actual call semantics** — don't blanket-replace
with `once()`, that adds a strict assertion the original test didn't
make and will break paths that legitimately invoke the method 0 or 2+
times.

| Original intent | Use |
|---|---|
| "Method must be called exactly once" | `self::once()` |
| "Method may be called any number of times, including 0" (true `any()`) | `self::atLeast(0)` (== effectively `any` but accepted by PHPStan) — or rethink whether this is a stub, not a mock |
| "Method must be called at least once" | `self::atLeastOnce()` |
| "Method must NOT be called" | `self::never()` |
| "Method must be called exactly N times" | `self::exactly(N)` |

For a mass-conversion of legacy `->method('x')->with(...)` chains
without `expects()` — these were treated as a stub-style call by
PHPUnit pre-12, and the framework didn't verify count at all.
`atLeastOnce()` is usually the safest faithful translation; `once()`
is correct only when you've verified the test path invokes the method
exactly once.

### ❌ `expectNotToPerformAssertions()` with mock expectations

```php
public function testEarlyReturn(): void
{
    $this->expectNotToPerformAssertions();
    $mock->expects(self::never())->method('save');  // ← THIS counts
    $service->process(invalidInput: true);
}
```

`expects(self::never())` IS an assertion. PHPUnit 12+ flags this as
risky: "expectsNoAssertions but performed N assertions". Drop the
`expectNotToPerformAssertions()` — the mock expectation is the proof.

### ❌ Leaving `->with(...)` on stub-style chains

```php
// Deprecated in 12.5, hard-removed in 13
$stub->method('foo')->with('x')->willReturn($v);
```

Either promote to mock (`expects()` form) or drop `with()`. Don't leave
it on a stub chain.

## When to use `#[AllowMockObjectsWithoutExpectations]`

Apply at **class level** when:

- The same fixture (e.g. `protected ServiceX $service` in `setUp`) is
  used both as a stub on some tests and a mock on others, and
- Refactoring `setUp` to per-test creation would yield no semantic gain.

Don't apply as a default escape hatch. The notice exists to push
genuinely-stub use of `createMock` over to `createStub`.

## Risky test patterns

| Risky message | Fix |
|---|---|
| `Test code did not remove its own exception handlers` | A parent (often Symfony `KernelTestCase`) registered one; add `tearDown` that calls `restore_exception_handler()` until the count balances. |
| `This test did not perform any assertions` | Add the assertion the test name implies, or use `expectNotToPerformAssertions()` (only if no mock expectations either). |
| `expectsNoAssertions but performed N` | See antipattern above — drop the expects-no-assertions call. |

## PHPStan stub fingerprint

`phpstan/phpstan-phpunit` ships a stub for `MockObject` that's keyed to
the installed PHPUnit major. After bumping PHPUnit (or after a rebase
that pulled in such a bump), run:

```bash
composer install                            # sync vendor
vendor/bin/phpstan clear-result-cache       # invalidate analysis cache
vendor/bin/phpstan analyse                  # re-run from cold cache
```

Without the cache flush, local PHPStan can keep reporting clean while
CI fails — the stale `tmpDir` holds analyses keyed to the old stub.

## Mass-conversion playbook

When a project has 100+ deprecated `->with()` sites:

1. **Inventory**: `grep -rn "->method(.*->with" tests/ --include="*.php"`
   gives the candidate sites. Don't trust line counts; one site may span
   multiple lines.
2. **Read the production caller** for each method. The arg passed at
   the call site is what `with(...)` should assert. Don't guess.
3. **Promote, don't strip**: insert `->expects(self::once())` before
   `->method(...)`. Keep `->with(...)` exactly as it was.
4. **Verify cold**: clear PHPStan `tmpDir` and re-run, OR run analyze
   inside Docker if CI uses Docker — local-only verify can lie.
5. **Run the affected tests** to confirm `once()` matches the actual
   call count on the test path.

## Verification commands

```bash
# Notice count (the agent should drive this to 0)
vendor/bin/phpunit --display-all-issues 2>&1 | grep -E "PHPUnit notice|tests triggered"

# Risky count
vendor/bin/phpunit 2>&1 | grep -E "Risky:|There (was|were) [0-9]+ risky"

# Cold PHPStan
vendor/bin/phpstan clear-result-cache
vendor/bin/phpstan analyse --no-progress
```
