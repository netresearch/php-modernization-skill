<?php

declare(strict_types=1);

namespace Fixtures\FullyModern\Tests;

use Fixtures\FullyModern\Modern;
use PHPUnit\Framework\TestCase;

final class ModernTest extends TestCase
{
    public function testLabel(): void
    {
        self::assertSame('hello', (new Modern('hello'))->label());
    }
}
