# Composer Package Metadata

**Source:** phpDocumentor/guides -- a monorepo whose ten `packages/*` directories are each published on their own
**Purpose:** Declare and verify the dependencies of a published package, where the code and the metadata disagree silently

## Two questions, two different answers

A dependency entry answers **what the code supports**. The installed version answers **what someone happened to resolve**. Reading the second and writing it into the first is the mistake this page exists for.

```jsonc
// psr/log resolved to 3.0.2, so this looked right:
"psr/log": "^3.0"

// but the code uses only LoggerInterface and LogLevel,
// unchanged across all three majors, and consumers could
// already resolve v1 and v2 through symfony/http-client:
"psr/log": "^1.0 || ^2.0 || ^3.0"
```

The first form is a **breaking change for consumers**. Somebody pinned to `psr/log` v2 by their framework can no longer install the package, and the change cannot ride along in a patch or minor release. In the case above a maintainer caught it in review: *"Adding `psr/log: ^3.0` to our requirements could be a breaking change for some projects and could therefore not be backported."*

## Deriving the constraint

1. **List the symbols the production code actually uses.** Not the package — the classes, interfaces and functions. `LoggerInterface`, `NullLogger` and `LogLevel` are a different question from "we use PSR-3".
2. **Find every major that provides them.** If a symbol exists unchanged in v1, v2 and v3, all three are supported.
3. **Check what your existing hard dependencies already allow.** A package that requires `symfony/http-client` already lets consumers resolve `psr/log: ^1|^2|^3`. Declaring that same range takes nothing away from anyone; declaring less does.
4. **Read the sibling packages in the same repository.** The established range is usually already written down next door. In the case above, `phpdocumentor/dev-server` carried `^1.0 || ^2.0 || ^3.0` the whole time.

## The one thing that forces a narrow range

Ask whether anything in the package **implements** the interface rather than merely consuming it.

Consuming `LoggerInterface` works across majors, because the call sites pass the same arguments. Implementing it does not: PSR-3 v3 declares `string|\Stringable $message` where v1 declares nothing, so a class implementing the interface is bound to one major. The same holds for any interface whose signatures changed between majors.

```bash
# The check that decides permissive vs. narrow
grep -rn "implements LoggerInterface\|extends AbstractLogger" packages/*/src
```

Empty result means the permissive range is safe. A hit means the narrow one is required, and the reason belongs in the commit message.

## Verifying a package, not a monorepo

In a monorepo the root install merges every dependency graph, so each package's classes are present regardless of what that package declares. Root-level checks are therefore **structurally blind** to per-package defects — a checker run against the root of the repository above reported `There were no symbols found, please check your configuration.`, because the root `composer.json` has no production `autoload` at all.

Verify per package, in isolation:

```bash
cp -r packages/<name> /tmp/check && cd /tmp/check
# only production code counts: dev autoload and dev requires are not shipped
jq 'del(.["autoload-dev"]) | del(.["require-dev"]) | del(.scripts)' composer.json > c && mv c composer.json
composer install --no-interaction --quiet
composer-require-checker check --config-file=/path/to/composer-require-checker.json composer.json
```

Run it once before the change and once after, both against the same baseline, or the two columns are not comparable.

## Reading the output without fooling yourself

Not every unknown symbol is a missing `require`:

| Symbol shape | What it means |
|---|---|
| `Vendor\Package\SomeClass` | a genuinely missing `require` |
| `filter_var`, `mb_strlen`, `ctype_alpha` | a missing `ext-filter` / `ext-mbstring` / `ext-ctype` |
| `UnknownSymbol`, `template`, `templateArray` | docblock generics — belong in the checker's `symbol-whitelist` |
| a class from a package listed under `suggest` | deliberately optional; declaring it changes behaviour |
| a class from a package that requires *this* one | declaring it closes a dependency ring; needs a code change |
| a v1-only and a v3-only class of the same library | a runtime `class_exists()` switch; unresolvable by construction, whitelist it |

## Two traps that cost real time

**A polyfilled function looks like a version-floor problem and is not.** `mb_str_pad()` exists from PHP 8.3, so a package declaring `php: ^8.1` that calls it looks broken. It is not, if `symfony/polyfill-mbstring` (v1.28+) reaches it — verify by installing the package standalone in a container of the lowest supported PHP version and calling the function. The defect is then an undeclared polyfill, not the PHP floor.

**A pinned checker can abort and look like a pass.** `composer-require-checker` 3.5.1 aborts on `symfony/config` v8 with `Syntax error, unexpected '(', expecting T_VARIABLE`, and `--ignore-parse-errors` does not help. The abort produces empty output that reads exactly like a clean run. Check the exit code and confirm the tool printed a verdict, not nothing.
