<?php

declare(strict_types=1);

namespace Acme\Pricing\Tests\Acceptance;

use Acme\Pricing\Cart;
use Acme\Pricing\Discount;
use Acme\Pricing\Price;
use PHPUnit\Framework\TestCase;

final class PricingTest extends TestCase
{
    public function testValueObjectsAreReadonlyAndTyped(): void
    {
        foreach ([Price::class, Discount::class] as $class) {
            foreach ((new \ReflectionClass($class))->getProperties() as $property) {
                self::assertTrue($property->isReadOnly(), "{$class}::\${$property->getName()} is not readonly");
                self::assertTrue($property->hasType(), "{$class}::\${$property->getName()} has no type");
            }
        }
    }

    public function testTheCartStillCollects(): void
    {
        $cart = new Cart();
        $cart->add(new Price(1000));
        $cart->add(new Price(500));
        self::assertSame(1500, $cart->total()->cents());
        self::assertSame(1200, $cart->total(new Discount(20))->cents());
        self::assertSame(750, $cart->total(new Discount(90))->cents());
        self::assertSame('15.00 EUR', $cart->total()->format());
    }
}
