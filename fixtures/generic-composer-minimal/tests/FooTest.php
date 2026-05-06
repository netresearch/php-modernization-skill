<?php

declare(strict_types=1);

namespace Fixtures\GenericComposerMinimal\Tests;

use Fixtures\GenericComposerMinimal\Foo;
use PHPUnit\Framework\TestCase;

final class FooTest extends TestCase
{
    public function testGreet(): void
    {
        self::assertSame('Hello, world', (new Foo())->greet('world'));
    }
}
