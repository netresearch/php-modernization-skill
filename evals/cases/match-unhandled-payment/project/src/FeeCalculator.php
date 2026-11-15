<?php

declare(strict_types=1);

namespace Acme\Payments;

final class FeeCalculator
{
    /** Fee in cents. */
    public function fee(PaymentMethod $method): int
    {
        return match ($method) {
            PaymentMethod::Card => 30,
            PaymentMethod::Invoice => 0,
            PaymentMethod::Paypal => 45,
        };
    }
}
