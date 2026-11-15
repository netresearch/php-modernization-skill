<?php

declare(strict_types=1);

namespace Acme\Pricing;

final readonly class Price
{
    public const CURRENCY = 'EUR';

    public function __construct(private int $cents)
    {
    }

    public function cents(): int
    {
        return $this->cents;
    }

    public function format(): string
    {
        return number_format($this->cents / 100, 2) . ' ' . self::CURRENCY;
    }
}
