<?php

declare(strict_types=1);

namespace Cases\Php81FloorMoney\Tests\Acceptance;

use Cases\Php81FloorMoney\Money;
use PHPUnit\Framework\TestCase;

final class MoneyTest extends TestCase
{
    public function testPropertiesAreReadonly(): void
    {
        foreach ((new \ReflectionClass(Money::class))->getProperties() as $property) {
            self::assertTrue($property->isReadOnly(), $property->getName() . ' is not readonly');
        }
    }

    public function testAddition(): void
    {
        $sum = (new Money(150, 'EUR'))->add(new Money(50, 'EUR'));
        self::assertSame(200, $sum->amount());
        self::assertSame('EUR', $sum->currency());
    }

    public function testCurrencyMismatch(): void
    {
        $this->expectException(\InvalidArgumentException::class);
        (new Money(1, 'EUR'))->add(new Money(1, 'USD'));
    }
}
