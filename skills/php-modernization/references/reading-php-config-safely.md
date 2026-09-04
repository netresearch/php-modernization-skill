# Reading a PHP config file without executing it

Legacy PHP declares configuration as a PHP file that assigns an array —
`ext_emconf.php`, an old `config.php`, a generated `parameters.php`. Reading one
means getting the array out. `include` and the `eval` construct both **run** the
file, which is unacceptable when the file is uploaded, vendored, or otherwise not
yours.

## Do not strip, then evaluate

The tempting middle ground is to parse the file, delete everything that is not a
literal, print the survivors and run that through `eval`. It is fragile in a way
that is easy to miss, because the failure is silent:

```php
// The visitor deletes any node outside its allow-list
public function leaveNode(Node $node) {
    if (!($node instanceof Scalar || $node instanceof Array_ /* … */)) {
        return NodeTraverser::REMOVE_NODE;
    }
    return null;
}
```

`NodeTraverser` honours `REMOVE_NODE` **only where the parent structure is an
array** (`traverseArray`). In a single-node slot (`traverseNode`) the same return
value falls through to

```
LogicException: leaveNode() returned invalid value of type integer
```

A visitor cannot tell which slot it is in, so any node that happens to sit in a
single-node slot blows up the whole parse. The nodes that do this are ordinary:
the `Identifier` inside `declare(strict_types=1)`, the operands of a
`defined('X') or die()` guard, a `.` concatenation used as a value. Wrapped in
the usual `catch (\Throwable) { return null; }`, the caller sees "could not read
the file" and blames the file.

And the result still has to be executed.

## Evaluate the expression instead

`nikic/php-parser` ships `ConstExprEvaluator`, which computes a constant
expression without executing anything. Locate the expression that holds the
configuration, evaluate it, done.

Config files come in two shapes and both are worth handling. `return [...]` is
the modern one — Symfony's `config/bundles.php`, most Laravel config; the
assignment (`$EM_CONF[$key] = [...]`, `$config = [...]`) is the older one:

```php
$statements = new ParserFactory()->createForHostVersion()->parse($code);

// Run NameResolver if you intend to accept ::class - see the fallback below
$traverser = new NodeTraverser(new NameResolver());
$statements = $traverser->traverse($statements);

$expression = null;

// shape 1: a single top-level `return <expr>;`
$returns = array_values(array_filter(
    $statements,
    static fn(Node $n): bool => $n instanceof Stmt\Return_ && $n->expr !== null
));
if (count($returns) === 1) {
    $expression = $returns[0]->expr;
}

// shape 2: exactly one assignment, and it must write to the variable you expect
if ($expression === null) {
    $assignments = (new NodeFinder())->find($statements, static fn(Node $n): bool =>
        $n instanceof Assign || $n instanceof AssignOp || $n instanceof AssignRef);

    if (count($assignments) !== 1 || !$assignments[0] instanceof Assign) {
        return null;                    // none, or more than one - ambiguous
    }
    $target = $assignments[0]->var;
    $base   = $target instanceof ArrayDimFetch ? $target->var : $target;
    if (!$base instanceof Variable || $base->name !== $expectedVariable) {
        return null;                    // an assignment, but not the one we want
    }
    $expression = $assignments[0]->expr;
}

$value = (new ConstExprEvaluator())->evaluateSilently($expression);
```

Two details that are easy to skip and both bite:

- `NodeFinder::find()` walks **every** descendant, not the top level. Without the
  target check, an unrelated assignment inside a closure or a dead branch is
  evaluated as if it were the configuration; with more than one assignment in the
  file the count check rejects a file that is perfectly fine. Checking the target
  variable is what makes "exactly one" meaningful.
- Deciding between the two shapes on *count* rather than on the first match keeps
  a file that both returns and assigns from being read half-way.

Everything else in the file — a `declare`, a guard clause, a function
declaration, a stray comment — is simply not looked at, because nothing runs.
That is the point: you no longer need an allow-list of "harmless" syntax.

`ConstExprEvaluator` natively handles scalars, arrays, unary and binary
operators, ternaries, `ArrayDimFetch` with a dimension, and the `true`/`false`/
`null` constants. It calls the fallback for anything else and, with no fallback
supplied, throws `ConstExprEvaluationException`. It never calls `constant()`,
`define()`, `call_user_func`, or the `eval` construct — verified by reading the
class.

## The fallback is where the semantics live

Supply one only to reproduce behaviour you must keep, and make it reject rather
than guess:

```php
/** @var array<string, mixed> $allowedConstants  e.g. ['PHP_EOL' => PHP_EOL] */
new ConstExprEvaluator(static function (Expr $part) use ($allowedConstants) {
    // an undefined variable came out as null under the old include
    if ($part instanceof Variable) {
        return null;
    }
    // Foo::class is a name, not a value - it loads nothing.
    // Only correct after NameResolver has run, otherwise `use` aliases resolve wrong.
    if ($part instanceof ClassConstFetch
        && $part->class instanceof Name
        && $part->name instanceof Identifier
        && $part->name->toLowerString() === 'class'
    ) {
        return $part->class->toString();
    }
    if ($part instanceof ConstFetch
        && array_key_exists($name = $part->name->toString(), $allowedConstants)
    ) {
        return $allowedConstants[$name];
    }
    throw new ConstExprEvaluationException(
        'Expression of type ' . $part->getType() . ' cannot be evaluated'
    );
});
```

Three notes on that shape:

- **Do not resolve constants by `defined()` + `constant()`.** That accepts *any*
  constant the host process happens to have defined, so an untrusted file can
  name `DB_PASSWORD` or an API key and lift its value into a config value you
  then store, log or display. Pass an explicit allowlist of the constants the
  format is documented to support; anything else is rejected like any other
  non-literal.
- **`::class` is safe and worth supporting**, because it is resolved from the
  syntax tree and loads nothing — `FrameworkBundle::class` as an array key is
  ordinary in Symfony config. It is only *correct* once `NameResolver` has run,
  though: without it, a short name under a `use` alias resolves to the wrong
  string. Any other `ClassConstFetch` (`Foo::BAR`) stays rejected.
- A function call in a value (`'x' => trim(' y ')`) is likewise rejected. If the
  old behaviour executed it, that is a behaviour change worth stating explicitly
  rather than papering over.

## Pin the old contract before you swap the implementation

The replacement is only safe if you know what the old one did. Measure, do not
reason: run the current implementation over the inputs you care about, record
accepted/rejected **and the parsed value**, then compare after the change.

A sweep over 181 real `ext_emconf.php` files from public repositories, comparing
`md5(serialize($result))` on both implementations, gave 175 identical, 6
previously-rejected files now accepted, and 0 regressions and 0 value
differences. That table is what makes the swap reviewable; "it looks equivalent"
is not.
