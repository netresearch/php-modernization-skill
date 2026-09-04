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
expression without executing anything. Find the assignment, evaluate its
right-hand side, done:

```php
$statements = new ParserFactory()->createForHostVersion()->parse($code);

$assignments = new NodeFinder()->find($statements, static fn(Node $n): bool =>
    $n instanceof Assign || $n instanceof AssignOp || $n instanceof AssignRef);

// exactly one assignment, to the variable you expect
if (count($assignments) !== 1 || !$assignments[0] instanceof Assign) {
    return null;
}

$value = (new ConstExprEvaluator())->evaluateSilently($assignments[0]->expr);
```

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
new ConstExprEvaluator(static function (Expr $part) {
    // an undefined variable came out as null under the old include
    if ($part instanceof Variable) {
        return null;
    }
    if ($part instanceof ConstFetch && defined($part->name->toString())) {
        return constant($part->name->toString());
    }
    throw new ConstExprEvaluationException(
        'Expression of type ' . $part->getType() . ' cannot be evaluated'
    );
});
```

Two notes on that shape:

- Resolving a **defined** constant reads a value; it does not load a class.
  `ClassConstFetch` is not handled natively, so `Foo::BAR` reaches the fallback
  and is rejected — which is what you want from an untrusted file.
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
