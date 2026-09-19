# Lexing PHP Across Versions

Read this before writing anything that reads PHP source as tokens — a doc
renderer, a code-modification tool, a linter, a signature parser.

## `token_get_all()` is version-dependent, and silently so

The tokenizer is not stable across releases. PHP merges token *kinds* between
versions, and text that one release lexes as several tokens a later one lexes as
one. The same source then reads differently depending on which PHP is running
your tool — with no error, no warning, and no deprecation.

Three merges in recent releases:

| text | ≤ 8.3 | 8.4 | 8.5 |
|---|---|---|---|
| `private(set)` | `T_PRIVATE` `(` `T_STRING` `)` | `T_PRIVATE_SET` | `T_PRIVATE_SET` |
| `\|>` | `'\|'` `'>'` | `'\|'` `'>'` | `T_PIPE` |
| `(void)` | `(` `T_STRING` `)` | `(` `T_STRING` `)` | `T_VOID_CAST` |

A tool that counts brackets, splits on a delimiter or classifies a token by its
id will disagree with itself across a CI matrix. The failure mode is the worst
kind: it renders or rewrites *something*, just not the same something.

`TOKEN_PARSE` does not help — it makes the problem louder, not smaller. It runs
the grammar of the *running* PHP, so source using newer syntax raises
`CompileError`, which is not a `ParseError` and is therefore not caught by the
obvious `try { … } catch (ParseError)`.

## Prefer php-parser's emulative lexer

`nikic/php-parser` already solves this, and solving it is its job rather than
yours:

```php
use PhpParser\ParserFactory;
use PhpParser\PhpVersion;

// The newest grammar the LIBRARY knows — not the PHP running this process.
$parser = (new ParserFactory())->createForVersion(PhpVersion::getNewestSupported());
```

Its `Emulative` lexer normalises exactly these merges, so source using 8.5 syntax
parses on an 8.2 runtime and yields the same tree on every version. Targeting a
specific grammar (`PhpVersion::fromString('8.4')`) is also possible, which raw
`token_get_all()` cannot do at all.

Keep the *text* the author wrote by slicing the original string at the node
offsets, not by printing the tree back:

```php
$text = substr($source, $node->getStartFilePos(),
    $node->getEndFilePos() - $node->getStartFilePos() + 1);
```

A pretty-printer normalises spacing and drops comments — fine for rewriting
code, wrong for anything that must reproduce the input.

## If you must use `token_get_all()`, pin the token set

Sometimes the raw tokenizer is the right tool — it is dependency-free, it never
rejects malformed input, and for a renderer that must degrade gracefully rather
than throw, that leniency is the feature. Then make the version drift *fail a
test* instead of reaching a user:

```php
// Every token kind this tool has been checked against.
$known = file(__DIR__ . '/token-kinds.txt', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
$found = array_keys(get_defined_constants(true)['tokenizer']);

self::assertSame([], array_values(array_diff($found, $known)));
```

A kind absent from the list fails on the first CI run of the version that
defines it. A new name is a *question* — does this kind merge text an earlier
version lexed apart? — not automatically a defect. Pair it with a recorded
token-stream fixture (signature → token texts) asserted on every matrix entry.

Two things that make such a guard real rather than decorative:

- **The matrix must contain the versions that merge.** A guard against an 8.5
  merge cannot fail on 8.2. Widening the matrix is part of the fix, not a
  separate nicety.
- **Pin the token *class* you branch on, not the raw id.** Ids change for
  reasons that never reach your code — `__PROPERTY__` is `T_STRING` on 8.3 and
  `T_PROPERTY_C` on 8.4 — and a fixture pinning raw ids goes red for a
  non-reason, which trains people to edit the fixture.

## Reference parsers make a good oracle

When the question is "is this text valid X?" and X is a syntax somebody else
already specifies, use their parser as an **oracle** in your tests even if you
do not use it in production. Parse the same input both ways and diff the
verdicts.

For PHP type syntax that is `phpstan/phpdoc-parser`:

```php
use PHPStan\PhpDocParser\{Lexer\Lexer, Parser\ConstExprParser, Parser\ParserException,
    Parser\TypeParser, Parser\TokenIterator, ParserConfig};

$config = new ParserConfig([]);
$lexer  = new Lexer($config);
$types  = new TypeParser($config, new ConstExprParser($config));

$isValidType = static function (string $type) use ($lexer, $types): bool {
    try {
        $it = new TokenIterator($lexer->tokenize($type));
        $types->parse($it);
        $it->consumeTokenType(Lexer::TOKEN_END); // without this, `int foo bar` "parses"
        return true;
    } catch (ParserException) {
        return false;
    }
};
```

Catch `ParserException`, not `\Throwable`. Every rejection path in the library
raises that one class — measured on 2.3.5 over `int foo bar`, `???`, `''`,
`array{` and `|` — so the broad catch buys nothing and silently turns a bug in
your own oracle into "not a valid type", which is the answer you are least
likely to question.

The `TOKEN_END` assertion is the part people forget: `parse()` stops at the
first thing it does not understand and reports success for the prefix.

An oracle turns a run of judgement calls into measurements, and it finds errors
in *both* directions — syntax you wrongly reject (`0|1` and `-1` are types;
`Foo::CONST_*` is a type) and syntax you wrongly accept. Report the residual
disagreements explicitly and say which are deliberate; a few usually are, because
a renderer may legitimately accept text a type parser rejects.

## Testing across versions without a full install per version

A `vendor/` resolved on a newer PHP refuses to load on an older one — Composer
writes `vendor/composer/platform_check.php`, which aborts with a message about
the platform requirement. To run one suite on many versions without a Composer
install per version, copy the tree and empty that one file **in the copy**:

```bash
TMP=$(mktemp -d)                 # never leave this unset: `cp -a … "$TMP/"`
trap 'rm -rf "$TMP"' EXIT        # would then target / and the mount would be ":/app"

cp -a src tests vendor phpunit.xml.dist "$TMP/"
echo '<?php' > "$TMP/vendor/composer/platform_check.php"

for v in 8.2 8.3 8.4 8.5; do
  docker run --rm --user "$(id -u):$(id -g)" -v "$TMP:/app" -w /app \
    "php:$v-cli" vendor/bin/phpunit --testsuite=unit
done
```

Use it for a differential — same tree, many runtimes, diff the output — not as
the final gate, because the resolved dependency *versions* are still the ones
the newer PHP picked. Where the resolution itself matters, do the real
per-version `composer install`. (`--user` keeps the container from leaving
root-owned files in the bind mount; see the docker-development skill.)
