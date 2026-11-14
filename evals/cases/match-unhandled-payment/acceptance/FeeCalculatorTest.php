<?php

declare(strict_types=1);

namespace Cases\MatchUnhandledPayment\Tests\Acceptance;

use Cases\MatchUnhandledPayment\FeeCalculator;
use Cases\MatchUnhandledPayment\PaymentMethod;
use PHPUnit\Framework\TestCase;

final class FeeCalculatorTest extends TestCase
{
    public function testExistingFeesAreUnchanged(): void
    {
        $fees = new FeeCalculator();
        self::assertSame(30, $fees->fee(PaymentMethod::Card));
        self::assertSame(0, $fees->fee(PaymentMethod::Invoice));
        self::assertSame(45, $fees->fee(PaymentMethod::Paypal));
    }

    public function testKlarnaExistsAndHasItsFee(): void
    {
        self::assertSame(120, (new FeeCalculator())->fee(PaymentMethod::from('klarna')));
    }
}
